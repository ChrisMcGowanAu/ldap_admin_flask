from typing import Any, Dict, List, Optional, Tuple

from ldap_core import (
    MODIFY_ADD,
    MODIFY_DELETE,
    SUBTREE,
    config,
    escape_filter_chars,
    get_service_connection,
    logger,
)

_get_service_connection = get_service_connection


def _group_base() -> str:
    """Return LDAP_GROUP_BASE_DN from config; raise clearly if not set."""
    base = getattr(config, "LDAP_GROUP_BASE_DN", None)
    if not base:
        raise RuntimeError(
            "LDAP_GROUP_BASE_DN is not set in config.py. "
            "Please add it, e.g.: LDAP_GROUP_BASE_DN = 'ou=groups,dc=example,dc=org'"
        )
    return base


def _user_base() -> str:
    """Return LDAP_USER_BASE_DN from config; raise clearly if not set."""
    base = getattr(config, "LDAP_USER_BASE_DN", None)
    if not base:
        raise RuntimeError(
            "LDAP_USER_BASE_DN is not set in config.py. "
            "Please add it, e.g.: LDAP_USER_BASE_DN = 'ou=people,dc=example,dc=org'"
        )
    return base


def ldap_create_group(cn: str, gid_number: int, test_mode: bool = False):
    """
    Create a posixGroup with cn + gidNumber.
    Warn if cn exists or gidNumber already used.
    """
    name = (cn or "").strip()
    if not name:
        return False, "Empty cn"

    try:
        gid = int(gid_number)
    except Exception:
        return False, f"Invalid gidNumber: {gid_number!r}"

    # cn exists?
    existing, _ = ldap_group_details(name)
    if existing:
        return (
            False,
            f"Group {name} already exists (gidNumber={existing.get('gidNumber')}).",
        )

    # gid exists?
    gid_matches, _ = ldap_search_groups(str(gid), limit=5)
    if gid_matches:
        return (
            False,
            f"gidNumber {gid} already in use by group {gid_matches[0].get('cn')}.",
        )

    dn = f"cn={name},{config.LDAP_GROUP_BASE_DN}"
    attrs = {
        "objectClass": ["top", "posixGroup"],
        "cn": name,
        "gidNumber": str(gid),
    }

    conn = _get_service_connection()
    try:
        if test_mode:
            logger.info("TEST_MODE: would create group %s gid=%s DN=%s", name, gid, dn)
            return True, f"TEST_MODE: would create group {name} gid={gid} ({dn})"

        ok = conn.add(dn, attributes=attrs)
        if not ok or conn.result.get("description") != "success":
            return False, f"LDAP add failed: {conn.result}"

        return True, f"Group {name} created (gidNumber={gid})."
    finally:
        conn.unbind()


def ldap_group_details(cn: str):
    """
    Return group details for delete confirmation.

    Returns:
      details dict:
        {
          "cn", "gidNumber", "members", "primary_gid_users", "dn"
        }
      message: "OK" or error string
    """
    from ldap_queries import ldap_list_users_by_gid  # local import avoids circulars

    name = (cn or "").strip()
    if not name:
        return None, "Empty cn"

    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Service bind failed in ldap_group_details: %s", e)
        return None, f"Service bind failed: {e}"

    try:
        safe = escape_filter_chars(name)
        conn.search(
            search_base=config.LDAP_GROUP_BASE_DN,
            search_filter=f"(cn={safe})",
            search_scope=SUBTREE,
            attributes=["cn", "gidNumber", "memberUid"],
            size_limit=2,
        )

        if not conn.entries:
            return None, f"Group {name} not found"

        e = conn.entries[0]

        gid_val = getattr(e, "gidNumber", None).value if hasattr(e, "gidNumber") else None

        members = []
        if hasattr(e, "memberUid") and e.memberUid:
            try:
                members = list(e.memberUid.values)
            except Exception:
                members = []

        # Find users whose PRIMARY gidNumber == this group's gidNumber
        primary_gid_users = []
        if gid_val is not None and str(gid_val).isdigit():
            users, _msg = ldap_list_users_by_gid(int(gid_val))
            primary_gid_users = [u.get("uid") for u in (users or []) if u.get("uid")]

        details = {
            "cn": getattr(e, "cn", None).value if hasattr(e, "cn") else name,
            "gidNumber": gid_val,
            "members": members,
            "primary_gid_users": primary_gid_users,
            "dn": e.entry_dn,
        }
        return details, "OK"

    except Exception as e:
        logger.error("Error in ldap_group_details: %s", e)
        return None, f"Lookup failed: {e}"
    finally:
        conn.unbind()


