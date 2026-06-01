# LDAP Admin Flask — Wiki

**LDAP Admin Flask** is a web-based OpenLDAP administration tool built with Python and Flask.  
It was originally created for a school running OpenLDAP on Linux, where common admin tasks — creating student accounts, resetting passwords, managing class groups — needed to be safer and faster than one-off shell scripts.

---

## What it does

| Feature | Description |
|---|---|
| Create users | Single or bulk (CSV) user creation with auto-generated usernames and passwords |
| Edit users | Search by username fragment, update name, home directory, shell, and class/group |
| Change passwords | Single or bulk (CSV) password reset; kid-friendly or strong staff passwords |
| Manage groups | Add/remove users from supplementary `memberUid` groups, individually or via CSV |
| Group audit | Detect missing `posixGroup` objects and missing `memberUid` memberships |
| Export users | Download an XLSX workbook of all users grouped by primary `gidNumber` |
| Test password | Verify a user's LDAP bind credentials (useful for "my password doesn't work" calls) |
| Delete users/groups | Multi-select delete with TEST MODE preview |
| TEST / LIVE mode | All destructive operations can be previewed in TEST MODE before applying to real LDAP |

---

## Who it is for

- **School IT admins** managing OpenLDAP for student and staff accounts
- **Small-organisation sysadmins** who need a safer UI for day-to-day LDAP management
- **Anyone** who wants a simple web front-end for OpenLDAP without heavyweight IDM software

It is **not** a full Identity Management system. It is a focused admin tool for the most common day-to-day tasks.

---

## Wiki pages

| Page | Contents |
|---|---|
| [Installation](Installation) | System requirements, install steps, virtualenv, systemd service |
| [Configuration Reference](Configuration-Reference) | Every `config.py` setting explained |
| [User Guide](User-Guide) | How to use each feature of the web UI |
| [CSV Formats](CSV-Formats) | Column layouts for bulk import, password reset, and group membership CSVs |
| [Home Directory Styles](Home-Directory-Styles) | `classic_unix` vs `graduation_year_group` explained |
| [Class & Group Model](Class-and-Group-Model) | How classes, gidNumbers, and posixGroups relate |
| [Password Generation](Password-Generation) | Kid-friendly and staff password generators |
| [Audit & Export](Audit-and-Export) | New-user audit CSVs and XLSX export |
| [Security Notes](Security-Notes) | CSRF, rate limiting, HTTPS, bind account, and more |
| [Troubleshooting](Troubleshooting) | Common errors and how to fix them |
| [Development](Development) | Running locally, linting, contributing |

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/ChrisMcGowanAu/ldap_admin_flask.git /opt/ldap_admin_flask
cd /opt/ldap_admin_flask

# 2. Virtual environment
python3 -m venv venv
venv/bin/pip install -r requirements.locked.txt

# 3. Configure
cp config_example.py config.py
nano config.py          # set LDAP_SERVER_URI, LDAP_BIND_DN, LDAP_BIND_PASSWORD, etc.

# 4. Run (TEST MODE is on by default)
venv/bin/gunicorn --bind 127.0.0.1:5000 app:app
```

Then open `http://your-server:5000/` and log in with an LDAP admin account.

> **Always start in TEST MODE.** No changes are written to LDAP until you switch to LIVE MODE.

---

## Screenshots

| Dashboard | Check / Edit User |
|---|---|
| ![Dashboard](../screenshots/ldap_dashboard.png) | ![Edit user](../screenshots/ldap_user_edit.png) |

| Group Audit | Manage User Groups |
|---|---|
| ![Group audit](../screenshots/ldap_group_audit.png) | ![Manage groups](../screenshots/ldap_manage_groups.png) |

---

## Licence

GNU General Public License v3.0 — see [LICENSE](../../LICENSE).
