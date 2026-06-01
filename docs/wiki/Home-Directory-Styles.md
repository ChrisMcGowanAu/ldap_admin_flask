# Home Directory Styles

The `HOME_STYLE` setting in `config.py` controls how the app calculates the `homeDirectory` LDAP attribute when creating or editing users.

Two styles are supported:

---

## `classic_unix`

All users get a flat home directory under a single base path.

```
/home/{username}
```

**Configuration:**

```python
HOME_STYLE = "classic_unix"
CLASSIC_UNIX_HOME_BASE = "/home"
```

**Examples:**

| User | Class | homeDirectory |
|---|---|---|
| `alices` | Class 10 | `/home/alices` |
| `dlee` | Staff | `/home/dlee` |

This is the standard layout for a typical Linux server and suits small organisations or general-purpose Linux environments.

---

## `graduation_year_group`

Designed for schools that organise student home directories by graduation year (or class year). Staff get their own base path; students get a per-class subdirectory.

```
Staff:    {GRAD_YEAR_STAFF_HOME_BASE}/{username}
Students: {GRAD_YEAR_CLASSES_HOME_BASE}/{class_dir}/{username}
```

**Configuration:**

```python
HOME_STYLE = "graduation_year_group"
GRAD_YEAR_STAFF_HOME_BASE    = "/schoolNet/staff"
GRAD_YEAR_CLASSES_HOME_BASE  = "/schoolNet/classes"
GRAD_YEAR_CLASS_DIR_TEMPLATE = "class{gidNumber}"
```

**Examples (academic year 2026, MAX_CLASS=12):**

| User | Class | gidNumber | homeDirectory |
|---|---|---|---|
| `dlee` | Staff | 500 | `/schoolNet/staff/dlee` |
| `alices` | Class 12 | 2026 | `/schoolNet/classes/class2026/alices` |
| `bjones` | Class 11 | 2027 | `/schoolNet/classes/class2027/bjones` |
| `carol` | Class 7 | 2031 | `/schoolNet/classes/class2031/carol` |

This keeps student files naturally grouped by their graduation year, which makes it easy to archive or remove a whole cohort's data at end of year.

---

## How `gidNumber` relates to graduation year

In `graduation_year_group` mode, the `gidNumber` for each class is calculated as:

```
gidNumber = current_academic_year + (MAX_CLASS - class_number)
```

With `MAX_CLASS = 12` in academic year 2026:

| Class | gidNumber | Graduates |
|---|---|---|
| Class 12 | 2026 | This year |
| Class 11 | 2027 | Next year |
| Class 10 | 2028 | In 2 years |
| Class 9 | 2029 | In 3 years |
| Class 8 | 2030 | In 4 years |
| Class 7 | 2031 | In 5 years |

When a new academic year begins, `generate_class_options()` recalculates these automatically, so Class 12 always gets the current year's `gidNumber` and the mapping rolls forward by one.

> **Tip:** Because `gidNumber` is the graduation year, you can look at a student's `gidNumber` and immediately know when they are expected to graduate.

---

## Overriding the home directory on a per-user basis

When creating a user (single or bulk CSV), you can supply a `home` value explicitly. If it is longer than 4 characters, it takes precedence over the computed path. This lets you place a specific user in a non-standard location without changing the global `HOME_STYLE`.

---

## Creating home directories on the filesystem

The app can optionally `mkdir` home directories when creating users:

```python
CREATE_HOME_DIR = True
HOME_DIR_MODE   = 0o700
```

This only works if the gunicorn service account (`www-data`, or whoever runs the app) has write permission to the parent directory. For NFS-mounted school network drives this is usually not the case — in that case leave `CREATE_HOME_DIR = False` and create the directories via your existing provisioning scripts or file server tooling.
