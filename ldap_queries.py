# ldap_queries.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ldap_core import SUBTREE, config, get_service_connection, logger


def ldap_list_users_by_gid(gid_number: int) -> Tuple[List[Dict[str, Any]], str]:
    gid_number = int(gid_number)
    try:
        conn = get_service_connection()
    except Exception as e:
        logger.error("Service bind failed in ldap_list_users_by_gid: %s", e)
        return [], f"Service bind failed: {e}"

    try:
        conn.search(
            search_base=config.LDAP_USER_BASE_DN,
            search_filter=f"(gidNumber={gid_number})",
            search_scope=SUBTREE,
            attributes=["uid", "cn", "gidNumber", "homeDirectory"],
        )
        users = []
        for e in sorted(conn.entries):
            users.append(
                {
                    "uid": getattr(e, "uid", None).value if hasattr(e, "uid") else None,
                    "cn": getattr(e, "cn", None).value if hasattr(e, "cn") else None,
                    "gidNumber": int(getattr(e, "gidNumber", gid_number).value),
                    "homeDirectory": (
                        getattr(e, "homeDirectory", None).value
                        if hasattr(e, "homeDirectory")
                        else None
                    ),
                    "dn": e.entry_dn,
                }
            )
        return users, "OK"
    except Exception as e:
        logger.error("Error in ldap_list_users_by_gid: %s", e)
        return [], f"Lookup failed: {e}"
    finally:
        conn.unbind()
