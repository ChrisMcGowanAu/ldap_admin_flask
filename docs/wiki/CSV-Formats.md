# CSV Formats

The app accepts CSV files for three bulk operations. All formats share these traits:

- **Encoding:** UTF-8 or UTF-8-BOM (Excel default)
- **Delimiter:** comma `,`, semicolon `;`, or tab — auto-detected
- **Header row:** required; column names are matched **case-insensitively** with spaces and underscores ignored
- **Empty rows:** skipped automatically
- **Template downloads:** each upload page has a *Download template CSV* link

---

## Bulk Import CSV

Used on the **Bulk Import Users** page to create many user accounts at once.

### Columns

| Column | Aliases accepted | Required | Notes |
|---|---|---|---|
| `class` | `group`, `year`, `class_key` | Yes | Class name (e.g. `7`, `8`, `12`, `staff`) or the full key (e.g. `Class 12`) |
| `given_name` | `given`, `givenName`, `first_name`, `firstname`, `first` | Yes | Student/staff first name |
| `family_name` | `family`, `surname`, `sn`, `last_name`, `lastname`, `last` | Yes | Student/staff surname |
| `username` | `uid`, `user`, `login` | No | If blank, auto-generated as `{given}{initial_of_surname}` (e.g. `alices`) |
| `password` | `pass` | No | If blank, a [kid-friendly password](Password-Generation) is auto-generated |
| `full_name` | `cn`, `displayName`, `name` | No | If blank, defaults to `given_name family_name` |
| `home` | `home_dir`, `directory` | No | If blank, calculated from `HOME_STYLE` and class |

### Class field values

The `class` column accepts:
- A bare year number: `7`, `8`, `9`, `10`, `11`, `12`
- The full class key: `Class 7`, `Class 12`
- The word `staff` (case-insensitive) for staff accounts

### Example

```csv
class,given_name,family_name,username,password,full_name,home
7,Alice,Smith,,,, 
8,Bob,Jones,bjones,Welcome1?,Bob Jones,
12,Carol,Brown,,,Carol Brown,
staff,Dave,Lee,dlee,P@ssw0rd!,,
```

> **Tip:** Leave `username` and `password` blank to let the app generate them. The results table after import shows what was assigned.

---

## Password Reset CSV

Used on the **Change Password** page to reset many passwords at once.

### Columns

| Column | Required | Notes |
|---|---|---|
| `Username` | Yes | Must exactly match an existing LDAP `uid` |
| `Password` | Yes | The new password to set |

### Example

```csv
Username,Password
alices,HappyKoala42?
bjones,QuickRiver17?
dlee,Xk9@mP2r-vQs7w
```

> Only these two columns are used. Any extra columns (e.g. `Full Name`, `Class`) are silently ignored, so you can use a broader spreadsheet and add the required columns.

---

## Group Membership CSV

Used on the **Manage User Groups** page to add many users to a supplementary group at once.

### Columns

| Column | Aliases accepted | Required | Notes |
|---|---|---|---|
| `username` | `uid`, `user`, `login` | Yes | Must match an existing LDAP `uid` |
| `gid` | `gidNumber`, `group_gid` | One of these | Numeric `gidNumber` of the target group |
| `group` | `group_name`, `cn`, `group_cn` | One of these | Exact `cn` of the target group |

You only need **one** of `gid` or `group` — both can be present but `gid` takes precedence.

### Example — by numeric gidNumber

```csv
username,gid,notes
alices,601,Add to science-tools group
bjones,601,
carol,602,Add to art-room group
```

### Example — by group cn

```csv
username,group
alices,science-tools
bjones,science-tools
carol,art-room
```

### Example — mixed

```csv
username,gid,group,notes
alices,601,,Numeric preferred
bjones,,science-tools,Name fallback
```

> **Exact match required:** Group `cn` lookups require an exact, case-insensitive match. Partial names are not accepted in the CSV to avoid accidentally adding users to the wrong group. Use the numeric `gidNumber` if you are unsure.

---

## Tips for preparing CSVs in Excel / LibreOffice

- **Save as CSV UTF-8** (not the default Windows ANSI encoding), or let the app handle the UTF-8-BOM that Excel adds.
- **Do not use merged cells** or formatting rows — the first row must be the header.
- **Verify class names** match exactly what your `CLASS_OPTIONS` keys are (e.g. `Class 12`, not `Year 12`, unless you have customised `CLASS_OPTIONS`).
- For large imports, **test in TEST MODE** first and check the results table for any `Skipped` or `FAIL` rows before switching to LIVE MODE.
