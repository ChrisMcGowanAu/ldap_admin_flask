try:
    import config
except ModuleNotFoundError as e:
    if e.name != "config":
        raise

    raise RuntimeError(
        "\n\n"
        "Missing config.py\n"
        "=================\n"
        "This application needs a local config.py file.\n\n"
        "Create one with:\n\n"
        "    cp config_example.py config.py\n"
        "    nano config.py\n\n"
        "Then restart the service:\n\n"
        "    sudo systemctl restart ldap-admin.service\n\n"
        "config.py is intentionally not tracked by git because it contains\n"
        "site-specific LDAP settings and secrets.\n"
    ) from e

import csv
import io
import os
import secrets
from datetime import timedelta
from typing import Any
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


import config
from home_paths import compute_home_directory
from ldap_core import logger
from ldap_password import (
    ldap_change_password,
)
from ldap_reports import build_users_by_primary_group_export

from ldap_utils import (
    ldap_add_user_to_existing_group,
    ldap_add_user_to_group,
    ldap_audit_group_membership,
    ldap_check_user_group_membership,
    ldap_create_group,
    ldap_create_user,
    ldap_delete_group,
    ldap_delete_user,
    ldap_ensure_group_exists,
    ldap_get_group_by_gid,
    ldap_get_user,
    ldap_group_details,
    ldap_list_groups_for_uid,
    ldap_list_posix_groups_for_select,
    ldap_list_users_by_gid,
    ldap_remove_user_from_existing_group,
    ldap_search_groups,
    ldap_search_users,
    ldap_test_bind,
    ldap_update_user,
)
from password_utils import generate_password, generate_username
from version import get_app_version


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _get_field(row: dict, *names: str) -> str:
    """
    Return the first non-empty field from the given possible column names.

    - Case-insensitive
    - Ignores spaces and underscores in column names
      so 'Given Name', 'given_name', 'GivenName' all match 'given_name'.
    """

    def norm(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch not in (" ", "_"))

    # Build normalized map
    norm_map = {}
    for k, v in row.items():
        if k is None:
            continue
        norm_map[norm(str(k))] = v

    for n in names:
        key = norm(n)
        if key in norm_map:
            val = norm_map[key]
            if val is not None:
                val = str(val).strip()
                if val:
                    return val
    return ""


def _parse_username_password_csv(file_storage) -> list[dict[str, Any]]:
    """
    Reads a CSV and returns rows: [{"rownum": int, "username": str, "password": str}, ...]
    Only uses columns Username + Password (case-insensitive). Ignores the rest.
    """
    raw = file_storage.read()
    text = raw.decode("utf-8-sig", errors="replace")  # handles BOM
    f = io.StringIO(text)

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(f, dialect=dialect)
    if not reader.fieldnames:
        return []

    # Find "Username" and "Password" columns case-insensitively
    lower_map = {h: (h or "").strip().lower() for h in reader.fieldnames}
    user_col = next((h for h, hl in lower_map.items() if hl == "username"), None)
    pass_col = next((h for h, hl in lower_map.items() if hl == "password"), None)

    if not user_col or not pass_col:
        raise ValueError(
            f"CSV must contain 'Username' and 'Password' columns (found: {reader.fieldnames})"
        )

    rows: list[dict[str, Any]] = []
    for rownum, row in enumerate(reader, start=2):  # header is line 1
        username = (row.get(user_col) or "").strip()
        password = (row.get(pass_col) or "").strip()
        if not username and not password:
            continue
        rows.append({"rownum": rownum, "username": username, "password": password})
    return rows


def _parse_group_membership_csv(file_storage) -> list[dict[str, Any]]:
    """
    Reads a CSV for bulk supplementary group membership.

    Required logical fields, with flexible headers:
      username: username preferred; uid, user, login also accepted
      group: gid, gidNumber, group_gid, group, group_name, cn

    Extra columns are ignored. Empty rows are skipped.
    """
    raw = file_storage.read()
    text = raw.decode("utf-8-sig", errors="replace")
    f = io.StringIO(text)

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(f, dialect=dialect)
    if not reader.fieldnames:
        return []

    rows: list[dict[str, Any]] = []
    for rownum, row in enumerate(reader, start=2):
        username = _get_field(row, "username", "uid", "user", "login").lower()
        group_value = _get_field(
            row,
            "gid",
            "gidNumber",
            "group_gid",
            "group",
            "group_name",
            "cn",
            "group_cn",
        )

        if not username and not group_value:
            continue

        # Keep uid as an internal/backwards-compatible alias, but prefer
        # username in the UI and CSV template.
        rows.append(
            {
                "rownum": rownum,
                "username": username,
                "uid": username,
                "group": group_value,
            }
        )

    return rows


def _resolve_group_for_bulk_membership(group_value: str) -> tuple[dict[str, Any] | None, str]:
    """Resolve a CSV group field to an existing posixGroup.

    Accepts either numeric gidNumber or an exact group cn. For CSV bulk changes,
    do not silently accept fuzzy cn matches; that is too easy to misapply.
    """
    q = (group_value or "").strip()
    if not q:
        return None, "Missing group/gid value"

    if q.isdigit():
        return ldap_get_group_by_gid(int(q))

    groups, msg = ldap_search_groups(q, limit=250)
    if msg != "OK":
        return None, msg

    exact = [g for g in groups if (g.get("cn") or "").lower() == q.lower()]
    if len(exact) == 1:
        return exact[0], "OK"
    if len(exact) > 1:
        return None, f"Multiple exact groups named {q!r}; use gidNumber instead"

    if groups:
        suggestions = ", ".join(str(g.get("cn")) for g in groups[:8])
        return None, f"No exact group cn {q!r}; possible matches: {suggestions}"

    return None, f"No group found for {q!r}"


