from __future__ import annotations

import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from ldap_core import SUBTREE, config, get_service_connection, logger


def _group_base() -> str:
    base = getattr(config, "LDAP_GROUP_BASE_DN", None)
    if not base:
        raise RuntimeError(
            "LDAP_GROUP_BASE_DN is not set in config.py. "
            "Please add it, e.g.: LDAP_GROUP_BASE_DN = 'ou=groups,dc=example,dc=org'"
        )
    return base


def _user_base() -> str:
    base = getattr(config, "LDAP_USER_BASE_DN", None)
    if not base:
        raise RuntimeError(
            "LDAP_USER_BASE_DN is not set in config.py. "
            "Please add it, e.g.: LDAP_USER_BASE_DN = 'ou=people,dc=example,dc=org'"
        )
    return base

EXCEL_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
EXCEL_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


HEADERS = [
    "uid",
    "cn",
    "givenName",
    "sn",
    "gidNumber",
    "primaryGroup",
    "primaryGroupStatus",
    "secondaryGroups",
    "homeDirectory",
    "loginShell",
    "dn",
]


def _attr_value(entry: Any, name: str, default: str = "") -> str:
    attr = getattr(entry, name, None)
    if attr is None:
        return default
    value = getattr(attr, "value", None)
    if value is None:
        return default
    return str(value)


def _attr_values(entry: Any, name: str) -> list[str]:
    attr = getattr(entry, name, None)
    if attr is None:
        return []
    values = getattr(attr, "values", None)
    if values is None:
        value = getattr(attr, "value", None)
        return [] if value in (None, "") else [str(value)]
    return [str(v) for v in values if v not in (None, "")]


def _safe_sheet_name(name: str, used: set[str]) -> str:
    """Return an Excel-safe worksheet name, unique within the workbook."""
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", (name or "Sheet")).strip()
    cleaned = cleaned or "Sheet"
    cleaned = cleaned[:31]

    candidate = cleaned
    n = 2
    while candidate.lower() in used:
        suffix = f"_{n}"
        candidate = f"{cleaned[:31 - len(suffix)]}{suffix}"
        n += 1
    used.add(candidate.lower())
    return candidate


def _column_letter(index: int) -> str:
    """1-based column index to Excel column letters."""
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _cell_xml(row_idx: int, col_idx: int, value: Any, style: int | None = None) -> str:
    cell_ref = f"{_column_letter(col_idx)}{row_idx}"
    style_attr = f' s="{style}"' if style is not None else ""

    if value is None:
        value = ""

    if isinstance(value, int):
        return f'<c r="{cell_ref}"{style_attr}><v>{value}</v></c>'

    text = str(value)
    if text == "":
        return f'<c r="{cell_ref}"{style_attr} t="inlineStr"><is><t></t></is></c>'

    preserve = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    return (
        f'<c r="{cell_ref}"{style_attr} t="inlineStr"><is><t{preserve}>'
        f"{escape(text)}"
        "</t></is></c>"
    )


def _sheet_xml(rows: list[list[Any]]) -> str:
    """Build a simple worksheet XML document from rows of values."""
    sheet_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            # Header style for row 1.
            cells.append(_cell_xml(r_idx, c_idx, value, style=1 if r_idx == 1 else None))
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    col_widths = {
        1: 18,  # uid
        2: 28,  # cn
        3: 18,  # givenName
        4: 18,  # sn
        5: 12,  # gidNumber
        6: 24,  # primaryGroup
        7: 20,  # status
        8: 40,  # secondaryGroups
        9: 42,  # homeDirectory
        10: 18,  # loginShell
        11: 55,  # dn
    }
    cols = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in col_widths.items()
    )

    freeze = (
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
    )
    dimension = f"A1:{_column_letter(len(HEADERS))}{max(1, len(rows))}"

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{EXCEL_NS_MAIN}" xmlns:r="{EXCEL_NS_REL}">'
        f'<dimension ref="{dimension}"/>'
        f"{freeze}"
        f"<cols>{cols}</cols>"
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        '<autoFilter ref="A1:K1"/>'
        "</worksheet>"
    )


