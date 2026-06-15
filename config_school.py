"""
Example configuration for the LDAP Admin Flask application.

Copy this file to config.py and edit it for your site.

Important:
- Do not commit your real config.py to Git.
- config.py may contain LDAP bind passwords, Flask secrets, internal paths,
  and site-specific policy choices.
- The public/default settings below favour a simple Classic Unix setup.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional


# -----------------------------------------------------------------------------
# Flask / application behaviour
# -----------------------------------------------------------------------------

# Generate a real secret for production, for example:
#   python3 - <<'PY'
#   import secrets
#   print(secrets.token_urlsafe(48))
#   PY
FLASK_SECRET_KEY = "change-me-generate-a-random-secret"

# Safe default for a new installation. In TEST_MODE the tool should preview
# changes without modifying LDAP.
TEST_MODE = True

LOG_FILE = "/var/log/ldap_admin_tool.log"

# Only these usernames may log into the admin UI. Leave empty only on a private
# test instance where every successful LDAP bind is allowed to administer users.
ADMIN_UID_ALLOWLIST = ["adminuser,admin"]


# -----------------------------------------------------------------------------
# LDAP connection / directory layout
# -----------------------------------------------------------------------------

LDAP_SERVER_URI = "ldap://ldap.example.org"
LDAP_BIND_DN = "cn=admin,dc=example,dc=org"
LDAP_BIND_PASSWORD = "change-me"

LDAP_USER_BASE_DN = "ou=people,dc=example,dc=org"
LDAP_GROUP_BASE_DN = "ou=groups,dc=example,dc=org"

# DN template used when creating new users.
#
# Many newer LDAP deployments prefer uid-based DNs, for example:
#   LDAP_USER_DN_TEMPLATE = "uid={uid},{base_dn}"
#
# Some older OpenLDAP deployments use full-name/CN based DNs, for example:
#   LDAP_USER_DN_TEMPLATE = "cn={cn},{base_dn}"
#
# Use the template matching your existing directory tree.
LDAP_USER_DN_TEMPLATE = "cn={cn},{base_dn}"

DEFAULT_LOGIN_SHELL = "/bin/bash"


# -----------------------------------------------------------------------------
# Numeric IDs / primary groups
# -----------------------------------------------------------------------------

# New uidNumber allocation starts at this value unless higher existing values
# are already present.
UID_BASE_NUMBER = 20000

# Staff primary group.
STAFF_GID_NUMBER = 500
STAFF_GROUP_CN = "staff"


# -----------------------------------------------------------------------------
# Home directory style
# -----------------------------------------------------------------------------
#
# HOME_STYLE controls how the app calculates LDAP homeDirectory values.
#
# classic_unix:
#   All users get:
#     /home/{username}
#
# graduation_year_group:
#   Useful for schools that organise student home directories by graduation
#   year, class group, or year group.
#
#   Staff:
#     {GRAD_YEAR_STAFF_HOME_BASE}/{username}
#
#   Students:
#     {GRAD_YEAR_CLASSES_HOME_BASE}/{GRAD_YEAR_CLASS_DIR_TEMPLATE}/{username}
#
#   Example:
#     /schoolNet/staff/teacher1
#     /schoolNet/classes/class2029/alices
#
# Valid values:
#   "classic_unix"
#   "graduation_year_group"
#
# For general use
# HOME_STYLE = "classic_unix"
# For Schools
HOME_STYLE = "graduation_year_group"

# Used when HOME_STYLE = "classic_unix".
CLASSIC_UNIX_HOME_BASE = "/home"

# Used when HOME_STYLE = "graduation_year_group".
GRAD_YEAR_STAFF_HOME_BASE = "/schoolNet/staff"
GRAD_YEAR_CLASSES_HOME_BASE = "/schoolNet/classes"
GRAD_YEAR_CLASS_DIR_TEMPLATE = "class{gidNumber}"

# Create home directories on the filesystem when creating users. This only works
# when the Flask/Gunicorn service account has suitable permissions, or when the
# path is mounted with permissions that allow creation.
CREATE_HOME_DIR = False
HOME_DIR_MODE = 0o700


# -----------------------------------------------------------------------------
# Class / graduation-year group options
# -----------------------------------------------------------------------------
#
# These options are shown in the New User and Check/Edit User screens.
# The key, e.g. "Class 12", is what forms submit as class_key.
# gidNumber becomes the user's primary gidNumber.
#
# For HOME_STYLE = "graduation_year_group", the gidNumber may also be used to
# create the class directory name, e.g. gidNumber 2029 -> class2029.
#
# The Staff option is handled separately by STAFF_GID_NUMBER and STAFF_GROUP_CN.

ACADEMIC_YEAR_START_MONTH = 1
MIN_CLASS = 7
MAX_CLASS = 12
DEFAULT_CLASS_OPTION = "Class 12"
CLASS_GROUP_CN_TEMPLATE = "class{gidNumber}"


def get_academic_year(today: Optional[datetime.date] = None) -> int:
    """Return the academic year used for graduation-year calculations."""
    if today is None:
        today = datetime.date.today()

    year = today.year
    if today.month < ACADEMIC_YEAR_START_MONTH:
        year -= 1
    return year


def generate_class_options(
    today: Optional[datetime.date] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Build the class/graduation-year mapping.

    Example when academic_year is 2026:
      Class 12 -> gidNumber 2026 -> home_subdir class2026
      Class 11 -> gidNumber 2027 -> home_subdir class2027
    """
    academic_year = get_academic_year(today=today)
    options: Dict[str, Dict[str, Any]] = {}

    for class_num in range(MAX_CLASS, MIN_CLASS - 1, -1):
        graduation_year = academic_year + (MAX_CLASS - class_num)
        key = f"Class {class_num}"
        options[key] = {
            "gidNumber": graduation_year,
            # Kept for older templates/reports and for display purposes.
            "home_subdir": f"class{graduation_year}",
            "description": f"Graduating class of {graduation_year}",
        }

    return options


CLASS_OPTIONS = generate_class_options()


# -----------------------------------------------------------------------------
# Generated/audit files
# -----------------------------------------------------------------------------
#
# The tool may generate CSV reports or account-creation audit files depending on
# which features you enable/use. These files can contain sensitive information.
# Keep output directories private, ideally root/admin-only.

NEW_USERS_AUDIT_DIR = "/var/lib/ldap_admin_flask/audit"

# Suggested permissions for directories containing generated password/account
# records, if your site uses those workflows:
#   directory: root-owned, mode 700
#   files:     root-owned, mode 600


# -----------------------------------------------------------------------------
# Optional Zimbra provisioning script output
# -----------------------------------------------------------------------------
#
# Leave these as None unless your site intentionally wants the app to append
# zmprov commands to script files. Such scripts may contain plaintext temporary
# passwords and must be stored in a protected directory.

ZIMBRA_STUDENT_SCRIPT = None
ZIMBRA_STAFF_SCRIPT = None
ZIMBRA_STUDENT_DOMAIN = "students.example.org"
ZIMBRA_STAFF_DOMAIN = "example.org"


# -----------------------------------------------------------------------------
# Public config hygiene notes
# -----------------------------------------------------------------------------
#
# Do not commit real values for:
#   FLASK_SECRET_KEY
#   LDAP_BIND_PASSWORD
#   site-specific private domains/paths if sensitive
#   generated CSV/script output containing passwords