def _build_group_membership_preview(rows: list[dict[str, Any]]):
    """Validate bulk supplementary group rows and return (preview, stats)."""
    preview = []
    stats = {
        "total_rows": len(rows),
        "missing": 0,
        "not_found": 0,
        "group_errors": 0,
        "ready": 0,
        "mode": "TEST" if is_test_mode() else "LIVE",
    }

    for r in rows:
        username = (r.get("username") or r.get("uid") or "").strip().lower()
        group_value = (r.get("group") or "").strip()

        item = {
            "rownum": r.get("rownum"),
            "username": username,
            "uid": username,  # internal/backwards-compatible alias
            "group_input": group_value,
            "gidNumber": "",
            "group_cn": "",
            "status": "",
            "msg": "",
        }

        if not username or not group_value:
            stats["missing"] += 1
            item.update({"status": "skip", "msg": "Missing username or group/gid"})
            preview.append(item)
            continue

        user_obj, user_msg = ldap_get_user(username)
        if not user_obj:
            stats["not_found"] += 1
            item.update({"status": "warn", "msg": f"User not found ({user_msg})"})
            preview.append(item)
            continue

        group, group_msg = _resolve_group_for_bulk_membership(group_value)
        if not group:
            stats["group_errors"] += 1
            item.update({"status": "warn", "msg": group_msg})
            preview.append(item)
            continue

        normalised_username = user_obj.get("uid") or username
        item.update(
            {
                "username": normalised_username,
                "uid": normalised_username,
                "gidNumber": group.get("gidNumber"),
                "group_cn": group.get("cn"),
                "status": "ok",
                "msg": "Ready",
            }
        )
        stats["ready"] += 1
        preview.append(item)

    return preview, stats


app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.permanent_session_lifetime = timedelta(minutes=60)

# Rate limiter: protects the login endpoint against brute-force attacks.
# Default storage is in-process memory (suitable for single-process deployments
# behind gunicorn with --workers 1 or systemd).  For multi-worker deployments
# configure a Redis backend via RATELIMIT_STORAGE_URI in the environment.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],          # no global limit; only the login route is restricted
    storage_uri="memory://",
)

TEST_MODE = config.TEST_MODE


@app.before_request
def ensure_csrf_token():
    """Generate a per-session CSRF token on first request."""
    session.setdefault("_csrf_token", secrets.token_urlsafe(32))


@app.before_request
def validate_csrf_token():
    """Reject state-changing POST requests that lack a valid CSRF token.

    The token is embedded in every HTML form via the ``{{ csrf_token() }}``
    Jinja2 helper (injected by ``inject_globals``).  JSON API endpoints
    (``/api/*``) are exempt because they use ``Content-Type: application/json``
    rather than form submissions.
    """
    if request.method != "POST":
        return
    # Exempt JSON API routes — callers use Authorization headers, not cookies.
    if request.path.startswith("/api/"):
        return
    token_in_session = session.get("_csrf_token")
    token_in_form = request.form.get("_csrf_token")
    if not token_in_session or not token_in_form:
        logger.warning(
            "CSRF token missing: path=%s remote=%s",
            request.path,
            request.remote_addr,
        )
        flash("Invalid or missing security token. Please try again.", "danger")
        return redirect(request.referrer or url_for("login"))
    if not secrets.compare_digest(token_in_session, token_in_form):
        logger.warning(
            "CSRF token mismatch: path=%s remote=%s",
            request.path,
            request.remote_addr,
        )
        flash("Security token mismatch. Please try again.", "danger")
        return redirect(request.referrer or url_for("login"))


@app.context_processor
def inject_version():
    return {"app_version": get_app_version()}


def is_test_mode() -> bool:
    """Return effective test mode for the current session (falls back to config default)."""
    return session.get("test_mode", config.TEST_MODE)


def _normalise_class_for_import(raw: str) -> str | None:
    """
    Map the CSV 'class' value (e.g. '7','8','12','staff') to the internal
    class_key used by ldap_create_user / CLASS_OPTIONS.

    Your CLASS_OPTIONS keys look like:
      'Class 12', 'Class 11', ... 'Class 7'

    So we:
      - map 'staff' -> 'Staff' (if present)
      - for digits '7'..'12', match against the numeric part of the key
        e.g. '7' -> 'Class 7', '10' -> 'Class 10'
    """

    raw = (raw or "").strip()
    if not raw:
        return None

    # Staff
    if raw.lower() == "staff":
        # if no staff key configured, treat as unknown
        return "Staff"

    # If the CSV value already matches a key exactly, use it
    if raw in config.CLASS_OPTIONS:
        return raw

    # If it's a digit (7..12), try to match against the numeric part of keys
    if raw.isdigit():
        for key in config.CLASS_OPTIONS.keys():
            # Extract digits from key, e.g. "Class 12" -> "12"
            digits = "".join(ch for ch in str(key) if ch.isdigit())
            if digits == raw:
                return key

    # As a very last resort, try matching substring in the key itself
    for key in config.CLASS_OPTIONS.keys():
        if raw in str(key):
            return key

    return None


def login_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "admin_user" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapper


def _gid_from_dual_input(
    manual_field: str = "group_gid_manual",
    select_field: str = "group_gid",
    source_field: str = "group_gid_source",
    previous_field: str = "previous_gid",
) -> str:
    """
    Resolve the gidNumber from pages that have both:
      - a manual gidNumber text input, and
      - a posixGroup dropdown.

    The dropdown should win when it appears to have been explicitly changed.
    This prevents a stale manual gidNumber from overriding the combo box.
    """
    manual_gid = (request.form.get(manual_field) or "").strip()
    select_gid = (request.form.get(select_field) or "").strip()
    gid_source = (request.form.get(source_field) or "").strip()
    previous_gid = (request.form.get(previous_field) or "").strip()

    if gid_source == "select" and select_gid:
        return select_gid

    if gid_source == "manual" and manual_gid:
        return manual_gid

    if (
        select_gid
        and manual_gid
        and previous_gid
        and manual_gid == previous_gid
        and select_gid != previous_gid
    ):
        # JavaScript normally clears the manual field when the dropdown
        # changes. This fallback handles cached/stale forms or browsers
        # where the manual field still contains the previous search gid.
        return select_gid

    if select_gid and manual_gid and select_gid != manual_gid:
        # No hidden source field is available. Prefer the dropdown because the
        # most common failure mode is a stale manual gidNumber left over from
        # the previous search.
        return select_gid

    return manual_gid or select_gid


@app.context_processor
def inject_globals():
    """Expose test-mode flag and CSRF token helper to all templates."""
    return {
        "effective_test_mode": is_test_mode(),
        "csrf_token": lambda: session.get("_csrf_token", ""),
    }


@app.route("/api/compute_home_directory", methods=["POST"])
@login_required
def api_compute_home_directory():
    data = request.get_json(silent=True) or {}

    username = (data.get("username") or "").strip().lower()
    class_key = (data.get("class_key") or "").strip()

    try:
        gid_number, home_directory = compute_home_directory(username, class_key)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(
        {
            "gidNumber": gid_number,
            "homeDirectory": home_directory,
        }
    )