def ldap_delete_group(cn: str, test_mode: bool = False):
    """
    Delete group by cn.
    In TEST_MODE: do not delete, just report.
    """
    details, msg = ldap_group_details(cn)
    if not details:
        return False, msg

    dn = details["dn"]

    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Service bind failed in ldap_delete_group: %s", e)
        return False, f"Service bind failed: {e}"

    try:
        if test_mode:
            logger.info("TEST_MODE: would delete group %s (%s)", cn, dn)
            return True, f"TEST_MODE: would delete group {cn} ({dn})"

        logger.info("Deleting group %s (%s)", cn, dn)
        conn.delete(dn)

        if conn.result.get("description") != "success":
            logger.error("LDAP delete failed in ldap_delete_group: %s", conn.result)
            return False, f"LDAP delete failed: {conn.result}"

        return True, f"Group {cn} deleted."

    except Exception as e:
        logger.error("Error in ldap_delete_group: %s", e)
        return False, f"LDAP delete exception: {e}"
    finally:
        conn.unbind()


def ldap_search_groups(group_query: str, limit: int = 50):
    """
    Search groups by cn fragment and/or gidNumber.

    If query is digits-only, we search BOTH:
      - gidNumber exact match
      - cn contains that number
    Otherwise:
      - cn contains fragment (supports '*' if user includes it)
    """
    q = (group_query or "").strip()
    if not q:
        return [], "Empty search"

    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Service bind failed in ldap_search_groups: %s", e)
        return [], f"Service bind failed: {e}"

    try:
        safe = escape_filter_chars(q)
        if q.isdigit():
            # Numeric searches should still find low-numbered Unix-style groups
            # such as gidNumber 6 (disks) or 46 (plugdev).  We also include a
            # cn fragment match so class2028 / 2028 style searches remain useful.
            n = int(q)
            search_filter = f"(|(gidNumber={n})(cn=*{safe}*))"

        else:
            cn_filter = safe if "*" in q else f"*{safe}*"
            search_filter = f"(cn={cn_filter})"

        conn.search(
            search_base=config.LDAP_GROUP_BASE_DN,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=["cn", "gidNumber", "memberUid"],
            size_limit=limit,
        )

        sorted_entries = sorted(
            conn.entries,
            key=lambda e: ((getattr(e, "cn", None).value or "").lower()),
            reverse=False,
        )

        out = []
        for e in sorted_entries:
            members = []
            if hasattr(e, "memberUid") and e.memberUid:
                try:
                    members = list(e.memberUid.values)
                except Exception:
                    members = []

            out.append(
                {
                    "cn": getattr(e, "cn", None).value if hasattr(e, "cn") else None,
                    "gidNumber": (
                        getattr(e, "gidNumber", None).value if hasattr(e, "gidNumber") else None
                    ),
                    "member_count": len(members),
                    "dn": e.entry_dn,
                }
            )

        return out, "OK"

    except Exception as e:
        logger.error("Error in ldap_search_groups: %s", e)
        return [], f"Lookup failed: {e}"
    finally:
        conn.unbind()


def ldap_list_posix_groups_for_select():
    """
    Return a list of dicts: [{"cn": str, "gidNumber": int, "dn": str}, ...]
    based on actual posixGroup entries under LDAP_GROUP_BASE_DN.
    """
    conn = _get_service_connection()
    try:
        conn.search(
            search_base=_group_base(),
            search_filter="(objectClass=posixGroup)",
            search_scope=SUBTREE,
            attributes=["cn", "gidNumber"],
        )
        groups = []
        for e in conn.entries:
            try:
                cn = getattr(e, "cn", None).value
                gid = int(getattr(e, "gidNumber", None).value)
            except Exception:
                continue
            groups.append(
                {
                    "cn": cn,
                    "gidNumber": gid,
                    "dn": e.entry_dn,
                }
            )
        groups.sort(key=lambda g: (g["gidNumber"], g["cn"]))
        return groups
    finally:
        conn.unbind()


