from __future__ import annotations

import csv
import os
from typing import Any, Dict

from ldap_core import config, get_service_connection, logger
from policy import compute_email_for_uid

_get_service_connection = get_service_connection


def audit_log_new_user(row: Dict[str, Any]) -> None:
    """
    Append one 'new user created' record to CSV (Excel-friendly).
    Never raises (logging only).
    """
    logger.info("audit_log_new_user")
    fname = ""
    gid = str(row.get("gidNumber", "unknown"))
    logger.info("audit_log_new_user gid=%s", str(gid))

    if gid == str(config.STAFF_GID_NUMBER):
        fname = "ldap_new_users_staff.csv"
    else:
        fname = "ldap_new_users_students_" + gid + ".csv"

    logger.info("audit_log_new_user fname=%s", fname)
    base_dir = getattr(config, "NEW_USERS_AUDIT_DIR", "/var/log/ldap_admin")
    logger.info("audit_log_new_user base_dir=%s", base_dir)
    path = os.path.join(base_dir, fname)

    try:
        logger.info("new user filename ->%s<-", path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file_exists = os.path.exists(path)
        email = ""
        uid = row.get("uid", "")
        class_key = row.get("class_key", "")
        gid_number = str(row.get("gid_number", "1"))
        email = compute_email_for_uid(uid, class_key=class_key, gid_number=gid_number)
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
            uid = row.get("uid", "")
            class_key = row.get("class_key", "")
            gid_number = row.get("gid_number", "")
            email = compute_email_for_uid(uid, class_key=class_key, gid_number=gid_number)
            fullname = str(row.get("givenName", "") + " " + row.get("sn", ""))
            data = [
                {
                    "Timestamp": row.get("timestamp", ""),
                    "Admin": row.get("admin_user", ""),
                    "Class": row.get("class_key", ""),
                    "First": row.get("givenName", ""),
                    "Last": row.get("sn", ""),
                    "Username": uid,
                    "Password": row.get("password", ""),
                    "Email": email,
                    "FullName": fullname,
                }
            ]
            data2 = [
                {
                    row.get("timestamp", ""),  # Timestamp
                    row.get("admin_user", ""),  # Admin
                    row.get("class_key", ""),  # Class
                    row.get("givenName", ""),  # First
                    row.get("sn", ""),  # Last
                    uid,  # Username
                    row.get("password", ""),  # Password
                    email,  # Email
                    row.get("dn", ""),  # FullName
                }
            ]
            # logger.info(str(data))
            logger.info(str(data))
            logger.info(str(data2))
            w.writerows(data)
    except Exception as e:
        logger.warning("Failed to write new-user audit CSV (%s): %s", path, e)
