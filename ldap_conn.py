from __future__ import annotations

from typing import Tuple

from ldap_core import Connection  # <-- add this
from ldap_core import ALL, Server, config, logger
from ldap_lookup import find_user_dn


def _get_service_connection() -> Connection:
    server = Server(config.LDAP_SERVER_URI, get_info=ALL)
    conn = Connection(
        server,
        user=config.LDAP_BIND_DN,
        password=config.LDAP_BIND_PASSWORD,
        auto_bind=True,
    )
    return conn


def ldap_test_bind(username: str, password: str) -> Tuple[bool, str]:
    """Attempt to bind as the given user using uid=<username> (partial allowed)."""
    username = username.strip()

    try:
        service_conn = _get_service_connection()
    except Exception as e:
        logger.error("Service bind failed during test_bind: %s", e)
        return False, f"Service bind failed: {e}"

    try:
        user_dn = find_user_dn(service_conn, username)
        if not user_dn:
            return False, f"User {username} not found."

        logger.info("Testing bind for %s as DN=%s", username, user_dn)

    finally:
        service_conn.unbind()

    try:
        server = Server(config.LDAP_SERVER_URI, get_info=ALL)
        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        user_conn.unbind()
        logger.info("Successful bind for %s", username)
        return True, "Bind successful"
    except Exception as e:
        logger.warning("Bind failed for %s (DN=%s): %s", username, user_dn, e)
        return False, str(e)