def ldap_audit_group_membership(
    include_staff: bool = True,
    mode: str = "current",
    group_gid: int | None = None,
):
    """
    Audit primary gidNumber -> posixGroup/memberUid consistency.

    Modes:
      - "current": only staff + cohorts defined in CLASS_OPTIONS
      - "all":     all users
      - "group":   only users whose primary gidNumber == group_gid

    The audit deliberately separates:
      - missing group objects: unique missing gidNumbers
      - users affected by missing group objects
      - missing memberUid memberships
      - skipped users: invalid/incomplete LDAP entries
      - outside_scope users: valid users ignored by the chosen mode
    """
    mode = (mode or "current").lower()

    staff_gid = int(getattr(config, "STAFF_GID_NUMBER", 500))
    cohort_gids = set()
    for info in getattr(config, "CLASS_OPTIONS", {}).values():
        try:
            cohort_gids.add(int(info["gidNumber"]))
        except Exception:
            continue

    current_valid_gids = set()
    if include_staff:
        current_valid_gids.add(staff_gid)
    current_valid_gids.update(cohort_gids)

    def _is_fixable_missing_group(gid: int) -> tuple[bool, str]:
        if gid == staff_gid:
            return False, "Staff group must be created/repaired manually."
        if gid in cohort_gids or 1900 <= gid <= 2200:
            return True, "Can create as a class-style posixGroup."
        return False, "gidNumber is outside the normal staff/class range; create manually."

    conn = _get_service_connection()
    try:
        conn.search(
            search_base=_group_base(),
            search_filter="(objectClass=posixGroup)",
            search_scope=SUBTREE,
            attributes=["cn", "gidNumber", "memberUid"],
        )

        groups_by_gid: Dict[int, Dict[str, Any]] = {}
        for e in sorted(conn.entries, reverse=False):
            try:
                gid = int(getattr(e, "gidNumber", None).value)
            except Exception:
                continue

            member_uids = set()
            if "memberUid" in e:
                member_uids = set(e.memberUid.values)

            groups_by_gid[gid] = {
                "cn": getattr(e, "cn", None).value,
                "dn": e.entry_dn,
                "member_uids": member_uids,
            }

        conn.search(
            search_base=_user_base(),
            search_filter="(uid=*)",
            search_scope=SUBTREE,
            attributes=["uid", "cn", "gidNumber"],
        )

        missing_by_gid: Dict[int, Dict[str, Any]] = {}
        missing_memberships: List[Dict[str, Any]] = []
        skipped_users: List[Dict[str, Any]] = []
        outside_scope_users: List[Dict[str, Any]] = []

        for e in sorted(conn.entries, reverse=False):
            uid_attr = getattr(e, "uid", None)
            cn_attr = getattr(e, "cn", None)
            gid_attr = getattr(e, "gidNumber", None)
            dn = e.entry_dn
            cn = getattr(cn_attr, "value", None) if cn_attr else None

            if not uid_attr or not getattr(uid_attr, "value", None):
                skipped_users.append(
                    {"dn": dn, "cn": cn, "uid": "", "gidNumber": "", "reason": "Missing uid"}
                )
                continue
            uid = uid_attr.value

            if not gid_attr or getattr(gid_attr, "value", None) in (None, ""):
                skipped_users.append(
                    {"dn": dn, "cn": cn, "uid": uid, "gidNumber": "", "reason": "Missing gidNumber"}
                )
                continue

            try:
                gid = int(gid_attr.value)
            except Exception:
                skipped_users.append(
                    {
                        "dn": dn,
                        "cn": cn,
                        "uid": uid,
                        "gidNumber": getattr(gid_attr, "value", ""),
                        "reason": "Invalid gidNumber",
                    }
                )
                continue

            if mode == "group":
                if group_gid is None or gid != int(group_gid):
                    continue
            elif mode == "current":
                if gid not in current_valid_gids:
                    outside_scope_users.append(
                        {
                            "dn": dn,
                            "cn": cn,
                            "uid": uid,
                            "gidNumber": gid,
                            "reason": "Valid user outside current staff/cohort audit scope",
                        }
                    )
                    continue
            elif mode == "all":
                pass
            else:
                pass

            group_info = groups_by_gid.get(gid)
            if not group_info:
                row = missing_by_gid.get(gid)
                if not row:
                    fixable, fix_reason = _is_fixable_missing_group(gid)
                    group_dn = _group_dn_for_gid(gid)
                    expected_cn = group_dn.split(",", 1)[0].split("=", 1)[1]
                    row = {
                        "gidNumber": gid,
                        "expected_cn": expected_cn,
                        "group_dn": group_dn,
                        "reason": "No posixGroup object for this gidNumber",
                        "fixable": fixable,
                        "fix_reason": fix_reason,
                        "affected_users": [],
                        "affected_count": 0,
                    }
                    missing_by_gid[gid] = row
                row["affected_users"].append({"uid": uid, "cn": cn, "dn": dn})
                row["affected_count"] += 1
                continue

            if uid not in group_info["member_uids"]:
                missing_memberships.append(
                    {
                        "uid": uid,
                        "cn": cn,
                        "gidNumber": gid,
                        "group_cn": group_info.get("cn"),
                        "group_dn": group_info["dn"],
                        "reason": "User missing from group.memberUid",
                    }
                )

        missing_groups = sorted(missing_by_gid.values(), key=lambda r: int(r["gidNumber"]))
        for row in missing_groups:
            row["affected_users"].sort(key=lambda u: (u.get("uid") or ""))

        audit = {
            "missing_groups": missing_groups,
            "missing_memberships": sorted(
                missing_memberships,
                key=lambda r: (int(r.get("gidNumber") or 0), r.get("uid") or ""),
            ),
            "skipped_users": skipped_users,
            "outside_scope_users": outside_scope_users,
        }
        summary = {
            "missing_groups": len(missing_groups),
            "users_affected_by_missing_groups": sum(r["affected_count"] for r in missing_groups),
            "missing_memberships": len(missing_memberships),
            "skipped": len(skipped_users),
            "outside_scope": len(outside_scope_users),
        }
        return audit, summary

    finally:
        conn.unbind()


