# Troubleshooting

Common errors and how to fix them.

---

## Table of Contents

1. [App Won't Start](#1-app-wont-start)
2. [LDAP Connection Failures](#2-ldap-connection-failures)
3. [Login Errors](#3-login-errors)
4. [CSRF / Security Token Errors](#4-csrf--security-token-errors)
5. [Rate Limit — 429 Too Many Requests](#5-rate-limit--429-too-many-requests)
6. [User Operations](#6-user-operations)
7. [Group Operations](#7-group-operations)
8. [Bulk Import Issues](#8-bulk-import-issues)
9. [Audit / Export Issues](#9-audit--export-issues)
10. [Viewing Logs](#10-viewing-logs)

---

## 1. App Won't Start

### `ModuleNotFoundError: No module named 'config'`

The application cannot find `config.py`.

**Fix:** Copy the example config and fill in your values:

```bash
cd /opt/ldap-admin
cp config_example.py config.py
nano config.py
```

See [Configuration Reference](Configuration-Reference.md) for all required settings.

---

### `ModuleNotFoundError: No module named 'flask'` (or any other package)

The virtual environment is not activated, or dependencies were not installed.

**Fix:**

```bash
cd /opt/ldap-admin
source venv/bin/activate
pip install -r requirements.txt
```

If running via systemd, verify the `ExecStart` path points to the venv's gunicorn:

```ini
ExecStart=/opt/ldap-admin/venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 app:app
```

---

### `RuntimeError: LDAP_GROUP_BASE_DN is not set in config`

`config.py` is missing required LDAP base DN settings.

**Fix:** Add the missing values:

```python
LDAP_USER_BASE_DN  = "ou=people,dc=school,dc=internal"
LDAP_GROUP_BASE_DN = "ou=groups,dc=school,dc=internal"
```

---

### `SECRET_KEY` warning in logs

Flask will print a warning if `SECRET_KEY` is not set. Sessions will not work reliably.

**Fix:** Set a strong random key in `config.py`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output into `config.py`:

```python
SECRET_KEY = "paste-output-here"
```

---

## 2. LDAP Connection Failures

### `LDAPSocketOpenError` / `Connection refused`

The app cannot reach the LDAP server.

**Diagnosis:**

```bash
# Test TCP connectivity to the LDAP server
nc -zv <LDAP_HOST> 389

# Or for LDAPS (TLS)
nc -zv <LDAP_HOST> 636
```

**Common causes:**

| Cause | Fix |
|---|---|
| Wrong `LDAP_HOST` in `config.py` | Verify hostname / IP resolves and is reachable |
| slapd not running | `sudo systemctl status slapd` and `sudo systemctl start slapd` |
| Firewall blocking port 389/636 | Open the port: `sudo ufw allow 389/tcp` |
| Wrong port | Set `LDAP_PORT = 636` and `LDAP_USE_SSL = True` for LDAPS |

---

### `LDAPInvalidCredentialsResult` on startup or any LDAP operation

The bind DN or bind password in `config.py` is incorrect.

**Diagnosis:**

```bash
ldapsearch -H ldap://<LDAP_HOST> \
  -D "cn=admin,dc=school,dc=internal" \
  -w "your-bind-password" \
  -b "dc=school,dc=internal" "(objectClass=*)" dn
```

If this fails with "Invalid credentials", the bind DN or password is wrong. Update `config.py`:

```python
LDAP_BIND_DN = "cn=admin,dc=school,dc=internal"
LDAP_BIND_PW = "correct-password"
```

---

### `LDAPNoSuchObjectResult` when searching users or groups

The base DN does not exist in LDAP.

**Diagnosis:**

```bash
# List the top-level of your LDAP tree
ldapsearch -H ldap://<LDAP_HOST> -D "<bind_dn>" -w "<password>" \
  -b "dc=school,dc=internal" -s one "(objectClass=*)" dn
```

**Fix:** Ensure `LDAP_USER_BASE_DN` and `LDAP_GROUP_BASE_DN` match the actual tree structure. Create the OUs if missing:

```ldif
dn: ou=people,dc=school,dc=internal
objectClass: organizationalUnit
ou: people

dn: ou=groups,dc=school,dc=internal
objectClass: organizationalUnit
ou: groups
```

```bash
ldapadd -H ldap://<LDAP_HOST> -D "<bind_dn>" -w "<password>" -f create_ous.ldif
```

---

### LDAPS certificate errors

If `LDAP_USE_SSL = True` and the server uses a self-signed certificate:

```
LDAPSSLConfigurationError: ... certificate verify failed
```

**Fix (development only):** Disable cert verification in `config.py`:

```python
LDAP_TLS_VALIDATE = False
```

**Fix (production):** Install the CA certificate on the app server:

```bash
sudo cp school-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

Then set `LDAP_TLS_VALIDATE = True` (or remove the setting — `True` is the default).

---

## 3. Login Errors

### "Invalid credentials" with correct password

Possible causes:

1. **Wrong bind DN format.** The login route constructs the user DN as:
   ```
   uid=<username>,<LDAP_USER_BASE_DN>
   ```
   Verify this matches your LDAP structure with `ldapsearch`.

2. **Account does not exist** in `LDAP_USER_BASE_DN`. Search for the user:
   ```bash
   ldapsearch -H ldap://<host> -D "<bind_dn>" -w "<pw>" \
     -b "<LDAP_USER_BASE_DN>" "(uid=<username>)" dn
   ```

3. **`ADMIN_UID_ALLOWLIST` is blocking the user.** If the allowlist is set, only listed UIDs can log in:
   ```python
   ADMIN_UID_ALLOWLIST = ["jsmith"]   # only jsmith can log in
   ```
   Add the UID to the list or leave `ADMIN_UID_ALLOWLIST = []` to allow all valid LDAP users.

---

### Redirected back to login immediately after entering credentials

The session is not persisting. Most likely cause: `SECRET_KEY` is missing or changes between restarts (which invalidates existing sessions).

**Fix:** Set a static `SECRET_KEY` in `config.py` (see above).

---

## 4. CSRF / Security Token Errors

### "Invalid or missing security token. Please try again."

This message appears when a `POST` request arrives without a valid CSRF token.

**Common causes:**

| Cause | Fix |
|---|---|
| Session expired (idle timeout) | Log in again; the new session will have a fresh token |
| Back/forward browser cache replaying an old form | Re-submit the form from the current page |
| Direct `curl` / API call to a form endpoint | Use the web UI, or add proper CSRF token handling |
| Form in a template missing the hidden field | See [developer notes](#csrf-field-missing-from-a-custom-template) below |

### CSRF field missing from a custom template

If you have added a new `<form>` to a template and forgotten the CSRF field:

```html
<form method="POST" action="/your-route">
  <!-- ADD THIS LINE: -->
  <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
  ...
</form>
```

The `csrf_token()` helper is injected into the Jinja2 context by the `inject_globals()` context processor in `app.py`.

---

## 5. Rate Limit — 429 Too Many Requests

### "Too Many Requests" on the login page

The login rate limiter (10 POST requests per minute per IP) has been triggered.

**For administrators testing the system:**

Wait 60 seconds for the counter to reset, then try again.

**If legitimate users are being blocked:**

This most commonly happens if nginx is not forwarding the real client IP, causing all users to appear as the same IP (`127.0.0.1`). Check your nginx config:

```nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Real-IP       $remote_addr;
```

And ensure flask-limiter is configured to trust the proxy headers. See [Security Notes — Rate Limiting](Security-Notes.md#2-login-rate-limiting).

**Temporarily disabling the rate limiter (not recommended for production):**

Comment out the decorator in `app.py`:

```python
@app.route("/login", methods=["GET", "POST"])
# @limiter.limit("10 per minute", methods=["POST"])   # temporarily disabled
def login():
```

---

## 6. User Operations

### Create User — "UID already exists"

A `posixAccount` with that `uid` already exists in `LDAP_USER_BASE_DN`.

**Fix:** Search for the existing account from the dashboard and confirm whether it should be reused or the new UID renamed.

---

### Create User — uidNumber / gidNumber conflicts

If the auto-assigned `uidNumber` conflicts with an existing entry, LDAP will return an error.

**Fix:** Set `UID_MIN` and `UID_MAX` in `config.py` to a range that does not overlap with existing accounts, or manually specify the UID when creating the user.

---

### Change Password — operation succeeds in TEST MODE but not LIVE MODE

TEST MODE simulates LDAP writes without committing them. To actually change the password, switch to LIVE MODE on the dashboard.

---

### Delete User — "Entry not found"

The user may have already been deleted, or the UID was mis-typed.

**Fix:** Use Check User to confirm the account exists before attempting to delete.

---

## 7. Group Operations

### Group Audit — "No posixGroup entries found"

The group base DN may be wrong, or groups use a different `objectClass`.

**Diagnosis:**

```bash
ldapsearch -H ldap://<host> -D "<bind_dn>" -w "<pw>" \
  -b "<LDAP_GROUP_BASE_DN>" "(objectClass=posixGroup)" cn gidNumber
```

If this returns no results, verify that your LDAP directory actually uses `posixGroup` and that `LDAP_GROUP_BASE_DN` is correct.

---

### "Cannot delete group — members still assigned"

The application will warn if a group still has `memberUid` entries. Removing a primary group from users first is the safe approach — use Group Audit to identify members, then remove them or reassign their primary GID.

---

## 8. Bulk Import Issues

### CSV not recognised / no data imported

**Diagnosis checklist:**

- [ ] Is the file UTF-8 or UTF-8-with-BOM? (BOM is handled automatically)
- [ ] Is the delimiter comma or semicolon? (Both are auto-detected)
- [ ] Does the header row use a recognised column name?

Recognised column aliases for each field are listed in [CSV Formats](CSV-Formats.md). Column names are case-insensitive and spaces/underscores are interchangeable.

---

### Some rows imported, some skipped

Rows are skipped if:

- A required field (`firstname` or `surname`) is blank
- The UID derived from the name already exists in LDAP (duplicate check)
- The `gidNumber` / class does not map to a known group

Check the flash messages after import — each skipped row is reported with a reason.

---

### Bulk import succeeded in TEST MODE — how do I run it for real?

Switch to LIVE MODE (dashboard → toggle mode button), then re-upload the same CSV. The import will re-validate each row and commit to LDAP.

---

### `UnicodeDecodeError` when uploading CSV

The file was saved in a non-UTF-8 encoding (e.g. Windows-1252 / Latin-1 from older Excel versions).

**Fix:** Open the file in Excel, choose **Save As → CSV UTF-8 (Comma delimited) (.csv)**. Or convert with Python:

```bash
python3 -c "
open('fixed.csv','w',encoding='utf-8').write(
  open('original.csv', encoding='cp1252').read()
)"
```

---

## 9. Audit / Export Issues

### Audit CSV not created after bulk import

**Check 1:** The session must be in LIVE MODE. TEST MODE logs operations but does not write audit files.

**Check 2:** `NEW_USERS_AUDIT_DIR` in `config.py` must exist and be writable by the gunicorn service user:

```bash
ls -la /var/ldap-audit           # should exist
sudo chown ldap-admin:ldap-admin /var/ldap-audit
sudo chmod 750 /var/ldap-audit
```

**Check 3:** The journalctl log will show the exact error if the write fails (see [Viewing Logs](#10-viewing-logs)).

---

### XLSX export is empty or missing columns

The XLSX exporter queries LDAP at export time. If the LDAP search returns no results, the spreadsheet will be empty. Verify that users exist in `LDAP_USER_BASE_DN` and that the bind account has read access.

---

## 10. Viewing Logs

### Application log (gunicorn / journalctl)

```bash
# If running as a systemd service named ldap-admin:
sudo journalctl -u ldap-admin -f           # live tail
sudo journalctl -u ldap-admin --since today  # today's entries
sudo journalctl -u ldap-admin -n 100       # last 100 lines
```

### Application log file

If `LOG_FILE` is set in `config.py`:

```bash
tail -f /var/log/ldap-admin/app.log
```

### nginx access and error logs

```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### slapd logs

```bash
# Enable logging in /etc/ldap/slapd.conf or cn=config, then:
sudo journalctl -u slapd -f
```

### Common log message patterns

| Log message | Meaning |
|---|---|
| `LDAP operation in TEST MODE` | Write was simulated, not committed |
| `LDAP create_user: success` | User created in LIVE MODE |
| `CSRF token mismatch` | Suspicious POST — possible CSRF attempt or expired session |
| `Rate limit exceeded on /login` | Login rate limiter triggered for an IP |
| `RuntimeError: LDAP_GROUP_BASE_DN is not set` | Missing config value — app will return 500 |