def _workbook_xml(sheets: list[dict[str, Any]]) -> str:
    sheet_xml = []
    for idx, sheet in enumerate(sheets, start=1):
        sheet_xml.append(f'<sheet name="{escape(sheet["name"])}" sheetId="{idx}" r:id="rId{idx}"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{EXCEL_NS_MAIN}" xmlns:r="{EXCEL_NS_REL}">'
        '<workbookPr date1904="false"/>'
        '<bookViews><workbookView activeTab="0"/></bookViews>'
        f'<sheets>{"".join(sheet_xml)}</sheets>'
        "</workbook>"
    )


def _workbook_rels_xml(sheets: list[dict[str, Any]]) -> str:
    rels = []
    for idx, _sheet in enumerate(sheets, start=1):
        rels.append(
            f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        )
    rels.append(
        f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PACKAGE_NS_REL}">{"".join(rels)}</Relationships>'
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PACKAGE_NS_REL}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _content_types_xml(sheet_count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for idx in range(1, sheet_count + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(overrides)}'
        "</Types>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{EXCEL_NS_MAIN}">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        "</fonts>"
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def _core_xml(created: datetime) -> str:
    stamp = created.replace(microsecond=0).isoformat() + "Z"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>LDAP users by primary group</dc:title>"
        "<dc:creator>Lorien LDAP Admin</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _app_xml(sheet_names: list[str]) -> str:
    names_xml = "".join(f"<vt:lpstr>{escape(name)}</vt:lpstr>" for name in sheet_names)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Lorien LDAP Admin</Application>"
        f'<TitlesOfParts><vt:vector size="{len(sheet_names)}" baseType="lpstr">{names_xml}</vt:vector></TitlesOfParts>'
        "</Properties>"
    )


def _make_xlsx(sheets: list[dict[str, Any]]) -> bytes:
    out = io.BytesIO()
    created = datetime.utcnow()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        zf.writestr("_rels/.rels", _root_rels_xml())
        zf.writestr("docProps/core.xml", _core_xml(created))
        zf.writestr("docProps/app.xml", _app_xml([s["name"] for s in sheets]))
        zf.writestr("xl/workbook.xml", _workbook_xml(sheets))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(sheets))
        zf.writestr("xl/styles.xml", _styles_xml())
        for idx, sheet in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", _sheet_xml(sheet["rows"]))
    return out.getvalue()


def _group_sort_key(group: dict[str, Any]) -> tuple[int, int, str]:
    gid = group.get("gidNumber")
    cn = group.get("cn") or ""
    status = group.get("status") or ""
    try:
        gid_int = int(gid)
    except Exception:
        gid_int = 999999

    staff_gid = int(getattr(config, "STAFF_GID_NUMBER", 500))
    if gid_int == staff_gid:
        return (0, gid_int, cn)
    if 1900 <= gid_int <= 2200:
        return (1, gid_int, cn)
    if status != "OK":
        return (3, gid_int, cn)
    return (2, gid_int, cn)


def _row_sort_key(row: dict[str, Any]) -> str:
    return (row.get("uid") or "").lower()