def ldap_check_user_group_membership(uid: str, gid_number: int) -> Tuple[bool, str, str]:
    """Check whether uid is a memberUid of the group implied by gid_number.
    Returns (ok, message, group_dn). Does NOT create groups.
    """
    uid = (uid or "").strip()
    group_dn = _group_dn_for_gid(int(gid_number))

    conn = _get_service_connection()
    try:
        conn.search(
            search_base=group_dn,
            search_filter="(objectClass=posixGroup)",
            search_scope=SUBTREE,
            attributes=["memberUid", "cn"],
        )
        if not conn.entries:
            return False, "Group missing", group_dn

        entry = conn.entries[0]
        members = set(entry.memberUid.values) if "memberUid" in entry else set()
        if uid in members:
            return True, "OK", group_dn
        return False, "User missing from group", group_dn
    finally:
        conn.unbind()


def ldap_add_user_to_group(uid: str, gid_number: int, test_mode: bool = False) -> Tuple[bool, str]:
    """Add uid to posixGroup.memberUid for the group implied by gid_number.
    Includes:
      - duplication check
      - auto-create class groups if missing (Policy C)
    """
    logger.info("ldap_add_user_to_group uid %s gid_number %d", uid, gid_number)
    uid = (uid or "").strip()
    ok, msg, group_dn = ldap_ensure_group_exists(int(gid_number), test_mode=test_mode)
    if not ok:
        return False, msg

    conn = _get_service_connection()
    try:
        conn.search(
            search_base=group_dn,
            search_filter="(objectClass=posixGroup)",
            search_scope=SUBTREE,
            attributes=["memberUid", "cn"],
        )
        if not conn.entries:
            return False, f"Group not found after ensure: {group_dn}"

        entry = conn.entries[0]
        existing = set(entry.memberUid.values) if "memberUid" in entry else set()
        if uid in existing:
            return True, f"{uid} already in group {entry.cn.value}"

        if test_mode:
            return True, f"TEST_MODE: would add {uid} to group {entry.cn.value}"

        conn.modify(group_dn, {"memberUid": [(MODIFY_ADD, [uid])]})
        if conn.result.get("description") != "success":
            return False, f"Group modify failed: {conn.result}"
        return True, f"Added {uid} to group {entry.cn.value}"
    finally:
        conn.unbind()


