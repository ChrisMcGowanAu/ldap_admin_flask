from __future__ import annotations

from typing import Optional

from ldap_core import SUBTREE, config, escape_filter_chars


def find_user_dn(conn, username: str) -> Optional[str]:
    username = (username or "").strip()
    if not username:
        return None

    safe = escape_filter_chars(username)
    conn.search(
        search_base=config.LDAP_USER_BASE_DN,
        search_filter=f"(uid={safe})",
        search_scope=SUBTREE,
        attributes=["uid"],  # anything valid; or [] also works
        size_limit=2,
    )
    if not conn.entries:
        return None
    return conn.entries[0].entry_dn