def build_users_by_primary_group_export() -> tuple[bytes, str, dict[str, int]]:
    """Return (xlsx_bytes, filename, stats) for an LDAP user audit workbook.

    The workbook contains an "All Users" sheet and one sheet for every primary
    gidNumber that currently has users. Groups with no primary users are left
    out. Users are sorted by uid. Secondary groups are semicolon-separated.
    """
    conn = get_service_connection()
    try:
        conn.search(
            search_base=_group_base(),
            search_filter="(objectClass=posixGroup)",
            search_scope=SUBTREE,
            attributes=["cn", "gidNumber", "memberUid"],
        )

        groups_by_gid: dict[int, dict[str, Any]] = {}
        secondary_by_uid: dict[str, list[str]] = defaultdict(list)
        duplicate_gids: set[int] = set()
        bad_groups = 0

        for e in conn.entries:
            cn = _attr_value(e, "cn")
            gid_raw = _attr_value(e, "gidNumber")
            try:
                gid = int(gid_raw)
            except Exception:
                bad_groups += 1
                continue

            if gid in groups_by_gid:
                duplicate_gids.add(gid)
            groups_by_gid.setdefault(
                gid,
                {
                    "gidNumber": gid,
                    "cn": cn,
                    "dn": e.entry_dn,
                    "status": "OK",
                },
            )

            for uid in _attr_values(e, "memberUid"):
                secondary_by_uid[uid].append(cn)

        conn.search(
            search_base=_user_base(),
            search_filter="(uid=*)",
            search_scope=SUBTREE,
            attributes=[
                "uid",
                "cn",
                "givenName",
                "sn",
                "gidNumber",
                "homeDirectory",
                "loginShell",
            ],
        )

        all_rows: list[dict[str, Any]] = []
        grouped_rows: dict[str, dict[str, Any]] = {}
        missing_primary_groups = 0
        invalid_primary_gids = 0

        for e in conn.entries:
            uid = _attr_value(e, "uid")
            if not uid:
                # The export is meant to be cross-checked by uid; skip entries
                # that do not even have a uid.
                continue

            gid_raw = _attr_value(e, "gidNumber")
            primary_group = None
            primary_group_cn = ""
            primary_status = "OK"
            group_key = "missing_gid"

            try:
                gid = int(gid_raw)
                primary_group = groups_by_gid.get(gid)
                if primary_group:
                    primary_group_cn = primary_group.get("cn") or ""
                    group_key = f"gid:{gid}"
                    if gid in duplicate_gids:
                        primary_status = "Duplicate gidNumber objects"
                else:
                    missing_primary_groups += 1
                    primary_group_cn = f"Missing posixGroup for gid {gid}"
                    primary_status = "Missing primary group object"
                    group_key = f"missing:{gid}"
            except Exception:
                invalid_primary_gids += 1
                gid = gid_raw
                primary_group_cn = "Invalid or missing gidNumber"
                primary_status = "Invalid/missing primary gidNumber"
                group_key = "invalid_gid"

            secondary_groups = sorted(
                {
                    name
                    for name in secondary_by_uid.get(uid, [])
                    if name and name != primary_group_cn
                },
                key=str.lower,
            )

            row = {
                "uid": uid,
                "cn": _attr_value(e, "cn"),
                "givenName": _attr_value(e, "givenName"),
                "sn": _attr_value(e, "sn"),
                "gidNumber": gid,
                "primaryGroup": primary_group_cn,
                "primaryGroupStatus": primary_status,
                "secondaryGroups": ";".join(secondary_groups),
                "homeDirectory": _attr_value(e, "homeDirectory"),
                "loginShell": _attr_value(e, "loginShell"),
                "dn": e.entry_dn,
            }
            all_rows.append(row)

            if group_key not in grouped_rows:
                grouped_rows[group_key] = {
                    "gidNumber": gid,
                    "cn": primary_group_cn,
                    "status": primary_status,
                    "rows": [],
                }
            grouped_rows[group_key]["rows"].append(row)

        all_rows.sort(key=_row_sort_key)
        for group in grouped_rows.values():
            group["rows"].sort(key=_row_sort_key)

        used_sheet_names: set[str] = set()
        sheets: list[dict[str, Any]] = []

        def rows_to_sheet_values(rows: list[dict[str, Any]]) -> list[list[Any]]:
            return [HEADERS] + [[row.get(h, "") for h in HEADERS] for row in rows]

        sheets.append(
            {
                "name": _safe_sheet_name("All Users", used_sheet_names),
                "rows": rows_to_sheet_values(all_rows),
            }
        )

        for group in sorted(grouped_rows.values(), key=_group_sort_key):
            gid = group.get("gidNumber")
            cn = group.get("cn") or ""
            status = group.get("status") or ""
            if status == "OK" or status == "Duplicate gidNumber objects":
                label = f"{gid}_{cn}" if cn else f"gid_{gid}"
            elif str(status).startswith("Missing"):
                label = f"MISSING_gid_{gid}"
            else:
                label = "WEIRD_primary_gid"
            sheets.append(
                {
                    "name": _safe_sheet_name(label, used_sheet_names),
                    "rows": rows_to_sheet_values(group["rows"]),
                }
            )

        stats = {
            "users": len(all_rows),
            "sheets": len(sheets),
            "groups_with_users": len(grouped_rows),
            "missing_primary_groups": missing_primary_groups,
            "invalid_primary_gids": invalid_primary_gids,
            "duplicate_primary_group_gids": len(duplicate_gids),
            "bad_group_objects": bad_groups,
        }
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"ldap_users_by_primary_group_{stamp}.xlsx"
        return _make_xlsx(sheets), filename, stats

    except Exception as e:
        logger.error("Failed to build users-by-primary-group export: %s", e)
        raise
    finally:
        conn.unbind()