@app.route("/create_group", methods=["GET", "POST"])
@login_required
def create_group():
    cn = ""
    gid = ""

    if request.method == "POST":
        action = request.form.get("action", "")

        # (Optional) if you still support toggle_mode via main-form on some pages
        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")

            cn = (request.form.get("cn") or "").strip()
            gid = (request.form.get("gid") or "").strip()

        elif action == "create":
            cn = (request.form.get("cn") or "").strip()
            gid = (request.form.get("gid") or "").strip()

            if not cn or not gid:
                flash("Please enter both a group name (cn) and gidNumber.", "warning")
            else:
                try:
                    ok, msg = ldap_create_group(cn, int(gid), test_mode=is_test_mode())
                    flash(msg, "success" if ok else "danger")
                except Exception as e:
                    flash(f"Invalid gidNumber: {gid!r} ({e})", "danger")

    return render_template(
        "create_group.html",
        cn=cn,
        gid=gid,
        test_mode=is_test_mode(),
    )


@app.route("/delete_group", methods=["GET", "POST"])
@login_required
def delete_group():
    """
    Delete groups, with:
      - search by cn fragment OR gidNumber (digits-only)
      - multi-select delete
      - warning preview (memberUid + primary gid users) + confirm
      - TEST_MODE preview
    """
    matches = []
    message = None
    group_query = ""
    delete_preview = []

    if request.method == "POST":
        action = request.form.get("action", "")

        # 1) Banner toggle: flip TEST_MODE, keep on this page
        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")

            group_query = (request.form.get("group_query") or "").strip()

        # 2) Search groups
        elif action == "search":
            group_query = (request.form.get("group_query") or "").strip()

            if not group_query:
                flash("Please enter a group name fragment or a gidNumber.", "warning")
            else:
                raw_groups, msg = ldap_search_groups(group_query, limit=500)
                message = msg
                if not raw_groups:
                    flash("No matching groups found.", "info")
                else:
                    # Add primary gid user counts for highlighting
                    for g in raw_groups:
                        gid = g.get("gidNumber")
                        primary_count = 0
                        if gid is not None:
                            users, _ = ldap_list_users_by_gid(int(gid))
                            primary_count = len(users or [])

                        matches.append(
                            {
                                "cn": g.get("cn"),
                                "gidNumber": g.get("gidNumber"),
                                "member_count": g.get("member_count", 0),
                                "primary_gid_user_count": primary_count,
                                "dn": g.get("dn"),
                            }
                        )

        # 3) Build delete preview (warnings) but do not delete yet
        elif action == "delete_selected":
            group_query = (request.form.get("group_query") or "").strip()

            selected_cns = request.form.getlist("selected_cn")
            if not selected_cns:
                flash("No groups selected for deletion.", "warning")
            else:
                for cn in selected_cns:
                    details, msg = ldap_group_details(cn)
                    if not details:
                        flash(f"{cn}: {msg}", "danger")
                        continue

                    member_count = len(details.get("members") or [])
                    primary_count = len(details.get("primary_gid_users") or [])

                    delete_preview.append(
                        {
                            "cn": details.get("cn"),
                            "dn": details.get("dn"),
                            "gidNumber": details.get("gidNumber"),
                            "member_count": member_count,
                            "primary_gid_user_count": primary_count,
                        }
                    )

                if delete_preview:
                    flash(
                        "Review warnings below. Tick the confirmation box to proceed.",
                        "warning",
                    )

        # 4) Confirm delete (honour TEST_MODE)
        elif action == "confirm_delete":
            group_query = (request.form.get("group_query") or "").strip()

            if request.form.get("confirm") != "yes":
                flash("Please tick the confirmation box to proceed.", "warning")
            else:
                selected_cns = request.form.getlist("selected_cn")
                if not selected_cns:
                    flash("No groups selected for deletion.", "warning")
                else:
                    any_fail = False
                    for cn in selected_cns:
                        ok, msg = ldap_delete_group(cn, test_mode=is_test_mode())
                        flash(
                            f"{cn}: {msg}",
                            "success" if ok else "danger",
                        )
                        if not ok:
                            any_fail = True

                    if not any_fail:
                        mode_label = "TEST" if is_test_mode() else "LIVE"
                        flash(
                            f"{len(selected_cns)} group(s) processed in {mode_label} mode.",
                            "info",
                        )

            # After confirm, clear preview + matches
            matches = []
            delete_preview = []

    return render_template(
        "delete_group.html",
        matches=matches,
        delete_preview=delete_preview,
        message=message,
        group_query=group_query,
        test_mode=is_test_mode(),
    )


@app.route("/toggle_test_mode", methods=["POST"])
@login_required
def toggle_test_mode():
    current = session.get("test_mode", is_test_mode())
    new_value = not current
    session["test_mode"] = new_value
    state = "ON" if new_value else "OFF"
    flash(f"Test mode is now {state} for this browser session.", "info")
    # return redirect(url_for("dashboard"))
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/test_password", methods=["GET", "POST"])
@login_required
def test_password():
    """
    Simple tool for IT staff to check a user's LDAP password.

    Supports the same partial username lookup pattern used by Check/Edit User
    and Change Password.  The actual password test should use an exact uid.
    """
    result = None
    matches = []
    username = (request.form.get("username") or request.args.get("username") or "").strip()
    current_test_mode = is_test_mode()  # just for banner / context

    def search_password_test_user(query: str):
        found, msg = ldap_search_users(query, limit=100)
        if msg != "OK":
            flash(msg, "warning")

        if not found:
            flash("No matching users found.", "info")
            return "", []

        if len(found) == 1:
            exact_uid = found[0].get("uid") or query
            return exact_uid, []

        flash(f"Multiple matches ({len(found)}). Please select one.", "info")
        return query, found

    if request.method == "POST":
        action = request.form.get("action", "test_password")

        if action == "lookup_user":
            if not username:
                flash("Please enter a username fragment.", "warning")
            else:
                username, matches = search_password_test_user(username)

        elif action == "choose_user":
            selected_uid = (request.form.get("selected_uid") or "").strip()
            if not selected_uid:
                flash("No user selected.", "warning")
            else:
                username = selected_uid

        elif action == "test_password":
            password = request.form.get("password", "")

            if not username or not password:
                flash("Username and password are required.", "danger")
            else:
                ok, msg = ldap_test_bind(username, password)
                result = {
                    "ok": ok,
                    "msg": msg,
                    "username": username,
                }

                if ok:
                    flash(f"Password OK for {username}.", "success")
                else:
                    flash(f"Password check failed for {username}: {msg}", "danger")

    return render_template(
        "test_password.html",
        result=result,
        matches=matches,
        username=username,
        test_mode=current_test_mode,
    )


