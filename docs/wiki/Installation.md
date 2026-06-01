# Installation

## Requirements

| Component | Minimum version |
|---|---|
| Python | 3.11+ |
| OpenLDAP server | 2.4+ (2.6 recommended) |
| OS | Ubuntu 22.04 / Debian 12 or equivalent |
| gunicorn | Installed via `requirements.locked.txt` |

The web UI is accessed through a browser on the same trusted network as the LDAP server.  
It does **not** need internet access after the initial `pip install`.

---

## Step 1 — Install system packages

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git
```

---

## Step 2 — Clone the repository

```bash
sudo git clone https://github.com/ChrisMcGowanAu/ldap_admin_flask.git /opt/ldap_admin_flask
cd /opt/ldap_admin_flask
```

You can install anywhere; `/opt/ldap_admin_flask` is the convention used throughout this guide.

---

## Step 3 — Create the Python virtual environment

```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.locked.txt
```

`requirements.locked.txt` contains pinned versions of all dependencies for a reproducible install.  
If you prefer loose version constraints (e.g. for testing with newer packages):

```bash
venv/bin/pip install -r requirements.txt
```

---

## Step 4 — Create `config.py`

`config.py` is **not** tracked by git — it contains secrets and site-specific settings.

```bash
cp config_example.py config.py
nano config.py
```

At minimum, set these values before running the app:

| Setting | What to set |
|---|---|
| `FLASK_SECRET_KEY` | A random string — see below |
| `LDAP_SERVER_URI` | e.g. `ldap://192.168.1.10` or `ldaps://ldap.school.local` |
| `LDAP_BIND_DN` | The DN of the admin/service account |
| `LDAP_BIND_PASSWORD` | Password for the bind account |
| `LDAP_USER_BASE_DN` | e.g. `ou=people,dc=school,dc=local` |
| `LDAP_GROUP_BASE_DN` | e.g. `ou=groups,dc=school,dc=local` |
| `ADMIN_UID_ALLOWLIST` | List of uids allowed to log into this tool |

**Generate a secret key:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the output into `FLASK_SECRET_KEY = "..."` in `config.py`.

> See the [Configuration Reference](Configuration-Reference) page for every available setting.

---

## Step 5 — Test the configuration

Check that all Python files compile cleanly:

```bash
venv/bin/python -m compileall -q .
```

Do a quick manual run to confirm the app starts and can reach the LDAP server:

```bash
venv/bin/gunicorn --bind 127.0.0.1:5000 app:app
```

Open `http://your-server:5000/` in a browser and try logging in.  
The banner should show **TEST MODE IS ACTIVE** — that means no real LDAP changes will be made yet.

Press `Ctrl+C` to stop gunicorn after testing.

---

## Step 6 — Install the systemd service

Copy the example service file:

```bash
sudo cp systemd/ldap-admin.service.example /etc/systemd/system/ldap-admin.service
sudo nano /etc/systemd/system/ldap-admin.service
```

Adjust `WorkingDirectory`, `User`, `Group`, and the gunicorn `--bind` address if needed.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ldap-admin.service
sudo systemctl status ldap-admin.service --no-pager
```

View live logs:

```bash
sudo journalctl -u ldap-admin.service -f
```

---

## Step 7 — Reverse proxy (recommended)

For production, place **nginx** or **Apache** in front of gunicorn and terminate HTTPS there.  
Keep gunicorn bound to `127.0.0.1:5000`.

### Minimal nginx example

```nginx
server {
    listen 443 ssl;
    server_name ldapadmin.school.local;

    ssl_certificate     /etc/ssl/certs/school.crt;
    ssl_certificate_key /etc/ssl/private/school.key;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name ldapadmin.school.local;
    return 301 https://$host$request_uri;
}
```

> The tool should only be accessible from trusted networks (IT office, VPN).  
> Do not expose it directly to the internet.

---

## Step 8 — Create the audit directory

If you use the new-user audit CSV feature, create the output directory and set strict permissions:

```bash
sudo mkdir -p /var/lib/ldap_admin_flask/audit
sudo chown root:root /var/lib/ldap_admin_flask/audit
sudo chmod 700 /var/lib/ldap_admin_flask/audit
```

The files written here contain plaintext temporary passwords — treat them as sensitive.

---

## Upgrading

```bash
cd /opt/ldap_admin_flask
sudo git pull
venv/bin/pip install -r requirements.locked.txt
sudo systemctl restart ldap-admin.service
```

Always read the commit history or release notes before upgrading in case `config.py` needs new settings added.
