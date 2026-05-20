# ldap_logging.py
import logging

import config

logger = logging.getLogger("ldap_admin")
logger.setLevel(logging.INFO)

if not logger.handlers:
    try:
        h = logging.FileHandler(config.LOG_FILE)
    except Exception:
        h = logging.StreamHandler()

    fmt = logging.Formatter("%(filename)s %(lineno)d [%(levelname)s] %(name)s: %(message)s")
    h.setFormatter(fmt)
    logger.addHandler(h)