@app.route("/user_groups/bulk_template")
@login_required
def bulk_group_membership_template():
    """Serve a sample CSV template for bulk supplementary group membership."""
    template_lines = [
        "username,gid,group,notes",
        "alice,601,,Add by numeric gidNumber",
        "bob,,science-tools,Add by exact group cn",
    ]
    csv_content = "\n".join(template_lines) + "\n"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="ldap_bulk_group_membership_template.csv"'
        },
    )


@app.route("/bulk_import", methods=["GET", "POST"])
@login_required
def bulk_import():
    """
    Bulk import users from a CSV file.

    Recommended CSV header for humans:
      class,given_name,family_name,username,password,full_name,home

    Accepted aliases (case-insensitive, spaces/underscores ignored):
      class:      group,class,year,class_key
      given_name: given_name,given,givenName,first_name,firstname,first
      family_name: family_name,family,surname,sn,last_name,lastname,last
      username:   username,uid,user,login
      password:   password,pass
      full_name:  full_name,cn,displayName,name
      home:       home,home_dir
    """
    results = []

    if request.method == "POST":
        action = request.form.get("action", "")

        # Toggle mode: do not run import; just flip session flag and re-render
        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")
            flash(
                "Note: browsers do not preserve selected files; please reselect the CSV.",
                "warning",
            )
            return render_template("bulk_import.html", results=None, test_mode=is_test_mode())

        file = request.files.get("csv_file") or request.files.get("csvfile")
        if not file or file.filename == "":
            flash("Please choose a CSV file to upload.", "danger")
            return render_template("bulk_import.html", results=None, test_mode=is_test_mode())

        try:
            data = file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(data))

            if not reader.fieldnames:
                flash("CSV file has no header row.", "danger")
                return render_template("bulk_import.html", results=None, test_mode=is_test_mode())

            for row in reader:
                # Flexible, case-insensitive, spreadsheet-friendly
                class_csv = _get_field(row, "group", "class", "year", "class_key")
                given = _get_field(
                    row,
                    "given_name",
                    "given",
                    "givenName",
                    "first_name",
                    "firstname",
                    "first",
                )
                famil = _get_field(
                    row,
                    "family_name",
                    "family",
                    "surname",
                    "sn",
                    "last_name",
                    "lastname",
                    "last",
                )
                username = _get_field(row, "username", "uid", "user", "login").lower()
                password = _get_field(row, "password", "pass")
                full_name = _get_field(row, "full_name", "cn", "displayName", "name")
                home_dir = _get_field(row, "home", "home_dir", "directory")
                # For the template display
                row["given_name"] = given
                row["family_name"] = famil
                row["class_key"] = class_csv

                # Required bits
                if not class_csv or not given or not famil:
                    results.append(
                        {
                            "row": row,
                            "status": "Skipped",
                            "message": "Missing class/given_name/family_name",
                            "uid": "",
                            "password": "",
                        }
                    )
                    continue

                # Map CSV class to internal key
                class_key = _normalise_class_for_import(class_csv)
                if class_key is None:
                    results.append(
                        {
                            "row": row,
                            "status": "FAIL",
                            "message": f"Class mapping failed for '{class_csv}'",
                            "uid": "",
                            "password": "",
                        }
                    )
                    continue

                # Auto-username if missing
                if not username:
                    username = generate_username(given, famil)

                # Auto-password if missing
                if not password:
                    password = generate_password()

                # Effective display name
                effective_cn = full_name or f"{given} {famil}"

                ok, msg = ldap_create_user(
                    given_name=given,
                    family_name=famil,
                    username=username,
                    password=password,
                    class_key=class_key,
                    home=home_dir,
                    test_mode=is_test_mode(),
                    display_name=effective_cn,
                    admin_user=session.get("admin_user", ""),
                )

                results.append(
                    {
                        "row": row,
                        "status": "OK" if ok else "FAIL",
                        "message": msg,
                        "uid": username,
                        "password": password,
                    }
                )

        except Exception as e:
            flash(f"CSV parse error: {e}", "danger")
            return render_template("bulk_import.html", results=None, test_mode=is_test_mode())

        return render_template("bulk_import.html", results=results, test_mode=is_test_mode())

    # GET
    return render_template("bulk_import.html", results=None, test_mode=is_test_mode())


