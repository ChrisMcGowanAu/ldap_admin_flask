from __future__ import annotations

import datetime
from typing import Any, Dict, Optional, Tuple

from flask import session

from audit import audit_log_new_user
from home_paths import compute_home_directory
from ldap_core import (
    ALL_ATTRIBUTES,
    MODIFY_REPLACE,
    SUBTREE,
    Connection,
    config,
    escape_filter_chars,
    get_service_connection,
    logger,
)

# from ldap_groups import ldap_add_user_to_group
from ldap_lookup import find_user_dn
from ldap_password import hash_password_for_ldap
from provisioning import _append_zimbra_command, _class_to_gid_and_home, create_home_directory

_find_user_dn = find_user_dn
_get_service_connection = get_service_connection


def ldap_delete_user(uid: str, test_mode: bool = False) -> Tuple[bool, str]:
    """
    Delete a user by uid (supports partial via find_user_dn).
    In TEST_MODE, just logs and reports what would happen.
    """
    uid = (uid or "").strip()
    if not uid:
        return False, "Empty uid"

    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Service bind failed in ldap_delete_user: %s", e)
        return False, f"Service bind failed: {e}"

    try:
        user_dn = find_user_dn(conn, uid)
        if not user_dn:
            return False, f"User {uid} not found."

        if test_mode:
            logger.info("TEST_MODE: would delete user %s (DN=%s)", uid, user_dn)
            return True, f"TEST_MODE: would delete {uid} ({user_dn})"

        logger.info("Deleting user %s (DN=%s)", uid, user_dn)
        conn.delete(user_dn)
        if conn.result.get("description") != "success":
            logger.error("LDAP delete failed: %s", conn.result)
            return False, f"LDAP delete failed: {conn.result}"

        logger.info("User %s deleted successfully", uid)
        return True, f"User {uid} deleted."
    except Exception as e:
        logger.error("Exception during LDAP delete: %s", e)
        return False, f"LDAP delete exception: {e}"
    finally:
        conn.unbind()


def ldap_list_all_users(limit: int = 5000):
    """Return list of {uid, gidNumber, cn, dn} for all users.
    Not currently used but left in for possible future use"""
    conn = _get_service_connection()
    try:
        conn.search(
            search_base=config.LDAP_USER_BASE_DN,
            search_filter="(uid=*)",
            search_scope=SUBTREE,
            attributes=["uid", "gidNumber", "cn"],
            size_limit=limit,
        )
        sorted_entries = sorted(conn.entries, reverse=False)
        out = []
        # for e in conn.entries:
        for e in sorted_entries:
            out.append(
                {
                    "uid": getattr(e, "uid", None).value,
                    "gidNumber": getattr(e, "gidNumber", None).value,
                    "cn": getattr(e, "cn", None).value,
                    "dn": e.entry_dn,
                }
            )
        return out, "OK"
    finally:
        conn.unbind()


def ldap_search_users(uid_fragment: str, limit: int = 5000):
    """
    Returns list of {"uid","cn","gidNumber","homeDirectory","dn"} for uid fragment search.
    """
    frag = (uid_fragment or "").strip()
    if not frag:
        return [], "Empty search"

    safe_frag = escape_filter_chars(frag)
    uid_filter = safe_frag if "*" in frag else f"*{safe_frag}*"

    conn = _get_service_connection()
    try:
        conn.search(
            search_base=config.LDAP_USER_BASE_DN,
            search_filter=f"(uid={uid_filter})",
            search_scope=SUBTREE,
            attributes=["uid", "cn", "gidNumber", "homeDirectory"],
            size_limit=limit,
        )
        matches = []
        for e in sorted(conn.entries, reverse=False):
            matches.append(
                {
                    "uid": getattr(e, "uid", None).value,
                    "cn": getattr(e, "cn", None).value,
                    "gidNumber": getattr(e, "gidNumber", None).value,
                    "homeDirectory": getattr(e, "homeDirectory", None).value,
                    "dn": e.entry_dn,
                }
            )
        return matches, "OK"
    finally:
        conn.unbind()