def ldap_cleanup_memberUid_for_uid(
    uid: str,
    test_mode: bool = False,
) -> Tuple[bool, str, List[str]]:
    """
    Remove 'uid' from memberUid in *all* posixGroup entries.

    This is useful after deleting a user so that group entries don't
    reference non-existent uids.

    Returns (ok, message, groups_touched).
    """
    uid = (uid or "").strip()
    if not uid:
        return False, "Empty uid provided for cleanup.", []

    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Service bind failed in ldap_cleanup_memberUid_for_uid: %s", e)
        return False, f"Service bind failed: {e}", []

    groups_touched: List[str] = []

    try:
        # Find all groups that reference this uid in memberUid
        safe_uid = escape_filter_chars(uid)
        conn.search(
            search_base=_group_base(),
            search_filter=f"(&(objectClass=posixGroup)(memberUid={safe_uid}))",
            search_scope=SUBTREE,
            attributes=["cn", "memberUid"],
        )

        if not conn.entries:
            return True, f"No memberUid references found for {uid}.", []

        sorted_entries = sorted(conn.entries, reverse=False)
        # for entry in conn.entries:
        for entry in sorted_entries:
            group_dn = entry.entry_dn
            groups_touched.append(group_dn)

            if test_mode:
                # In TEST MODE, we don't modify anything, just log
                logger.info(
                    "TEST_MODE: would remove uid=%s from group %s",
                    uid,
                    group_dn,
                )
                continue

            # Remove uid from memberUid
            conn.modify(
                dn=group_dn,
                changes={"memberUid": [(MODIFY_DELETE, [uid])]},
            )
            if conn.result.get("description") != "success":
                logger.warning(
                    "Failed to remove %s from %s: %s",
                    uid,
                    group_dn,
                    conn.result,
                )

        if test_mode:
            return (
                True,
                (f"TEST_MODE: would remove {uid} from {len(groups_touched)} group(s)."),
                groups_touched,
            )

        return (
            True,
            f"Removed {uid} from {len(groups_touched)} group(s).",
            groups_touched,
        )

    except Exception as e:
        logger.error("Error cleaning memberUid for %s: %s", uid, e)
        return False, f"Cleanup failed: {e}", groups_touched
    finally:
        conn.unbind()


def ldap_ensure_group_exists(gid_number: int, test_mode: bool = False) -> Tuple[bool, str, str]:
    """Policy C:
    - Auto-create missing *class* groups
    - Never auto-create the staff group (must exist)
    Returns (ok, message, group_dn).
    """
    gid_number = int(gid_number)
    group_dn = _group_dn_for_gid(gid_number)

    # Never auto-create staff group
    if gid_number == int(config.STAFF_GID_NUMBER):
        conn = _get_service_connection()
        try:
            conn.search(group_dn, "(objectClass=posixGroup)", attributes=["cn"])
            if not conn.entries:
                return (
                    False,
                    f"Staff group missing (create manually): {group_dn}",
                    group_dn,
                )
            return True, "OK", group_dn
        finally:
            conn.unbind()

    # Class groups: create if missing
    conn = _get_service_connection()
    try:
        conn.search(group_dn, "(objectClass=posixGroup)", attributes=["cn"])
        if conn.entries:
            return True, "OK", group_dn

        group_cn = group_dn.split(",")[0].split("=", 1)[1]  # cn=...

        if test_mode:
            return (
                True,
                f"TEST_MODE: would create group {group_cn} gid={gid_number}",
                group_dn,
            )

        attrs = {
            "objectClass": ["top", "posixGroup"],
            "cn": group_cn,
            "gidNumber": str(gid_number),
        }
        conn.add(group_dn, attributes=attrs)
        if conn.result.get("description") != "success":
            return False, f"Group create failed: {conn.result}", group_dn
        return True, f"Created group {group_cn}", group_dn
    finally:
        conn.unbind()