@app.route("/bulk_import/template")
@login_required
def bulk_import_template():
    """
    Serve a sample CSV template for bulk import.
    Columns are the human-friendly ones your importer expects.
    """
    template_lines = [
        "class,given_name,family_name,username,password,full_name,home",
        "7,First,Student,firststudent,,First Student,/home/first",
        "8,Second,Student,secondstudent,,Second Student,",
        "12,Staffmember,Teacher,staffmember,,Staffmember Teacher,",
        "staff,Admin,Staff,,,",
    ]
    csv_content = "\n".join(template_lines) + "\n"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="ldap_bulk_import_template.csv"'},
    )


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("login.html")

        ok, message = ldap_test_bind(username, password)
        if ok:
            # Simple admin allowlist gate (configurable in config.py)
            allowlist = getattr(config, "ADMIN_UID_ALLOWLIST", [])
            if allowlist and username not in allowlist:
                flash("Login OK -- but this User is not an Admin.", "danger")
                return render_template("login.html")

            session["admin_user"] = username
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash(f"Login failed: {message}", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", test_mode=is_test_mode())


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    bulk_preview = None
    bulk_stats = None
    matches = []
    username = (request.form.get("username") or request.args.get("username") or "").strip()

    def search_password_user(query: str):
        found, msg = ldap_search_users(query, limit=100)
        if msg != "OK":
            flash(msg, "warning")

        if not found:
            flash("No matching users found.", "info")
            return "", []

        if len(found) == 1:
            exact_uid = found[0].get("uid") or query
            return exact_uid, []

        flash(f"Multiple matches ({len(found)}). Please select one.", "info")
        return query, found

    if request.method == "POST":
        action = request.form.get("action", "")

        # ----- Single user lookup / password change -----
        if action == "lookup_user":
            if not username:
                flash("Please enter a username fragment.", "warning")
            else:
                username, matches = search_password_user(username)

            return render_template(
                "change_password.html",
                test_mode=is_test_mode(),
                username=username,
                matches=matches,
                bulk_preview=None,
                bulk_stats=None,
            )

        if action == "choose_user":
            selected_uid = (request.form.get("selected_uid") or "").strip()
            if not selected_uid:
                flash("No user selected.", "warning")
            else:
                username = selected_uid

            return render_template(
                "change_password.html",
                test_mode=is_test_mode(),
                username=username,
                matches=[],
                bulk_preview=None,
                bulk_stats=None,
            )

        if action == "single_change":
            username = (request.form.get("username") or "").strip()
            new_password = (request.form.get("new_password") or "").strip()

            if not username or not new_password:
                flash("Please enter both Username and New Password.", "warning")
            else:
                # This uses exact uid lookup, so the Lookup button should be used
                # when the admin only knows a partial uid.
                ok, msg = ldap_change_password(username, new_password, test_mode=is_test_mode())
                flash(f"{username}: {msg}", "success" if ok else "danger")

            return render_template(
                "change_password.html",
                test_mode=is_test_mode(),
                username=username,
                matches=[],
                bulk_preview=None,
                bulk_stats=None,
            )

        # ----- Bulk CSV preview / apply -----
        if action in ("bulk_preview", "bulk_apply"):
            upload = request.files.get("password_csv")
            if not upload or not upload.filename:
                flash("Please choose the CSV file (with Username + Password columns).", "warning")
                return render_template(
                    "change_password.html",
                    test_mode=is_test_mode(),
                    username=username,
                    matches=matches,
                )

            try:
                rows = _parse_username_password_csv(upload)
            except Exception as e:
                flash(f"CSV parse failed: {e}", "danger")
                return render_template(
                    "change_password.html",
                    test_mode=is_test_mode(),
                    username=username,
                    matches=matches,
                )

            if not rows:
                flash("CSV contained no usable rows.", "warning")
                return render_template(
                    "change_password.html",
                    test_mode=is_test_mode(),
                    username=username,
                    matches=matches,
                )

            preview = []
            missing = 0
            not_found = 0

            for r in rows:
                u = (r["username"] or "").strip()
                p = (r["password"] or "").strip()

                if not u or not p:
                    missing += 1
                    preview.append({**r, "status": "skip", "msg": "Missing Username or Password"})
                    continue

                # Optional existence check
                user_obj, msg = ldap_get_user(u)
                if not user_obj:
                    not_found += 1
                    preview.append({**r, "status": "warn", "msg": f"User not found ({msg})"})
                else:
                    preview.append({**r, "status": "ok", "msg": "Ready"})

            bulk_preview = preview
            bulk_stats = {
                "total_rows": len(rows),
                "missing": missing,
                "duplicates": 0,  # you can add dedupe later if you want
                "not_found": not_found,
                "mode": "TEST" if is_test_mode() else "LIVE",
            }

            if action == "bulk_apply":
                if not is_test_mode() and request.form.get("confirm_live") != "yes":
                    flash("LIVE mode: tick the confirmation box before applying.", "danger")
                    return render_template(
                        "change_password.html",
                        test_mode=is_test_mode(),
                        username=username,
                        matches=matches,
                        bulk_preview=bulk_preview,
                        bulk_stats=bulk_stats,
                    )

                ok_count = 0
                fail_count = 0

                for r in rows:
                    u = (r["username"] or "").strip()
                    p = (r["password"] or "").strip()
                    if not u or not p:
                        continue

                    ok, msg = ldap_change_password(u, p, test_mode=is_test_mode())
                    if ok:
                        ok_count += 1
                        flash(f"Row {r['rownum']} {u}: {msg}", "success")
                    else:
                        fail_count += 1
                        flash(f"Row {r['rownum']} {u}: {msg}", "danger")

                flash(
                    f"Bulk password run complete: {ok_count} ok, {fail_count} failed "
                    f"({ 'TEST' if is_test_mode() else 'LIVE' } mode).",
                    "info",
                )

            return render_template(
                "change_password.html",
                test_mode=is_test_mode(),
                username=username,
                matches=matches,
                bulk_preview=bulk_preview,
                bulk_stats=bulk_stats,
            )

        # ----- Unknown action fallback -----
        flash("Unknown action.", "warning")

    # GET (or POST fallback)
    return render_template(
        "change_password.html",
        test_mode=is_test_mode(),
        username=username,
        matches=matches,
        bulk_preview=bulk_preview,
        bulk_stats=bulk_stats,
    )


@app.route("/new_user", methods=["GET", "POST"])
@login_required
def new_user():
    if request.method == "POST":
        action = request.form.get("action", "")

        # Toggle mode but DO NOT lose typed fields
        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")

            # Re-render the page with the values the user already typed.
            return render_template(
                "new_user.html",
                classes=config.CLASS_OPTIONS,
                default_class=request.form.get("class_key", "") or config.DEFAULT_CLASS_OPTION,
            )

        # Normal submit: create user
        given_name = request.form.get("given_name", "").strip()
        family_name = request.form.get("family_name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        class_key = request.form.get("class_key", "").strip()
        full_name = request.form.get("fullName", "").strip()

        if not (given_name and family_name and username and password and class_key):
            flash("All fields are required.", "danger")
            # IMPORTANT: re-render, don't redirect, so typed values stay visible
            return render_template(
                "new_user.html",
                classes=config.CLASS_OPTIONS,
                default_class=class_key or config.DEFAULT_CLASS_OPTION,
            )

        if full_name is None or full_name == "":
            full_name = f"{given_name} {family_name}"

        success, message = ldap_create_user(
            given_name=given_name,
            family_name=family_name,
            username=username,
            password=password,
            class_key=class_key,
            display_name=full_name,
            home="",
            test_mode=is_test_mode(),
            admin_user=session.get("admin_user", ""),
        )

        if success:
            flash(message, "success")
            return redirect(url_for("dashboard"))

        flash(f"Failed to create user: {message}", "danger")
        return render_template(
            "new_user.html",
            classes=config.CLASS_OPTIONS,
            default_class=class_key or config.DEFAULT_CLASS_OPTION,
        )

    # GET
    return render_template(
        "new_user.html",
        classes=config.CLASS_OPTIONS,
        default_class=config.DEFAULT_CLASS_OPTION,
    )


@app.route("/group_audit", methods=["GET", "POST"])
@login_required
def group_audit():
    mode = None
    audit = {}
    summary = None
    selected_group_gid = None

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")

        elif action == "audit_current":
            mode = "current"

        elif action == "audit_all":
            mode = "all"

        elif action == "fix_missing_groups":
            raw_gids = request.form.getlist("missing_gid")
            if not raw_gids:
                flash("No missing groups selected for creation.", "warning")
            else:
                for raw_gid in raw_gids:
                    try:
                        gid = int(raw_gid)
                    except Exception:
                        flash(f"Invalid gidNumber skipped: {raw_gid!r}", "warning")
                        continue
                    ok, msg, _group_dn = ldap_ensure_group_exists(gid, test_mode=is_test_mode())
                    flash(msg, "success" if ok else "danger")

            # Re-run the last audit mode so the page updates after fixing.
            last_mode = (request.form.get("last_mode") or "all").strip()
            mode = last_mode if last_mode in {"current", "all", "group"} else "all"
            raw_gid = (request.form.get("selected_group_gid") or "").strip()
            if mode == "group" and raw_gid:
                try:
                    selected_group_gid = int(raw_gid)
                except Exception:
                    selected_group_gid = None

        elif action == "audit_group":
            mode = "group"

            raw_gid = _gid_from_dual_input()

            if not raw_gid:
                mode = None
                flash(
                    "Please enter a gidNumber or choose a group before auditing.",
                    "warning",
                )
            else:
                try:
                    selected_group_gid = int(raw_gid)
                    if selected_group_gid <= 0:
                        raise ValueError("gid must be > 0")
                except Exception:
                    mode = None
                    selected_group_gid = None
                    flash(f"Invalid gidNumber: {raw_gid!r}", "danger")

        if mode:
            try:
                audit, summary = ldap_audit_group_membership(
                    include_staff=True,
                    mode=mode,
                    group_gid=selected_group_gid,
                )
            except Exception as e:
                flash(f"Group audit failed: {e}", "danger")
                audit, summary = {}, None

    groups_for_select = ldap_list_posix_groups_for_select()

    return render_template(
        "group_audit.html",
        audit=audit,
        summary=summary,
        mode=mode or "",
        groups_for_select=groups_for_select,
        selected_group_gid=selected_group_gid,
        test_mode=is_test_mode(),
    )


@app.route("/group_users", methods=["GET", "POST"])
@login_required
def group_users():
    users = []
    selected_gid = None
    message = None
    groups_for_select = ldap_list_posix_groups_for_select()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")
        else:
            raw_gid = _gid_from_dual_input()
            if not raw_gid:
                flash("Please enter a gidNumber or choose a group.", "warning")
            else:
                try:
                    selected_gid = int(raw_gid)
                    if selected_gid <= 0:
                        raise ValueError("gid must be > 0")
                    users, msg = ldap_list_users_by_gid(selected_gid)
                    message = msg
                    if not users:
                        flash(f"No users found with gidNumber={selected_gid}.", "info")
                except Exception as e:
                    selected_gid = None
                    flash(f"Invalid gidNumber: {raw_gid!r} ({e})", "danger")

    return render_template(
        "group_users.html",
        users=users,
        groups_for_select=groups_for_select,
        selected_gid=selected_gid,
        message=message,
        test_mode=is_test_mode(),
    )


@app.route("/user_groups", methods=["GET", "POST"])
@login_required
def user_groups():
    user = None
    member_groups = []
    matches = []
    bulk_group_preview = None
    bulk_group_stats = None
    bulk_group_result_message = None
    bulk_group_result_category = "info"
    username = (request.form.get("username") or request.args.get("username") or "").strip()
    groups_for_select = ldap_list_posix_groups_for_select()

    def load_user_by_uid(uid: str):
        """Load an exact user by uid and normalise the username field."""
        loaded_user, msg = ldap_get_user(uid)
        if not loaded_user:
            flash(msg or f"User {uid!r} not found.", "danger")
            return None, uid
        return loaded_user, loaded_user.get("uid") or uid

    def search_or_load_user(query: str):
        """Search by partial uid. Auto-open only when exactly one user matches."""
        found, msg = ldap_search_users(query, limit=100)
        if msg != "OK":
            flash(msg, "warning")

        if not found:
            flash("No matching users found.", "info")
            return None, [], query

        if len(found) == 1:
            exact_uid = found[0].get("uid") or query
            loaded_user, exact_uid = load_user_by_uid(exact_uid)
            return loaded_user, [], exact_uid

        flash(f"Multiple matches ({len(found)}). Please select one.", "info")
        return None, found, query

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")

        elif action == "lookup":
            if not username:
                flash("Please enter a username fragment.", "warning")
            else:
                user, matches, username = search_or_load_user(username)

        elif action == "choose_user":
            selected_uid = (request.form.get("selected_uid") or "").strip()
            if not selected_uid:
                flash("No user selected.", "warning")
            else:
                user, username = load_user_by_uid(selected_uid)

        elif action in ("bulk_group_preview", "bulk_group_apply"):
            upload = request.files.get("group_membership_csv")
            if not upload or not upload.filename:
                flash("Please choose a CSV file with username and gid/group columns.", "warning")
            else:
                try:
                    rows = _parse_group_membership_csv(upload)
                    if not rows:
                        flash("CSV contained no usable rows.", "warning")
                    else:
                        bulk_group_preview, bulk_group_stats = _build_group_membership_preview(rows)
                except Exception as e:
                    flash(f"CSV parse failed: {e}", "danger")

            if action == "bulk_group_apply" and bulk_group_preview:
                if not is_test_mode() and request.form.get("confirm_live") != "yes":
                    bulk_group_result_message = (
                        "LIVE mode: tick the confirmation box before applying."
                    )
                    bulk_group_result_category = "danger"
                    flash(bulk_group_result_message, bulk_group_result_category)
                    logger.warning(
                        "Bulk supplementary group apply blocked: LIVE mode without confirm checkbox"
                    )
                else:
                    ok_count = 0
                    fail_count = 0
                    skip_count = 0

                    for r in bulk_group_preview:
                        if r.get("status") != "ok":
                            skip_count += 1
                            logger.warning(
                                "Bulk supplementary group row skipped: row=%r status=%r msg=%r",
                                r.get("rownum"),
                                r.get("status"),
                                r.get("msg"),
                            )
                            continue

                        username_for_group = (
                            (r.get("username") or r.get("uid") or "").strip().lower()
                        )

                        try:
                            gid = int(r.get("gidNumber"))
                        except Exception:
                            fail_count += 1
                            flash(
                                f"Row {r.get('rownum')}: invalid gidNumber {r.get('gidNumber')!r}",
                                "danger",
                            )
                            logger.error(
                                "Bulk supplementary group invalid gidNumber row=%r username=%r gidNumber=%r",
                                r.get("rownum"),
                                username_for_group,
                                r.get("gidNumber"),
                            )
                            continue

                        logger.info(
                            "Bulk add supplementary group: username=%r gid=%r test_mode=%r",
                            username_for_group,
                            gid,
                            is_test_mode(),
                        )
                        ok, msg = ldap_add_user_to_existing_group(
                            username_for_group,
                            gid,
                            test_mode=is_test_mode(),
                        )
                        # flash(
                        #     f"Row {r.get('rownum')} {username_for_group}: {msg}",
                        #     "success" if ok else "danger",
                        # )
                        if ok:
                            ok_count += 1
                            r["apply_status"] = "ok"
                            r["apply_msg"] = msg
                        else:
                            fail_count += 1
                            r["apply_status"] = "fail"
                            r["apply_msg"] = msg

                    bulk_group_result_message = (
                        f"Bulk group membership run complete: {ok_count} ok, "
                        f"{fail_count} failed, {skip_count} skipped "
                        f"({ 'TEST' if is_test_mode() else 'LIVE' } mode)."
                    )
                    bulk_group_result_category = "info"
                    flash(bulk_group_result_message, bulk_group_result_category)

        elif not username:
            flash("Please enter a username.", "warning")

        else:
            # add/remove actions submit the exact uid in a hidden field.
            user, username = load_user_by_uid(username)
            if user:
                primary_gid = None
                try:
                    primary_gid = int(user.get("gidNumber"))
                except Exception:
                    primary_gid = None

                if action == "add_group":
                    raw_gid = (request.form.get("group_gid") or "").strip()
                    try:
                        gid = int(raw_gid)
                        ok, msg = ldap_add_user_to_existing_group(
                            username,
                            gid,
                            test_mode=is_test_mode(),
                        )
                        flash(msg, "success" if ok else "danger")
                    except Exception as e:
                        flash(f"Invalid group selection: {raw_gid!r} ({e})", "danger")

                elif action == "remove_group":
                    raw_gid = (request.form.get("remove_gid") or "").strip()
                    try:
                        gid = int(raw_gid)
                        if primary_gid is not None and gid == primary_gid:
                            flash(
                                "Not removing the user's primary group membership here. Change class/primary gidNumber or use Group Audit instead.",
                                "warning",
                            )
                        else:
                            ok, msg = ldap_remove_user_from_existing_group(
                                username,
                                gid,
                                test_mode=is_test_mode(),
                            )
                            flash(msg, "success" if ok else "danger")
                    except Exception as e:
                        flash(f"Invalid group selection: {raw_gid!r} ({e})", "danger")

    elif username:
        user, matches, username = search_or_load_user(username)

    if user:
        member_groups, msg = ldap_list_groups_for_uid(user.get("uid"))
        if msg != "OK":
            flash(msg, "warning")
        try:
            primary_gid = int(user.get("gidNumber"))
        except Exception:
            primary_gid = None
        for g in member_groups:
            try:
                g["is_primary"] = primary_gid is not None and int(g.get("gidNumber")) == primary_gid
            except Exception:
                g["is_primary"] = False

    return render_template(
        "user_groups.html",
        user=user,
        username=username,
        matches=matches,
        member_groups=member_groups,
        groups_for_select=groups_for_select,
        bulk_group_preview=bulk_group_preview,
        bulk_group_stats=bulk_group_stats,
        bulk_group_result_message=bulk_group_result_message,
        bulk_group_result_category=bulk_group_result_category,
        test_mode=is_test_mode(),
    )


@app.route("/delete_user", methods=["GET", "POST"])
@login_required
def delete_user():
    """
    Delete users, with:
      - search by uid fragment
      - list users by gidNumber (e.g. old cohorts 2022, 2023, ...)
      - multi-select delete with TEST_MODE preview
    """
    matches = []
    message = None
    username_fragment = ""
    group_gid_manual = ""

    if request.method == "POST":
        action = request.form.get("action", "")

        # 1) Banner toggle: flip TEST_MODE, keep on this page
        if action == "toggle_mode":
            session["test_mode"] = not is_test_mode()
            state = "ON" if is_test_mode() else "OFF"
            flash(f"Test mode is now {state} for this browser session.", "info")

            # Preserve the text fields so user sees what they typed
            username_fragment = (request.form.get("username_fragment") or "").strip()
            group_gid_manual = (request.form.get("group_gid_manual") or "").strip()

        # 2) Search by uid fragment
        elif action == "search":
            username_fragment = (request.form.get("username_fragment") or "").strip()
            group_gid_manual = (request.form.get("group_gid_manual") or "").strip()

            if not username_fragment:
                flash("Please enter a username fragment to search.", "warning")
            else:
                raw_matches, msg = ldap_search_users(username_fragment, limit=500)
                message = msg
                if not raw_matches:
                    flash("No matching users found.", "info")
                else:
                    # Normalise into a consistent shape for the template
                    for m in raw_matches:
                        matches.append(
                            {
                                "uid": m.get("uid"),
                                "cn": m.get("cn"),
                                "gidNumber": m.get("gidNumber"),
                                "homeDirectory": m.get("homeDirectory"),
                                "dn": m.get("dn"),
                            }
                        )

        # 3) List users by gidNumber (for cohorts)
        elif action == "from_group":
            username_fragment = (request.form.get("username_fragment") or "").strip()
            group_gid_manual = (request.form.get("group_gid_manual") or "").strip()

            if not group_gid_manual:
                flash("Please enter a gidNumber.", "warning")
            else:
                try:
                    gid = int(group_gid_manual)
                    raw_users, msg = ldap_list_users_by_gid(gid)
                    message = msg
                    if not raw_users:
                        flash(f"No users found with gidNumber={gid}.", "info")
                    else:
                        for u in raw_users:
                            matches.append(
                                {
                                    "uid": u.get("uid"),
                                    "cn": u.get("cn"),
                                    "gidNumber": u.get("gidNumber"),
                                    "homeDirectory": u.get("homeDirectory"),
                                    "dn": u.get("dn"),
                                }
                            )
                except Exception as e:
                    flash(f"Invalid gidNumber: {group_gid_manual!r} ({e})", "danger")

        # 4) Delete selected users
        elif action == "delete_selected":
            username_fragment = (request.form.get("username_fragment") or "").strip()
            group_gid_manual = (request.form.get("group_gid_manual") or "").strip()

            selected_uids = request.form.getlist("selected_uid")
            if not selected_uids:
                flash("No users selected for deletion.", "warning")
            else:
                any_fail = False
                for uid in selected_uids:
                    ok, msg = ldap_delete_user(uid, test_mode=is_test_mode())
                    flash(
                        f"{uid}: {msg}",
                        "success" if ok else "danger",
                    )
                    if not ok:
                        any_fail = True

                if not any_fail:
                    # Nice little summary
                    mode_label = "TEST" if is_test_mode() else "LIVE"
                    flash(
                        f"{len(selected_uids)} user(s) processed in {mode_label} mode.",
                        "info",
                    )

            # After delete, we clear matches; the admin can re-run the search if needed
            matches = []

    return render_template(
        "delete_user.html",
        matches=matches,
        message=message,
        username_fragment=username_fragment,
        group_gid_manual=group_gid_manual,
        test_mode=is_test_mode(),
    )


@app.route("/check_user", methods=["GET", "POST"])
@login_required
def check_user():
    """
    Check / edit a user:
      - search by uid fragment
      - choose from multiple matches
      - edit key attributes
      - fix group membership
      - test the user's password (bind test)
    """
    user_data = None
    matches = []
    membership = None
    password_result = None
    current_test_mode = is_test_mode()

    if request.method == "POST":
        action = request.form.get("action", "lookup")
        username = request.form.get("username", "").strip()
        effective_uid = request.form.get("effective_uid", "").strip()

        # Choose which uid we operate on depending on action
        if action == "choose":
            username = request.form.get("selected_uid", "").strip()
        elif action in ("save", "fix_membership", "test_password") and effective_uid:
            username = effective_uid

        if action == "lookup":
            if not username:
                flash("Username is required.", "danger")
            else:
                matches, _ = ldap_search_users(username)
                if not matches:
                    flash("User not found.", "warning")
                elif len(matches) == 1:
                    user_data, msg = ldap_get_user(matches[0]["uid"])
                    if not user_data:
                        flash(msg or "User not found.", "warning")
                else:
                    flash(
                        f"Multiple matches ({len(matches)}). Please select one.",
                        "info",
                    )

        elif action == "choose":
            if not username:
                flash("No user selected.", "warning")
            else:
                user_data, msg = ldap_get_user(username)
                if not user_data:
                    flash(msg or "User not found.", "warning")

        elif action == "save":
            if not username:
                flash("No user selected to save.", "warning")
            else:
                attrs = {
                    "givenName": request.form.get("givenName", "").strip(),
                    "cn": request.form.get("cn", "").strip(),
                    "homeDirectory": request.form.get("homeDirectory", "").strip(),
                    "loginShell": request.form.get("loginShell", "").strip(),
                    "class_key": request.form.get("class_key", "").strip(),
                }
                ok, msg = ldap_update_user(
                    username,
                    attrs,
                    test_mode=current_test_mode,
                )
                flash(msg, "success" if ok else "danger")
                user_data, _ = ldap_get_user(username)

        elif action == "fix_membership":
            if not username:
                flash("No user selected to fix membership.", "warning")
            else:
                gid = int(request.form.get("gidNumber", "0") or 0)
                ok, msg = ldap_add_user_to_group(
                    username,
                    gid,
                    test_mode=current_test_mode,
                )
                flash(msg, "success" if ok else "danger")
                user_data, _ = ldap_get_user(username)

        elif action == "test_password":
            if not username:
                flash("No user selected for password check.", "warning")
            else:
                pwd = request.form.get("test_password", "")
                if not pwd:
                    flash("Password is required for the test.", "danger")
                else:
                    ok, msg = ldap_test_bind(username, pwd)
                    password_result = {
                        "ok": ok,
                        "msg": msg,
                        "username": username,
                    }
                    if ok:
                        flash(f"Password OK for {username}.", "success")
                    else:
                        flash(f"Password check failed for {username}: {msg}", "danger")
                    user_data, _ = ldap_get_user(username)

        # If some action happened but we still don't have user_data, try to fetch it
        if not user_data and username and action != "lookup":
            user_data, _ = ldap_get_user(username)

    # Group membership status
    if user_data:
        try:
            gid = int(user_data.get("gidNumber") or 0)
            ok, msg, group_dn = ldap_check_user_group_membership(
                user_data.get("uid", ""),
                gid,
            )
            membership = {"ok": ok, "msg": msg, "group_dn": group_dn}
        except Exception as e:
            membership = {
                "ok": False,
                "msg": f"Membership check failed: {e}",
                "group_dn": "",
            }

    return render_template(
        "check_user.html",
        user_data=user_data,
        matches=matches,
        membership=membership,
        password_result=password_result,
        classes=config.CLASS_OPTIONS,
        staff_gid=config.STAFF_GID_NUMBER,
        test_mode=current_test_mode,
    )


@app.route("/api/generate_username", methods=["POST"])
@login_required
def api_generate_username():
    data = request.get_json() or {}
    given_name = data.get("given_name", "")
    family_name = data.get("family_name", "")
    if not given_name or not family_name:
        return jsonify({"error": "Missing given_name or family_name"}), 400

    username = generate_username(given_name, family_name)
    return jsonify({"username": username})


@app.route("/api/generate_password", methods=["POST"])
@login_required
def api_generate_password():
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or data.get("type") or "kid").strip().lower()

    try:
        pwd = generate_password(kind=kind)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"password": pwd, "kind": kind})


@app.route("/export/users_by_primary_group.xlsx")
@login_required
def export_users_by_primary_group_xlsx():
    """Download an XLSX audit report of all LDAP users by primary gidNumber."""
    try:
        data, filename, stats = build_users_by_primary_group_export()
    except Exception as e:
        flash(f"User export failed: {e}", "danger")
        return redirect(url_for("dashboard"))

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-LDAP-Export-Users": str(stats.get("users", 0)),
        "X-LDAP-Export-Sheets": str(stats.get("sheets", 0)),
    }
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


if __name__ == "__main__":
    host = os.environ.get("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_RUN_PORT", "5000"))
    debug = bool(int(os.environ.get("FLASK_DEBUG", "1")))
    app.run(host=host, port=port, debug=debug)