def ldap_create_user(
    given_name: str,
    family_name: str,
    username: str,
    password: str,
    class_key: str,
    home: str,
    test_mode: bool = False,
    admin_user: str = "",
    display_name: Optional[str] = None,
) -> Tuple[bool, str]:
    """Create a new LDAP user entry, with username collision handling."""
    given_name = given_name.strip()
    family_name = family_name.strip()
    requested_username = username.strip()
    home_dir = home.strip()
    admin_user = session.get("admin_user", "Unknown")
    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Failed to bind as service account: %s", e)
        return False, f"Service bind failed: {e}"

    # Resolve to an available uid (chrism, chrism1, chrism2, ...)
    try:
        final_username = _find_available_username(conn, requested_username)
    except Exception as e:
        logger.error("Error resolving available username: %s", e)
        conn.unbind()
        return False, f"Username allocation failed: {e}"

    username = final_username

    try:
        gid_number, home_directory = compute_home_directory(username, class_key)
        if len(home_dir) > 4:
            home_directory = home
    except Exception as e:
        logger.error("Class mapping failed: %s", e)
        conn.unbind()
        return False, f"Class mapping failed: {e}"

    try:
        uid_number = _get_next_uid_number(conn)
    except Exception as e:
        logger.error("Failed to allocate uidNumber: %s", e)
        conn.unbind()
        return False, f"Failed to allocate uidNumber: {e}"

    cn = ""
    if display_name:
        cn = display_name.strip()
    else:
        cn = f"{given_name} {family_name}"

    user_dn = config.LDAP_USER_DN_TEMPLATE.format(
        cn=cn,
        base_dn=config.LDAP_USER_BASE_DN,
    )

    sn = family_name
    givenName = given_name
    hashed_password = hash_password_for_ldap(password)
    attributes = {
        "objectClass": ["inetOrgPerson", "posixAccount", "shadowAccount"],
        "uid": username,
        "sn": sn,
        "givenName": givenName,
        "cn": cn,
        "displayName": cn,
        "uidNumber": str(uid_number),
        "gidNumber": str(gid_number),
        "homeDirectory": home_directory,
        "loginShell": config.DEFAULT_LOGIN_SHELL,
        "userPassword": hashed_password,
    }

    logger.info(
        "Prepared to create user DN=%s requested_uid=%s final_uid=%s uidNumber=%s gidNumber=%s home=%s class=%s",
        user_dn,
        requested_username,
        username,
        uid_number,
        gid_number,
        home_directory,
        class_key,
    )

    if test_mode:
        logger.info("TEST_MODE enabled - not actually creating user in LDAP")
        conn.unbind()
        if username == requested_username:
            return True, f"TEST_MODE: would create user {username}."
        else:
            return (
                True,
                f"TEST_MODE: would create user as {username} (requested {requested_username}).",
            )

    try:
        conn.add(dn=user_dn, attributes=attributes)
        if not conn.result["description"] == "success":
            logger.error("LDAP add failed: %s", conn.result)
            return False, f"LDAP add failed: {conn.result}"
    except Exception as e:
        logger.error("Exception during LDAP add: %s", e)
        return False, f"LDAP add exception: {e}"
    finally:
        conn.unbind()

    # Ensure group membership (Policy C: auto-create class groups; staff group must exist)
    from ldap_groups import ldap_add_user_to_group  # local import avoids circular import

    group_ok, group_msg = ldap_add_user_to_group(username, gid_number, test_mode=test_mode)

    if not group_ok:
        logger.warning("User created but group membership not set: %s", group_msg)

    # Create home directory on filesystem
    if getattr(config, "CREATE_HOME_DIR", False):
        home_ok, home_msg = create_home_directory(
            home_directory, uid_number, gid_number, test_mode=test_mode
        )
        if not home_ok:
            logger.warning("User created but home directory not created: %s", home_msg)

    if username == requested_username:
        msg = f"User {username} created successfully."
    else:
        msg = f"User created successfully as {username} (requested {requested_username})."

    logger.info(msg)

    try:
        audit_log_new_user(
            {
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "admin_user": admin_user,
                "uid": username,
                "password": password,
                "cn": cn,
                "givenName": givenName,
                "sn": sn,
                "uidNumber": str(uid_number),
                "gidNumber": str(gid_number),
                "class_key": class_key,
                "homeDirectory": home_directory,
                "loginShell": config.DEFAULT_LOGIN_SHELL,
                "requested_uid": requested_username,
                "test_mode": str(bool(test_mode)),
            }
        )
    except Exception:
        pass

    # Append Zimbra provisioning command for REAL creations only
    if not test_mode and password:
        try:
            _append_zimbra_command(
                username=username,
                given_name=given_name,
                family_name=family_name,
                class_key=class_key,
                password=password,
                display_name=cn,
                admin_user=admin_user,
            )
        except Exception as e:
            logger.error("Failed to append Zimbra provisioning command: %s", e)

    return True, msg