def ldap_get_group_by_gid(gid_number: int) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return a posixGroup by gidNumber, using the real group DN/CN from LDAP."""
    try:
        gid = int(gid_number)
    except Exception:
        return None, f"Invalid gidNumber: {gid_number!r}"

    conn = _get_service_connection()
    try:
        conn.search(
            search_base=_group_base(),
            search_filter=f"(&(objectClass=posixGroup)(gidNumber={gid}))",
            search_scope=SUBTREE,
            attributes=["cn", "gidNumber", "memberUid"],
            size_limit=2,
        )
        if not conn.entries:
            return None, f"No posixGroup found with gidNumber={gid}."

        e = conn.entries[0]
        members = []
        if "memberUid" in e:
            members = list(e.memberUid.values)

        return (
            {
                "cn": getattr(e, "cn", None).value if hasattr(e, "cn") else None,
                "gidNumber": gid,
                "dn": e.entry_dn,
                "members": members,
                "member_count": len(members),
            },
            "OK",
        )
    except Exception as e:
        logger.error("Error in ldap_get_group_by_gid: %s", e)
        return None, f"Group lookup failed: {e}"
    finally:
        conn.unbind()


def ldap_list_groups_for_uid(uid: str) -> Tuple[List[Dict[str, Any]], str]:
    """Return posixGroup entries where memberUid contains uid."""
    uid = (uid or "").strip()
    if not uid:
        return [], "Empty uid"

    conn = _get_service_connection()
    try:
        safe_uid = escape_filter_chars(uid)
        conn.search(
            search_base=_group_base(),
            search_filter=f"(&(objectClass=posixGroup)(memberUid={safe_uid}))",
            search_scope=SUBTREE,
            attributes=["cn", "gidNumber", "memberUid"],
        )
        groups = []
        for e in sorted(conn.entries, reverse=False):
            try:
                gid = int(getattr(e, "gidNumber", None).value)
            except Exception:
                gid = None
            members = list(e.memberUid.values) if "memberUid" in e else []
            groups.append(
                {
                    "cn": getattr(e, "cn", None).value if hasattr(e, "cn") else None,
                    "gidNumber": gid,
                    "dn": e.entry_dn,
                    "member_count": len(members),
                }
            )
        groups.sort(key=lambda g: ((g.get("cn") or "").lower(), g.get("gidNumber") or 0))
        return groups, "OK"
    except Exception as e:
        logger.error("Error in ldap_list_groups_for_uid: %s", e)
        return [], f"Group membership lookup failed: {e}"
    finally:
        conn.unbind()


def ldap_add_user_to_existing_group(
    uid: str, gid_number: int, test_mode: bool = False
) -> Tuple[bool, str]:
    """Add uid to an existing posixGroup.memberUid, found by gidNumber.

    Unlike ldap_add_user_to_group(), this does not auto-create class groups.
    It is intended for secondary/supplementary group management.
    """
    logger.info("ldap_add_user_to_existing_group uid %s gid_number %d", uid, gid_number)
    uid = (uid or "").strip()
    if not uid:
        logger.error("Empty uid %s gid_number is %d", uid, gid_number)
        return False, "Empty uid"

    group, msg = ldap_get_group_by_gid(gid_number)
    if not group:
        logger.error("Bad group uid %s gid_number is %d", uid, gid_number)
        return False, msg

    if uid in set(group.get("members") or []):
        logger.warning("uid %s is already a member gid_number is %d", uid, gid_number)
        return True, f"{uid} is already a member of {group.get('cn')}"

    if test_mode:
        return True, f"TEST_MODE: would add {uid} to {group.get('cn')}"

    conn = _get_service_connection()
    try:
        conn.modify(group["dn"], {"memberUid": [(MODIFY_ADD, [uid])]})
        if conn.result.get("description") != "success":
            logger.error("Group modify failed:%s %d %s", uid, gid_number, conn.result)
            return False, f"Group modify failed: {conn.result}"
        return True, f"Added {uid} to {group.get('cn')}"
    finally:
        conn.unbind()


def ldap_remove_user_from_existing_group(
    uid: str, gid_number: int, test_mode: bool = False
) -> Tuple[bool, str]:
    """Remove uid from an existing posixGroup.memberUid, found by gidNumber."""
    uid = (uid or "").strip()
    if not uid:
        return False, "Empty uid"

    group, msg = ldap_get_group_by_gid(gid_number)
    if not group:
        return False, msg

    if uid not in set(group.get("members") or []):
        return True, f"{uid} is not a member of {group.get('cn')}"

    if test_mode:
        return True, f"TEST_MODE: would remove {uid} from {group.get('cn')}"

    conn = _get_service_connection()
    try:
        conn.modify(group["dn"], {"memberUid": [(MODIFY_DELETE, [uid])]})
        if conn.result.get("description") != "success":
            return False, f"Group modify failed: {conn.result}"
        return True, f"Removed {uid} from {group.get('cn')}"
    finally:
        conn.unbind()


def _group_dn_for_gid(gid_number: int) -> str:
    """Return the expected DN for the posixGroup matching the gidNumber.
    Staff:    cn=staff,<LDAP_GROUP_BASE_DN>
    Students: cn=classYYYY,<LDAP_GROUP_BASE_DN>
    """
    gid_number = int(gid_number)
    if gid_number == int(config.STAFF_GID_NUMBER):
        cn = getattr(config, "STAFF_GROUP_CN", "staff").lower()
    else:
        tmpl = getattr(config, "CLASS_GROUP_CN_TEMPLATE", "class{gidNumber}")
        cn = tmpl.format(gidNumber=gid_number).lower()
    return f"cn={cn},{_group_base()}"
