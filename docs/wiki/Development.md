# Development

How to set up a local development environment, run the linter and compiler checks, and contribute changes.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Local Development Setup](#2-local-development-setup)
3. [Running the App in Development Mode](#3-running-the-app-in-development-mode)
4. [Project Layout](#4-project-layout)
5. [Code Quality Checks](#5-code-quality-checks)
6. [CI Pipeline](#6-ci-pipeline)
7. [Adding New Features](#7-adding-new-features)
8. [Branch Model and Contributing](#8-branch-model-and-contributing)
9. [Module Overview](#9-module-overview)

---

## 1. Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Python | 3.9+ | 3.11 recommended |
| Git | Any recent version | |
| OpenLDAP server | 2.4+ | Real or mock LDAP for testing |
| pip | 21+ | Bundled with Python 3.9+ |

A real (or test) OpenLDAP instance is needed for end-to-end testing. The app has no built-in LDAP mock — use TEST MODE to avoid writing to a production server.

---

## 2. Local Development Setup

```bash
# Clone the repo
git clone https://github.com/ChrisMcGowanAu/ldap_admin_flask.git
cd ldap_admin_flask

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create a local config (fill in your LDAP details)
cp config_example.py config.py
nano config.py
```

Minimum `config.py` fields for development:

```python
SECRET_KEY         = "dev-only-not-for-production"
LDAP_HOST          = "localhost"          # or your test LDAP server
LDAP_PORT          = 389
LDAP_BIND_DN       = "cn=admin,dc=test,dc=local"
LDAP_BIND_PW       = "test-password"
LDAP_USER_BASE_DN  = "ou=people,dc=test,dc=local"
LDAP_GROUP_BASE_DN = "ou=groups,dc=test,dc=local"
```

---

## 3. Running the App in Development Mode

```bash
# Activate the venv if not already active
source venv/bin/activate

# Run Flask's built-in development server
flask run --debug
# or equivalently:
python3 app.py
```

The app will be available at `http://127.0.0.1:5000`.

Flask's `--debug` flag enables:
- **Hot reload** — the server restarts automatically when you save a Python file
- **Interactive debugger** — tracebacks shown in the browser (never use in production)
- **Verbose logging** — all requests printed to the terminal

> **Note:** `DEBUG = True` also disables some Flask security defaults. Never deploy with the development server or debug mode enabled.

### Using TEST MODE during development

After logging in, the session defaults to **TEST MODE**. All LDAP write operations (create user, delete user, change password, bulk import) are simulated and logged but not committed to LDAP. This is the safe mode for development and testing.

Switch to LIVE MODE only when you want to verify that a specific write actually works against your test LDAP server.

---

## 4. Project Layout

```
ldap_admin_flask/
├── app.py                  # Main Flask application — all routes (~1 900 lines)
├── audit.py                # Writes new-user CSV audit files
├── config_example.py       # Template config (copy to config.py and fill in)
├── config_school.py        # School-specific config template
├── home_paths.py           # compute_home_directory() — returns (gidNumber, path)
├── ldap_conn.py            # LDAP connection factory, ldap_test_bind()
├── ldap_core.py            # Central import hub (imports all ldap_*.py modules)
├── ldap_groups.py          # Group CRUD: create, delete, audit, membership
├── ldap_logging.py         # Logger setup (file + stream, with fallback)
├── ldap_lookup.py          # find_user_dn() — exact UID match
├── ldap_password.py        # hash_password_for_ldap(), ldap_change_password()
├── ldap_queries.py         # ldap_list_users_by_gid()
├── ldap_reports.py         # XLSX export (pure Python, no openpyxl)
├── ldap_users.py           # ldap_create_user(), ldap_search_users(), etc.
├── ldap_utils.py           # Wildcard import facade (from X import * for all ldap_*.py)
├── password_utils.py       # Kid and staff password generators (secrets module)
├── policy.py               # compute_email_for_uid() — uses config domains
├── provisioning.py         # Home directory creation, Zimbra script appending
├── version.py              # get_app_version() via git subprocess (cached)
│
├── templates/              # Jinja2 HTML templates (15 files)
│   ├── base.html           # Base layout — navbar, flash messages, session state
│   ├── login.html
│   ├── dashboard.html
│   ├── new_user.html
│   ├── bulk_import.html
│   ├── check_user.html
│   ├── change_password.html
│   ├── delete_user.html
│   ├── create_group.html
│   ├── delete_group.html
│   ├── group_audit.html
│   ├── group_users.html
│   ├── user_groups.html
│   ├── test_login.html
│   └── test_password.html
│
├── static/
│   └── password_gen.js     # Async button wiring for /api/generate_password
│
├── docs/
│   └── wiki/               # GitHub wiki source (markdown)
│
├── systemd/
│   └── ldap-admin.service.example
│
├── .github/
│   └── workflows/
│       └── python-app.yml  # CI: compileall + flake8
│
├── requirements.txt        # Unpinned dependencies
├── requirements.locked.txt # Pinned dependencies (for reproducible installs)
├── set-passhash.ldif       # LDIF to set olcPasswordHash on slapd
├── INSTALL.md              # Original installation guide
└── README.md               # Project overview
```

---

## 5. Code Quality Checks

### Byte-compile check (catches syntax errors)

```bash
python -m compileall -q .
```

Exits 0 if all `.py` files compile cleanly. This is the first CI step.

### Flake8 — critical errors only

```bash
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

Checks for:

| Code | Meaning |
|---|---|
| `E9xx` | Syntax errors, encoding errors, I/O errors |
| `F63x` | Invalid `assert` or `print` statements |
| `F7xx` | Syntax errors found by pyflakes |
| `F82x` | Undefined names |

These are the error classes that indicate the code will actually fail at runtime. The CI pipeline uses only this subset because the codebase has pre-existing style warnings (long lines, wildcard imports) that are accepted.

### Full flake8 (style + complexity)

To see all warnings:

```bash
flake8 . --max-line-length=120
```

Pre-existing warnings you will see:

- `F401` unused imports in `ldap_core.py` (intentional re-export hub)
- `F403` / `F405` wildcard imports in `ldap_utils.py` (intentional facade)
- `E501` long lines in `app.py` (SQL-style LDAP filter strings)

None of these prevent the app from running.

### Optional: ruff (faster linter)

```bash
pip install ruff
ruff check .
```

[ruff](https://docs.astral.sh/ruff/) is a modern, significantly faster Python linter that enforces a superset of flake8 rules. It is not yet part of the CI pipeline but is recommended for local development.

---

## 6. CI Pipeline

The GitHub Actions workflow (`.github/workflows/python-app.yml`) runs automatically on every push and pull request to `main`.

### Steps

1. **Checkout** the repository
2. **Set up Python 3.11**
3. **Install dependencies** from `requirements.txt`
4. **Byte-compile** all `.py` files: `python -m compileall -q .`
5. **Flake8** critical errors only: `flake8 . --count --select=E9,F63,F7,F82 ...`

The pipeline is intentionally minimal — it catches syntax errors and undefined names without blocking on style. If you want to add type-checking (`mypy`) or full style enforcement, add extra steps to `python-app.yml`.

### Viewing CI results

On GitHub, go to **Actions → python-app** to see the status of each run. Failed runs show the exact error output from `compileall` or `flake8`.

---

## 7. Adding New Features

### Adding a new route

1. Add the route function to `app.py`.
2. Create a template in `templates/` if a new page is needed.
3. If the route handles `POST` requests with a form, add the CSRF hidden field to the template:
   ```html
   <form method="POST" action="/your-route">
     <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
     ...
   </form>
   ```
   The `validate_csrf_token()` `before_request` hook will enforce this automatically.

### Adding a new LDAP operation

1. Add the function to the appropriate `ldap_*.py` module:
   - User operations → `ldap_users.py`
   - Group operations → `ldap_groups.py`
   - Password operations → `ldap_password.py`
   - General queries → `ldap_queries.py`

2. The function should accept a `connection` parameter (the ldap3 `Connection` object) rather than creating its own connection. See existing functions for the pattern.

3. Export the function via `ldap_utils.py` if it needs to be called from `app.py` (the wildcard facade imports everything from each `ldap_*.py` module).

4. Respect TEST MODE in the calling route:
   ```python
   if is_test_mode():
       flash(f"TEST MODE: would have done X", "warning")
   else:
       result = ldap_your_function(conn, ...)
   ```

### Adding a new config setting

1. Add the setting with a sensible default (or raise `RuntimeError` if it is required) in the relevant module.
2. Document it in `config_example.py`.
3. Add it to the [Configuration Reference](Configuration-Reference.md) wiki page.

### Adding a new template

All templates extend `base.html`:

```html
{% extends "base.html" %}
{% block title %}Your Page Title{% endblock %}
{% block content %}
  <!-- your content here -->
{% endblock %}
```

`base.html` provides:
- Bootstrap CSS/JS
- Navbar with TEST/LIVE mode indicator and logout button
- Flash message rendering
- `csrf_token()` in the template context

---

## 8. Branch Model and Contributing

### Branches

| Branch | Purpose |
|---|---|
| `main` | Stable, production-ready code |
| `genspark_ai_developer` | AI-assisted improvement work |
| Feature branches | Individual feature or fix development |

### Workflow for contributors

```bash
# Start from an up-to-date main
git checkout main
git pull origin main

# Create a feature branch
git checkout -b feature/your-feature-name

# Make changes, then check quality
python -m compileall -q .
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Commit
git add .
git commit -m "feat: describe your change"

# Push and open a pull request to main
git push origin feature/your-feature-name
```

### Pull request checklist

- [ ] `python -m compileall -q .` exits with 0 errors
- [ ] `flake8 --select=E9,F63,F7,F82` exits with 0 errors
- [ ] All new forms include the CSRF hidden field
- [ ] New LDAP write operations respect TEST MODE
- [ ] New `config.py` settings are documented in `config_example.py` and the wiki
- [ ] PR description explains what was changed and why

---

## 9. Module Overview

A quick reference to which module owns each responsibility:

| Responsibility | Module |
|---|---|
| All Flask routes and HTTP logic | `app.py` |
| LDAP connection / bind | `ldap_conn.py` |
| User CRUD | `ldap_users.py` |
| Group CRUD | `ldap_groups.py` |
| Password hashing and change | `ldap_password.py` |
| User-by-UID lookup | `ldap_lookup.py` |
| Bulk queries (list by GID) | `ldap_queries.py` |
| XLSX export | `ldap_reports.py` |
| Logger configuration | `ldap_logging.py` |
| Wildcard import facade | `ldap_utils.py` |
| Central hub (imports all ldap_*.py) | `ldap_core.py` |
| Password / username generators | `password_utils.py` |
| Email address policy | `policy.py` |
| Home directory path calculation | `home_paths.py` |
| Home directory creation, Zimbra scripts | `provisioning.py` |
| New-user audit CSV writing | `audit.py` |
| App version (git tag) | `version.py` |
| Configuration template | `config_example.py` |
