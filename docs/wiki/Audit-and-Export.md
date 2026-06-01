# Audit and Export

The app produces two types of output files: **new-user audit CSVs** and an **XLSX user export**.

---

## New-user audit CSV

Every time a user is created in **LIVE MODE**, a record is appended to a CSV file in `NEW_USERS_AUDIT_DIR`.

### File naming

| User type | Filename |
|---|---|
| Staff | `ldap_new_users_staff.csv` |
| Students (gidNumber 2026) | `ldap_new_users_students_2026.csv` |
| Students (gidNumber 2027) | `ldap_new_users_students_2027.csv` |

One file per class cohort — at end of year you get a neat per-class record of all accounts created.

### Columns

| Column | Description |
|---|---|
| Timestamp | ISO 8601 datetime of when the account was created |
| Admin | uid of the admin who performed the creation |
| Class | Class key (e.g. `Class 12`) |
| First | `givenName` |
| Last | `sn` |
| Username | LDAP `uid` |
| Password | **Plaintext** temporary password assigned at creation |
| Email | Derived from `ZIMBRA_STAFF_DOMAIN` / `ZIMBRA_STUDENT_DOMAIN` |
| FullName | `givenName sn` |

### Security

These files contain plaintext passwords. Protect them:

```bash
sudo mkdir -p /var/lib/ldap_admin_flask/audit
sudo chown root:root /var/lib/ldap_admin_flask/audit
sudo chmod 700       /var/lib/ldap_admin_flask/audit
```

The gunicorn service account (`www-data`) needs write access:

```bash
sudo chown www-data:root /var/lib/ldap_admin_flask/audit
sudo chmod 750           /var/lib/ldap_admin_flask/audit
```

**Delete or archive CSV files after passwords have been distributed** and students have changed them.

### Use cases

- Print per-class CSV to give students their login details on paper
- Import into a student information system
- Provide to teachers for their records
- Keep as an audit trail of who created which account

---

## XLSX user export

**Path:** Dashboard → *Export Users*  
**URL:** `GET /export/users_by_primary_group.xlsx`

Downloads an Excel workbook with a snapshot of all LDAP users.

### Workbook structure

| Sheet | Contents |
|---|---|
| All Users | Every user, sorted by `uid` |
| `2026_class2026` | Users whose primary `gidNumber` is 2026 |
| `2027_class2027` | Users whose primary `gidNumber` is 2027 |
| `500_staff` | Staff users |
| `MISSING_gid_999` | Users with a `gidNumber` that has no matching `posixGroup` |

One sheet per group that has at least one user. Groups with no users are not included.

### Columns

| Column | Description |
|---|---|
| uid | LDAP username |
| cn | Full name |
| givenName | First name |
| sn | Surname |
| gidNumber | Primary group ID |
| primaryGroup | `cn` of the primary `posixGroup` (or an error description) |
| primaryGroupStatus | `OK`, `Missing primary group object`, `Duplicate gidNumber objects`, `Invalid/missing primary gidNumber` |
| secondaryGroups | Semicolon-separated list of supplementary group `cn` values |
| homeDirectory | LDAP `homeDirectory` attribute |
| loginShell | LDAP `loginShell` attribute |
| dn | Full LDAP DN |

### Use cases

- Annual account audit — verify every student is in the right class group
- Cross-check against a student information system or enrolment database
- Hand a per-class tab to the IT support team or school administration
- Identify accounts with missing or incorrect group membership before doing cleanup

### Notes

- The export is generated live from LDAP each time — it is always current.
- The XLSX is built without third-party libraries (pure Python + zipfile + XML) so there are no extra dependencies.
- Row 1 of each sheet is a bold header with freeze-pane and autofilter applied.
- The filename includes a timestamp: `ldap_users_by_primary_group_20260601_1430.xlsx`

---

## Zimbra provisioning scripts (optional)

If `ZIMBRA_STUDENT_SCRIPT` and `ZIMBRA_STAFF_SCRIPT` are set in `config.py`, the app appends a `zmprov ca` command to the relevant script file each time a user is created in LIVE MODE.

```bash
# Example line appended to the script
zmprov ca 'alices@students.school.edu' 'HappyKoala42?' displayName 'Alice Smith' givenName 'Alice' sn 'Smith' # created_by=dlee
```

These scripts are ready to run against a Zimbra server to provision matching email accounts.

**Protect script files the same way as audit CSVs** — they contain plaintext passwords.
