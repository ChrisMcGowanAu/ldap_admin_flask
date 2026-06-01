# Configuration Reference

All configuration lives in `config.py` in the project root.  
This file is **not** tracked by git. Create it from one of the examples:

```bash
cp config_example.py config.py   # generic / small-organisation
cp config_school.py  config.py   # school with graduation-year home directories
```

---

## Flask / application

| Setting | Type | Default | Description |
|---|---|---|---|
| `FLASK_SECRET_KEY` | `str` | *(must set)* | Random secret used to sign session cookies. Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `TEST_MODE` | `bool` | `True` | Global default. When `True`, all write operations are simulated and not committed to LDAP. Can be toggled per browser session from the UI. |
| `LOG_FILE` | `str` | `"/var/log/ldap_admin_tool.log"` | Path for the application log file. The service account must have write access. |
| `ADMIN_UID_ALLOWLIST` | `list[str]` | `["adminuser"]` | Only LDAP users in this list can log into the admin UI. Set to `[]` only for private test instances. |

---

## LDAP connection

| Setting | Type | Example | Description |
|---|---|---|---|
| `LDAP_SERVER_URI` | `str` | `"ldap://192.168.1.10"` | URI of your OpenLDAP server. Use `ldaps://` for TLS. |
| `LDAP_BIND_DN` | `str` | `"cn=admin,dc=school,dc=local"` | DN of the service account used by the app to connect. |
| `LDAP_BIND_PASSWORD` | `str` | `"secret"` | Password for `LDAP_BIND_DN`. Keep this out of version control. |
| `LDAP_USER_BASE_DN` | `str` | `"ou=people,dc=school,dc=local"` | Base DN for user searches and creation. |
| `LDAP_GROUP_BASE_DN` | `str` | `"ou=groups,dc=school,dc=local"` | Base DN for group searches and creation. |
| `LDAP_USER_DN_TEMPLATE` | `str` | `"cn={cn},{base_dn}"` | Template for new user DNs. Use `"uid={uid},{base_dn}"` for uid-based DNs or `"cn={cn},{base_dn}"` for CN-based. Match your existing directory convention. |
| `DEFAULT_LOGIN_SHELL` | `str` | `"/bin/bash"` | Default `loginShell` attribute set on new users. |

---

## Numeric IDs and primary groups

| Setting | Type | Default | Description |
|---|---|---|---|
| `UID_BASE_NUMBER` | `int` | `20000` | `uidNumber` for new users starts here (or at max-existing + 1, whichever is higher). |
| `STAFF_GID_NUMBER` | `int` | `500` | Primary `gidNumber` assigned to staff accounts. |
| `STAFF_GROUP_CN` | `str` | `"staff"` | `cn` of the staff `posixGroup`. This group **must already exist** — it is never auto-created. |

---

## Home directory style

`HOME_STYLE` controls how `homeDirectory` is calculated for new users.

| Value | Who it suits | Path example |
|---|---|---|
| `"classic_unix"` | General Linux servers | `/home/alice` |
| `"graduation_year_group"` | Schools with per-class directories | `/schoolNet/classes/class2029/alice` |

### Settings for `classic_unix`

| Setting | Default | Description |
|---|---|---|
| `CLASSIC_UNIX_HOME_BASE` | `"/home"` | All users get `{base}/{username}`. |

### Settings for `graduation_year_group`

| Setting | Default | Description |
|---|---|---|
| `GRAD_YEAR_STAFF_HOME_BASE` | `"/schoolNet/staff"` | Staff home path: `{base}/{username}`. |
| `GRAD_YEAR_CLASSES_HOME_BASE` | `"/schoolNet/classes"` | Root of class directories. |
| `GRAD_YEAR_CLASS_DIR_TEMPLATE` | `"class{gidNumber}"` | Subdirectory name template. e.g. gidNumber 2029 → `class2029`. |

### Home directory creation

| Setting | Default | Description |
|---|---|---|
| `CREATE_HOME_DIR` | `False` | If `True`, the app will `mkdir` the home path on the server filesystem. Only works if the service account has write access to the parent directory. |
| `HOME_DIR_MODE` | `0o700` | Permissions applied to new home directories. |

---

## Class / graduation-year groups

These settings power the **class dropdown** on the Create User and Check/Edit User screens.

| Setting | Default | Description |
|---|---|---|
| `ACADEMIC_YEAR_START_MONTH` | `1` (January) | Month the academic year begins. Used to calculate graduation years. |
| `MIN_CLASS` | `7` | Lowest class year to include in the dropdown. |
| `MAX_CLASS` | `12` | Highest class year to include in the dropdown. |
| `DEFAULT_CLASS_OPTION` | `"Class 12"` | Which class is pre-selected in the dropdown. |
| `CLASS_GROUP_CN_TEMPLATE` | `"class{gidNumber}"` | Template for class `posixGroup` `cn` values. |
| `CLASS_OPTIONS` | *(generated)* | Dict built automatically by `generate_class_options()`. Maps `"Class 12"` etc. to `gidNumber` and `home_subdir`. You can override this entirely with a static dict if needed. |

The `gidNumber` for each class is calculated as:

```
gidNumber = academic_year + (MAX_CLASS - class_number)
```

For example, in 2026 with `MAX_CLASS=12`:
- Class 12 → gidNumber **2026**
- Class 11 → gidNumber **2027**
- Class 7  → gidNumber **2031**

---

## Audit / generated files

| Setting | Default | Description |
|---|---|---|
| `NEW_USERS_AUDIT_DIR` | `"/var/lib/ldap_admin_flask/audit"` | Directory where new-user audit CSVs are written. Must be writable by the service account. See [Audit & Export](Audit-and-Export). |

---

## Optional: Zimbra / email provisioning

Leave these as `None` unless your site uses Zimbra (or a compatible mail system).

| Setting | Default | Description |
|---|---|---|
| `ZIMBRA_STUDENT_SCRIPT` | `None` | Path to a shell script where `zmprov ca` commands for student accounts will be appended. |
| `ZIMBRA_STAFF_SCRIPT` | `None` | Same for staff accounts. |
| `ZIMBRA_STUDENT_DOMAIN` | `"students.example.org"` | Email domain for student accounts (used in audit CSVs and provisioning scripts). |
| `ZIMBRA_STAFF_DOMAIN` | `"example.org"` | Email domain for staff accounts. |

> **Warning:** Zimbra script files contain plaintext passwords. Store them in a root-owned, mode-0700 directory and delete them after use.

---

## Generating `CLASS_OPTIONS` manually

If your school doesn't use a simple 7–12 year range, you can replace the auto-generated `CLASS_OPTIONS` with a hand-crafted dict:

```python
CLASS_OPTIONS = {
    "Year 7":  {"gidNumber": 2031, "home_subdir": "class2031", "description": "Year 7 students"},
    "Year 8":  {"gidNumber": 2030, "home_subdir": "class2030", "description": "Year 8 students"},
    # ...
    "Year 12": {"gidNumber": 2026, "home_subdir": "class2026", "description": "Year 12 students"},
}
DEFAULT_CLASS_OPTION = "Year 12"
```
