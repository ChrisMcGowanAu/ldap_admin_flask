# Security Notes

This page describes the security controls built into LDAP Admin Flask, their limitations, and recommendations for hardening a production deployment.

---

## Table of Contents

1. [CSRF Protection](#1-csrf-protection)
2. [Login Rate Limiting](#2-login-rate-limiting)
3. [HTTPS / TLS](#3-https--tls)
4. [Admin Allow-List](#4-admin-allow-list)
5. [LDAP Bind Account](#5-ldap-bind-account)
6. [Password Hashing (SHA-1 / SSHA)](#6-password-hashing-sha-1--ssha)
7. [Audit File Permissions](#7-audit-file-permissions)
8. [Session Security](#8-session-security)
9. [TEST MODE as a Safety Net](#9-test-mode-as-a-safety-net)
10. [Summary Checklist](#10-summary-checklist)

---

## 1. CSRF Protection

### What it does

Every HTML form in the application includes a hidden field containing a per-session token:

```html
<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
```

Before any `POST` request is processed, `app.py` validates that the token in the submitted form matches the token stored in the server-side session:

```python
@app.before_request
def validate_csrf_token():
    if request.method != "POST":
        return
    if request.path.startswith("/api/"):
        return          # JSON API endpoints use token auth, not sessions
    token_in_session = session.get("_csrf_token")
    token_in_form    = request.form.get("_csrf_token")
    if not token_in_session or not token_in_form:
        flash("Invalid or missing security token. Please try again.", "danger")
        return redirect(request.referrer or url_for("login"))
    if not secrets.compare_digest(token_in_session, token_in_form):
        flash("Security token mismatch. Please try again.", "danger")
        return redirect(request.referrer or url_for("login"))
```

Key properties:

| Property | Detail |
|---|---|
| Token length | 32 bytes, URL-safe base64 (`secrets.token_urlsafe(32)`) |
| Token scope | Per-session (regenerated on each login) |
| Comparison | `secrets.compare_digest()` — constant-time, resists timing attacks |
| Coverage | All `POST` routes except `/api/*` |

### Why `/api/*` is exempt

The password-generation API (`/api/generate_password`) is called by JavaScript from the same page and returns only a suggested password string — it performs no state changes. It does not require a CSRF token.

If you add new API endpoints that **do** modify state (e.g. a REST endpoint for bulk imports), ensure they require authentication and consider adding an `X-CSRF-Token` header check.

---

## 2. Login Rate Limiting

### What it does

`flask-limiter` applies a rate limit to the `/login` `POST` endpoint:

```python
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    ...
```

- **Limit:** 10 POST requests per minute, per IP address
- **Storage:** In-process memory (`storage_uri="memory://"`)
- **Response on breach:** HTTP 429 Too Many Requests

### Limitations

| Limitation | Detail |
|---|---|
| Memory storage | Limits are lost if gunicorn restarts or if you run multiple workers. For multi-worker deployments, switch to Redis storage (see below). |
| IP spoofing | The limit keys on the IP reported by the WSGI server. If nginx is reverse-proxying, configure `TRUSTED_PROXIES` in the limiter config so the real client IP is used. |
| Distributed attack | A botnet can still exceed 10/minute across many IPs. The limiter is a deterrent, not a complete brute-force prevention system. |

### Upgrading to Redis storage (multi-worker)

```python
# requirements.txt — add:
#   flask-limiter[redis]>=3.5
#   redis>=5.0

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="redis://localhost:6379/0",
)
```

### Configuring nginx to forward real IP

```nginx
# /etc/nginx/sites-available/ldap-admin
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Real-IP       $remote_addr;
```

Then in `app.py`, initialise the limiter with:

```python
from flask_limiter.util import get_remote_address
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
)
```

Flask-Limiter respects `X-Forwarded-For` headers when the app is configured with `TRUSTED_PROXIES`.

---

## 3. HTTPS / TLS

**The application does not serve HTTPS itself.** All TLS must be terminated at the nginx reverse proxy.

### Minimum nginx TLS configuration

```nginx
server {
    listen 443 ssl;
    server_name ldap-admin.school.internal;

    ssl_certificate     /etc/letsencrypt/live/ldap-admin.school.internal/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ldap-admin.school.internal/privkey.pem;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name ldap-admin.school.internal;
    return 301 https://$host$request_uri;
}
```

### Why HTTPS matters for this app

- Login credentials travel over the network.
- Session cookies (which hold the CSRF token) are sent with every request.
- LDAP query results include staff/student personal information.

Even on an internal school network, HTTPS is strongly recommended.

---

## 4. Admin Allow-List

`config.py` can restrict which LDAP UIDs are allowed to log in to the admin tool:

```python
ADMIN_UID_ALLOWLIST = ["jsmith", "admin", "it_helpdesk"]
```

If `ADMIN_UID_ALLOWLIST` is set and non-empty, the login route rejects any UID not in the list, even if their LDAP password is correct. This prevents a compromised student or staff account from accessing the admin interface.

**Recommendation:** Set `ADMIN_UID_ALLOWLIST` to the smallest possible set of UIDs — ideally just the IT administrator accounts.

If the setting is absent or an empty list, all successful LDAP binds are accepted (useful during initial setup but should not be the production state).

---

## 5. LDAP Bind Account

### Service bind account

The application binds to LDAP using a dedicated service account (configured in `config.py`):

```python
LDAP_BIND_DN = "cn=admin,dc=school,dc=internal"
LDAP_BIND_PW = "service-account-password"
```

**Recommendations:**

1. **Use a dedicated read/write account** — not the LDAP root DN (`cn=admin,...`). Create a service account with only the permissions the app needs:
   - Read all `posixAccount` and `posixGroup` entries
   - Write `userPassword`, `cn`, `sn`, `mail`, `homeDirectory`, `uidNumber`, `gidNumber`
   - Create/delete entries under `LDAP_USER_BASE_DN` and `LDAP_GROUP_BASE_DN`

2. **Restrict the bind account's access** with an OpenLDAP ACL:
   ```ldif
   # Example ACL — restrict service account to app subtrees only
   olcAccess: to dn.subtree="ou=people,dc=school,dc=internal"
     by dn="cn=ldap-admin-svc,dc=school,dc=internal" write
     by * none
   ```

3. **Rotate the bind password** periodically. Update `config.py` and restart the service.

4. **Do not use the same bind account** for other services (e.g. Zimbra, Sophos) — if the app is compromised, only the app's access is exposed.

### Test bind account

`ldap_test_bind()` (used on the Test Login page) binds with user-supplied credentials directly. This is a legitimate LDAP operation (verifying a user's own password) and does not use the service account.

---

## 6. Password Hashing (SHA-1 / SSHA)

### Current scheme

The application stores passwords using OpenLDAP's `{SSHA}` scheme:

```
{SSHA}<base64( SHA1(password + salt) + salt )>
```

This is the **OpenLDAP default** and is broadly compatible with all LDAP clients (Zimbra, Sophos, Windows LDAP clients, etc.).

### Known limitation

SHA-1 is cryptographically weak by modern standards. It is vulnerable to brute-force attacks if an attacker obtains the LDAP database (`/var/lib/ldap/`). A determined attacker with modern GPU hardware can crack short passwords quickly.

### Migration path

OpenLDAP supports stronger schemes (`{ARGON2}`, `{PBKDF2}`, `{CRYPT}` with bcrypt). To switch:

1. Enable the new scheme in `slapd`:
   ```bash
   # Install the argon2 contrib module for slapd, then:
   ldapmodify -Y EXTERNAL -H ldapi:/// -f set-passhash.ldif
   ```
   with `set-passhash.ldif` containing:
   ```ldif
   dn: cn=config
   changetype: modify
   replace: olcPasswordHash
   olcPasswordHash: {ARGON2}
   ```

2. Existing passwords remain as `{SSHA}` until users next log in and set a new password (OpenLDAP verifies the old hash, then stores the new one with the current scheme).

3. Update `hash_password_for_ldap()` in `ldap_password.py` to use the new scheme for admin-set passwords.

### Practical advice for schools

Student passwords are intentionally short and memorable (they are shared across mail, Teams, and Sophos). This means SHA-1 weakness is relevant. **The strongest mitigation is physical security of the LDAP server** — if an attacker cannot read `/var/lib/ldap/`, the hash scheme is irrelevant.

---

## 7. Audit File Permissions

The audit system writes CSV files containing **plaintext passwords** for newly created users. These are intended for distribution to classroom teachers.

Default audit directory (set in `config.py`):

```python
NEW_USERS_AUDIT_DIR = "/var/ldap-audit"
```

### Required permissions

```bash
# Create the directory, owned by the gunicorn service user
sudo mkdir -p /var/ldap-audit
sudo chown ldap-admin:ldap-admin /var/ldap-audit
sudo chmod 750 /var/ldap-audit
```

- **Mode 750** — owner (service account) can read/write; group members can read; others have no access.
- **Do not serve this directory via nginx** or any web server.
- Files should be retrieved directly from the server by an administrator and then deleted.

### After distributing audit files

```bash
# Delete audit files after passwords have been handed out
sudo rm /var/ldap-audit/class_*.csv
```

Consider setting up a cron job to automatically delete files older than 30 days:

```cron
0 3 * * * find /var/ldap-audit -name "*.csv" -mtime +30 -delete
```

### Zimbra provisioning scripts

If configured, provisioning scripts (`ZIMBRA_STUDENT_SCRIPT`, `ZIMBRA_STAFF_SCRIPT`) also contain plaintext passwords. Apply the same permissions and lifecycle policy.

---

## 8. Session Security

Flask sessions are signed with `SECRET_KEY` (set in `config.py`). The session cookie holds:

- The logged-in UID
- The CSRF token
- The TEST/LIVE mode flag

### Recommendations

| Setting | Recommendation |
|---|---|
| `SECRET_KEY` | At least 32 random bytes: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_COOKIE_HTTPONLY` | `True` (default in Flask) — prevents JavaScript from reading the cookie |
| `SESSION_COOKIE_SECURE` | `True` — only send cookie over HTTPS. Set this once HTTPS is configured. |
| `SESSION_COOKIE_SAMESITE` | `"Lax"` — additional CSRF mitigation |
| `PERMANENT_SESSION_LIFETIME` | Set a session timeout (e.g. `timedelta(hours=8)`) to expire idle sessions |

Example additions to `config.py`:

```python
SESSION_COOKIE_HTTPONLY  = True
SESSION_COOKIE_SECURE    = True          # Requires HTTPS
SESSION_COOKIE_SAMESITE  = "Lax"
PERMANENT_SESSION_LIFETIME = 28800       # 8 hours in seconds
```

---

## 9. TEST MODE as a Safety Net

TEST MODE is not a security feature per se, but it is an important **operational safety control**.

When TEST MODE is active (per-session flag), all destructive LDAP operations — create user, delete user, change password, bulk import — are **previewed but not committed**. The app logs what *would* have happened without making any LDAP writes.

This prevents accidental bulk changes from affecting production. It is especially important during bulk imports.

**Default:** New sessions start in TEST MODE. A logged-in admin must explicitly switch to LIVE MODE from the dashboard.

See [User Guide — TEST MODE and LIVE MODE](User-Guide.md#test-mode-and-live-mode) for full details.

---

## 10. Summary Checklist

Use this checklist before going live:

- [ ] `SECRET_KEY` set to a long random value (≥ 32 bytes)
- [ ] `ADMIN_UID_ALLOWLIST` configured with only IT admin UIDs
- [ ] LDAP bind account is a dedicated service account, not the root DN
- [ ] nginx configured with HTTPS (TLS 1.2+)
- [ ] `SESSION_COOKIE_SECURE = True` set in `config.py`
- [ ] `/var/ldap-audit` (or custom `NEW_USERS_AUDIT_DIR`) has mode 750, not served by web server
- [ ] Audit CSV files deleted after distribution to teachers
- [ ] Rate limiter storage upgraded to Redis if running multiple gunicorn workers
- [ ] `TRUSTED_PROXIES` configured in flask-limiter if behind nginx
- [ ] Consider migrating `olcPasswordHash` to `{ARGON2}` or `{PBKDF2}` for stronger hashing
