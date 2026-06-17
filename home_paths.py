from __future__ import annotations

from typing import Tuple

import config
from ldap_core import logger


def compute_home_directory(username: str, class_key: str) -> Tuple[int, str]:
    """
    Return (gidNumber, homeDirectory) for a user.

    HOME_STYLE values:
      classic_unix:
        /home/{username}

      graduation_year_group:
        staff:    /lorienNet/staff/{username}
        students: /lorienNet/classes/class{gidNumber}/{username}
    """
    username = (username or "").strip().lower()
    class_key = (class_key or "").strip()

    logger.info("compute_home_directory user %s class %s", username, class_key)

    home_style = getattr(config, "HOME_STYLE", "classic_unix").strip().lower()

    if class_key.lower() == "staff":
        gid_number = int(config.STAFF_GID_NUMBER)

        if home_style == "classic_unix":
            base = getattr(config, "CLASSIC_UNIX_HOME_BASE", "/home").rstrip("/")
            return gid_number, f"{base}/{username}"

        if home_style == "graduation_year_group":
            base = getattr(config, "GRAD_YEAR_STAFF_HOME_BASE", "/lorienNet/staff").rstrip("/")
            return gid_number, f"{base}/{username}"

        raise ValueError(f"Unknown HOME_STYLE: {home_style!r}")

    if class_key not in config.CLASS_OPTIONS:
        raise ValueError(f"Unknown class_key: {class_key!r}")

    if not username:
        raise ValueError("Username is required")

    if not class_key:
        raise ValueError("Class/group is required")

    if class_key not in config.CLASS_OPTIONS:
        raise ValueError(f"Unknown class_key: {class_key!r}")

    info = config.CLASS_OPTIONS[class_key]
    gid_number = int(info["gidNumber"])

    home_style = getattr(config, "HOME_STYLE", "classic_unix").strip().lower()

    logger.info(
        "compute_home_directory username=%s class_key=%s style=%s",
        username,
        class_key,
        home_style,
    )

    if home_style == "classic_unix":
        base = getattr(config, "CLASSIC_UNIX_HOME_BASE", "/home").rstrip("/")
        home_directory = f"{base}/{username}"
        logger.info(
            "classic_unix home result gidNumber=%d home=%s",
            gid_number,
            home_directory,
        )
        logger.info(
            "classic compute_home_directory returning gid %d home %s", gid_number, home_directory
        )
        return gid_number, home_directory

    if home_style == "graduation_year_group":
        if gid_number == int(config.STAFF_GID_NUMBER):
            base = getattr(
                config,
                "GRAD_YEAR_STAFF_HOME_BASE",
                "/lorienNet/staff",
            ).rstrip("/")
            home_directory = f"{base}/{username}"
        else:
            base = getattr(
                config,
                "GRAD_YEAR_CLASSES_HOME_BASE",
                "/lorienNet/classes",
            ).rstrip("/")
            template = getattr(
                config,
                "GRAD_YEAR_CLASS_DIR_TEMPLATE",
                "class{gidNumber}",
            )
            class_dir = template.format(gidNumber=gid_number)
            home_directory = f"{base}/{class_dir}/{username}"

        logger.info(
            "graduation_year_group home result gid=%d home=%s",
            gid_number,
            home_directory,
        )
        logger.info(
            "Lorien compute_home_directory returning gid %d home %s", gid_number, home_directory
        )
        return gid_number, home_directory

    raise ValueError(f"Unknown HOME_STYLE: {home_style!r}")
