# version.py
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=APP_DIR,
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()


def _is_dirty() -> bool:
    try:
        return bool(_git("status", "--porcelain"))
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_app_version() -> str:
    """Return a friendly version string, computed once and cached for the process lifetime.

    Caching avoids forking two or three ``git`` subprocesses on every template render
    (this function is called from an ``@app.context_processor``).

    Override at deploy time by setting the ``LDAP_ADMIN_VERSION`` environment variable,
    which is useful when the deployment host has no git available (e.g. Docker images).

    Examples:
      v0.2.0 - Group audit and supplementary group management
      v0.2.0 - Group audit and supplementary group management - dirty
      v0.2.0 + 3 commits (1c44e22)
      1c44e22
    """
    env_ver = os.getenv("LDAP_ADMIN_VERSION")
    if env_ver:
        return env_ver

    dirty = " - dirty" if _is_dirty() else ""

    try:
        # Best case: HEAD is exactly on a tag.
        tag = _git("describe", "--exact-match", "--tags", "HEAD")

        # Annotated tag message subject.
        tag_subject = _git(
            "for-each-ref",
            f"refs/tags/{tag}",
            "--format=%(contents:subject)",
        )

        if tag_subject:
            return f"{tag} - {tag_subject}{dirty}"

        # Lightweight tags have no message.
        return f"{tag}{dirty}"

    except Exception:
        pass

    try:
        # Not exactly on a tag: show nearest tag and commit count.
        desc = _git("describe", "--tags", "--long", "--always")
        sha = _git("rev-parse", "--short", "HEAD")

        # Example desc: v0.2.0-3-g1c44e22
        parts = desc.rsplit("-", 2)
        if len(parts) == 3 and parts[1].isdigit():
            tag, commits_since, _gsha = parts
            return f"{tag} + {commits_since} commits ({sha}){dirty}"

        return f"{desc}{dirty}"

    except Exception:
        return "unknown"
