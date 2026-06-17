#!/usr/bin/env bash
set -e
# cd /opt/ldap_admin_flask
venv/bin/python3 -c "import ldap_utils; print('ldap_utils import: OK')"
venv/bin/python3 -c "import ldap_users, ldap_groups, ldap_core; print('modules import: OK')"

