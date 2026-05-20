# ruff: noqa: F401

from ldap3 import (
    ALL,
    ALL_ATTRIBUTES,
    MODIFY_ADD,
    MODIFY_DELETE,
    MODIFY_REPLACE,
    SUBTREE,
    Connection,
    Server,
)
from ldap3.utils.conv import escape_filter_chars

import config
from ldap_logging import logger


def get_service_connection() -> Connection:
    server = Server(config.LDAP_SERVER_URI, get_info=ALL)
    return Connection(
        server,
        user=config.LDAP_BIND_DN,
        password=config.LDAP_BIND_PASSWORD,
        auto_bind=True,
    )


# Backwards compatibility
_get_service_connection = get_service_connection
