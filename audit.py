from __future__ import annotations

import csv
import os
from typing import Any, Dict

from ldap_core import config, get_service_connection, logger
from policy import compute_email_for_uid

_get_service_connection = get_service_connection


def audit_log_new_user(row: Dict[str, Any]) -> None:
    """Append one 'new user created' record to the per-group CSV audit file.

    Files are written to NEW_USERS_AUDIT_DIR (configured in config.py).
    Staff records go to ``ldap_new_users_staff.csv``; student records go to
    ``ldap_new_users_students_<gidNumber>.csv``.

    NOTE: The CSV contains the plaintext temporary password so that it can be
    distributed to users.  The audit directory must be root-owned with mode
    700 and the files should be treated as sensitive.

    This function never raises — failures are logged as warnings only.
    """
    gid = str(row.get("gidNumber", "unknown"))
    logger.info("audit_log_new_user gid=%s", gid)

    if gid == str(config.STAFF_GID_NUMBER):
        fname = "ldap_new_users_staff.csv"
    else:
        fname = "ldap_new_users_students_" + gid + ".csv"

    base_dir = getattr(config, "NEW_USERS_AUDIT_DIR", "/var/log/ldap_admin")
    path = os.path.join(base_dir, fname)

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file_exists = os.path.exists(path)

        uid = row.get("uid", "")
        class_key = row.get("class_key", "")
        gid_number = row.get("gid_number", "")
        email = compute_email_for_uid(uid, class_key=class_key, gid_number=gid_number)
        fullname = f"{row.get('givenName', '')} {row.get('sn', '')}".strip()

        header = [
            "Timestamp",
            "Admin",
            "Class",
            "First",
            "Last",
            "Username",
            "Password",
            "Email",
            "FullName",
        ]

        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header)
            if not file_exists:
                w.writeheader()
            w.writerow(
                {
                    "Timestamp": row.get("timestamp", ""),
                    "Admin": row.get("admin_user", ""),
                    "Class": class_key,
                    "First": row.get("givenName", ""),
                    "Last": row.get("sn", ""),
                    "Username": uid,
                    "Password": row.get("password", ""),
                    "Email": email,
                    "FullName": fullname,
                }
            )

        logger.info("audit_log_new_user wrote record uid=%s path=%s", uid, path)

    except Exception as e:
        logger.warning("Failed to write new-user audit CSV (%s): %s", path, e)