def ldap_get_user(username: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Retrieve selected attributes for a user by uid or uid fragment."""
    username = username.strip()
    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Failed to bind as service account: %s", e)
        return None, f"Service bind failed: {e}"

    try:
        user_dn = find_user_dn(conn, username)
        if not user_dn:
            return None, f"User {username} not found."

        conn.search(
            search_base=user_dn,
            search_filter="(objectClass=*)",
            search_scope=SUBTREE,
            attributes=ALL_ATTRIBUTES,
        )
        if not conn.entries:
            return None, f"User {username} not found at DN {user_dn}."

        entry = conn.entries[0]
        data = {"dn": entry.entry_dn}
        for attr in [
            "uid",
            "cn",
            "sn",
            "givenName",
            "displayName",
            "uidNumber",
            "gidNumber",
            "homeDirectory",
            "loginShell",
        ]:
            try:
                data[attr] = getattr(entry, attr).value
            except Exception:
                data[attr] = None

        return data, "OK"

    except Exception as e:
        logger.error("Error during user lookup: %s", e)
        return None, f"Lookup failed: {e}"
    finally:
        conn.unbind()


def ldap_update_user(
    username: str,
    attrs: Dict[str, str],
    test_mode: bool = False,
) -> Tuple[bool, str]:
    """Update selected attributes for a user.

    Editable: givenName, cn/displayName, homeDirectory, loginShell, and class_key
    which changes gidNumber and optionally homeDirectory.
    """
    username = username.strip()

    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Failed to bind as service account: %s", e)
        return False, f"Service bind failed: {e}"

    new_gid = None
    group_msg = None

    try:
        user_dn = _find_user_dn(conn, username)
        if not user_dn:
            return False, f"User {username} not found."

        allowed_attrs = {"givenName", "cn", "displayName", "homeDirectory", "loginShell"}
        changes = {}
        class_key = (attrs.get("class_key") or "").strip()

        if class_key:
            try:
                new_gid, computed_home = _class_to_gid_and_home(username, class_key)
                changes["gidNumber"] = [(MODIFY_REPLACE, [str(new_gid)])]
                if not (attrs.get("homeDirectory") or "").strip():
                    changes["homeDirectory"] = [(MODIFY_REPLACE, [computed_home])]
            except Exception as e:
                return False, f"Class mapping failed in update: {e}"

        for attr, value in attrs.items():
            logger.info("attr %s value %s", attr, value)
            if attr not in allowed_attrs:
                continue
            if value is None or value == "":
                continue

            if attr in ("cn", "displayName"):
                changes["cn"] = [(MODIFY_REPLACE, [value])]
                changes["displayName"] = [(MODIFY_REPLACE, [value])]
            else:
                changes[attr] = [(MODIFY_REPLACE, [value])]

        if not changes:
            return False, "No editable attributes provided."

        logger.info("Prepared to update DN=%s with changes=%s", user_dn, list(changes.keys()))

        if test_mode:
            if new_gid is not None:
                return (
                    True,
                    "TEST_MODE: attribute update simulated; would also update group membership.",
                )
            return True, "TEST_MODE: attribute update simulated."

        conn.modify(dn=user_dn, changes=changes)
        if conn.result.get("description") != "success":
            logger.error("LDAP modify (update_user) failed: %s", conn.result)
            return False, f"LDAP modify failed: {conn.result}"

        # If the primary gidNumber changed, update memberUid after the user modify succeeds.
        if new_gid is not None:
            from ldap_groups import ldap_add_user_to_group  # local import avoids circular import

            g_ok, group_msg = ldap_add_user_to_group(username, new_gid, test_mode=False)
            if not g_ok:
                logger.warning("Group membership update failed during update_user: %s", group_msg)
                return (
                    True,
                    f"User attributes updated, but group membership update failed: {group_msg}",
                )

        logger.info("Attributes updated successfully for %s", username)
        if group_msg:
            return True, f"User attributes updated successfully. {group_msg}"
        return True, "User attributes updated successfully."

    except Exception as e:
        logger.warning("Exception during LDAP attribute update: %s", e)
        return False, f"LDAP update exception: {e}"
    finally:
        conn.unbind()


def _get_next_uid_number(conn: Connection) -> int:
    """Very simple uidNumber allocator: find the max uidNumber and add 1."""
    conn.search(
        search_base=config.LDAP_USER_BASE_DN,
        search_filter="(uidNumber=*)",
        search_scope=SUBTREE,
        attributes=["uidNumber"],
    )
    max_uid = config.UID_BASE_NUMBER
    for entry in conn.entries:
        try:
            val = int(entry.uidNumber.value)
            if val > max_uid:
                max_uid = val
        except Exception:
            continue
    return max_uid + 1


def _original_find_user_dn(conn: Connection, username: str) -> Optional[str]:
    """Find the DN for a user with the given uid or uid fragment using an existing service connection."""
    username = username.strip()
    if not username:
        return None

    # Allow simple partial search: treat input as a fragment of uid.
    # If the caller wants raw LDAP wildcards, they can include '*' themselves.
    if "*" in username:
        uid_filter_value = username
    else:
        uid_filter_value = f"*{username}*"

    search_filter = f"(uid={uid_filter_value})"

    conn.search(
        search_base=config.LDAP_USER_BASE_DN,
        search_filter=search_filter,
        search_scope=SUBTREE,
        # no explicit attributes; we only need entry_dn
    )
    if not conn.entries:
        return None
    if len(conn.entries) > 1:
        # sorted_entries = sorted(conn.entries, reverse=False)
        # logger.info(str(sorted_entries))
        logger.warning("Multiple entries found for uid fragment '%s'; using first", username)
    return conn.entries[0].entry_dn


def _find_available_username(conn: Connection, base_username: str) -> str:
    """Return a uid that does not yet exist, by appending 1,2,... if needed."""
    base = base_username.strip().lower()
    if not base:
        raise ValueError("Base username is empty")

    candidate = base
    suffix = 1

    while True:
        conn.search(
            search_base=config.LDAP_USER_BASE_DN,
            search_filter=f"(uid={escape_filter_chars(candidate)})",
            search_scope=SUBTREE,
            attributes=["uid"],
        )
        if not conn.entries:
            # free!
            return candidate
        candidate = f"{base}{suffix}"
        suffix += 1
