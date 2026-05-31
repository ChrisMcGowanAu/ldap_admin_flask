from __future__ import annotations

import base64
import hashlib
import os
from typing import List, Tuple

from ldap_core import MODIFY_REPLACE, SUBTREE, config, get_service_connection, logger
from ldap_lookup import find_user_dn

_get_service_connection = get_service_connection


def hash_password_for_ldap(plain: str) -> str:
    """
    Return an {SSHA} hash for the given plain-text password.

    This matches the format produced by 'slappasswd -h {SSHA}'.
    The stored value looks like: {SSHA}<base64(sha1(password+salt) + salt)>

    Security note
    -------------
    {SSHA} uses SHA-1 which is cryptographically weak by modern standards.
    It is used here because it remains the most widely-supported scheme in
    OpenLDAP deployments and is compatible with Sophos, Zimbra/Synacor, and
    other services that bind against the LDAP directory.

    If your OpenLDAP server supports it, consider migrating to a stronger
    scheme such as {ARGON2} or {PBKDF2-SHA512}.  You can set the default
    hash on the server side via ``olcPasswordHash`` (cn=config) so that
    slapd upgrades existing hashes transparently on the next bind.
    """
    if plain is None:
        plain = ""
    plain_bytes = plain.encode("utf-8")

    # 4–8 bytes of salt is typical. 4 is enough here.
    salt = os.urandom(4)

    sha = hashlib.sha1(plain_bytes + salt).digest()
    value = base64.b64encode(sha + salt).decode("ascii")
    return "{SSHA}" + value


def ldap_change_password(
    username: str,
    new_password: str,
    test_mode: bool = False,
) -> Tuple[bool, str]:
    """Change the user's password."""
    username = username.strip()

    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Failed to bind as service account: %s", e)
        return False, f"Service bind failed: {e}"

    try:
        user_dn = find_user_dn(conn, username)
        if not user_dn:
            return False, f"User {username} not found."

        logger.info("Prepared to change password for DN=%s", user_dn)

        if test_mode:
            logger.info("TEST_MODE enabled - not actually changing password in LDAP")
            return True, "TEST_MODE: password change simulated."

        hashed = hash_password_for_ldap(new_password)
        conn.modify(
            dn=user_dn,
            changes={"userPassword": [(MODIFY_REPLACE, [hashed])]},
        )
        if not conn.result["description"] == "success":
            logger.error("LDAP modify failed: %s", conn.result)
            return False, f"LDAP modify failed: {conn.result}"

        logger.info("Password changed successfully for %s", username)
        return True, "Password changed successfully."

    except Exception as e:
        logger.error("Exception during LDAP modify: %s", e)
        return False, f"LDAP modify exception: {e}"
    finally:
        conn.unbind()


def ldap_rehash_cleartext_passwords(
    limit: int = 0,
    test_mode: bool = True,
) -> Tuple[int, int, int, List[str]]:
    """
    Scan all users under LDAP_USER_BASE_DN, looking at userPassword.

    Any value that does NOT start with '{' is treated as clear text and
    will be rehashed to {SSHA} using hash_password_for_ldap().

    Returns (total_users, hashed_count, skipped_hashed, errors).

    NOTE:
      - test_mode=True (default): logs what it *would* do, but makes no changes.
      - test_mode=False: actually rewrites the userPassword attribute.
    """
    try:
        conn = _get_service_connection()
    except Exception as e:
        logger.error("Service bind failed in ldap_rehash_cleartext_passwords: %s", e)
        return 0, 0, 0, [f"Service bind failed: {e}"]

    total = 0
    hashed_count = 0
    skipped_hashed = 0
    errors: List[str] = []

    try:
        conn.search(
            search_base=config.LDAP_USER_BASE_DN,
            search_filter="(userPassword=*)",
            search_scope=SUBTREE,
            attributes=["uid", "userPassword"],
            size_limit=limit or 0,
        )
        sorted_entries = sorted(conn.entries, reverse=False)

        # for entry in conn.entries:
        for entry in sorted_entries:
            total += 1

            try:
                uid = getattr(entry, "uid", None)
                uid_val = uid.value if uid is not None else "<no-uid>"

                up = getattr(entry, "userPassword", None)
                if up is None:
                    continue

                # ldap3 may return bytes or str
                current = up.value
                if isinstance(current, bytes):
                    try:
                        current = current.decode("utf-8", errors="ignore")
                    except Exception:
                        current = str(current)

                if not current:
                    logger.info("Empty userPassword for uid=%s; skipping", uid_val)
                    continue

                # If it starts with '{', assume it is already hashed/schemed.
                if str(current).startswith("{"):
                    skipped_hashed += 1
                    continue

                # Treat as clear text
                plain = str(current)
                logger.info(
                    "Found clear-text userPassword for uid=%s; will rehash (test_mode=%s)",
                    uid_val,
                    test_mode,
                )

                if test_mode:
                    # Don't change, just log
                    continue

                new_hash = hash_password_for_ldap(plain)

                conn.modify(
                    dn=entry.entry_dn,
                    changes={"userPassword": [(MODIFY_REPLACE, [new_hash])]},
                )
                if conn.result.get("description") != "success":
                    msg = f"Modify failed for uid={uid_val}: {conn.result}"
                    logger.error(msg)
                    errors.append(msg)
                else:
                    hashed_count += 1

            except Exception as inner_e:
                msg = f"Error processing entry {entry.entry_dn}: {inner_e}"
                logger.error(msg)
                errors.append(msg)

    except Exception as e:
        msg = f"Search failed in rehash_cleartext: {e}"
        logger.error(msg)
        errors.append(msg)
    finally:
        conn.unbind()

    return total, hashed_count, skipped_hashed, errors
