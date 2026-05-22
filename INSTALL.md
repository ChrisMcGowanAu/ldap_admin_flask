# Installation

These notes assume an Ubuntu/Debian-style server and an install path of:

```bash
/opt/ldap_admin_flask
```

Adjust paths and service user/group for your site.

## 1. Install system packages

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git
```

## 2. Clone the repository

```bash
sudo git clone https://github.com/ChrisMcGowanAu/ldap_admin_flask.git /opt/ldap_admin_flask
cd /opt/ldap_admin_flask
```

## 3. Create the Python virtual environment

```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
```

Install the pinned/known-good requirements if present:

```bash
venv/bin/pip install -r requirements.locked.txt
```

If the project only has `requirements.txt`, use:

```bash
venv/bin/pip install -r requirements.txt
```

For development tools only:

```bash
venv/bin/pip install black isort ruff flake8 pytest
```

## 4. Create local configuration

`config.py` is not tracked by git because it contains site-specific settings and may contain secrets.

For a generic/small-business style setup:

```bash
cp config_example.py config.py
```

For a school-style setup, if provided:

```bash
cp config_school.py config.py
```

Then edit it:

```bash
nano config.py
```

At minimum, review:

- `FLASK_SECRET_KEY`
- `LDAP_SERVER_URI`
- `LDAP_BIND_DN`
- `LDAP_BIND_PASSWORD`
- `LDAP_USER_BASE_DN`
- `LDAP_GROUP_BASE_DN`
- `ADMIN_UID_ALLOWLIST`
- `HOME_STYLE`
- `CLASS_OPTIONS`

## 5. Test Python syntax

```bash
venv/bin/python -m py_compile app.py home_paths.py ldap_users.py ldap_groups.py provisioning.py
```

You can also compile the full tree:

```bash
venv/bin/python -m compileall -q .
```

## 6. Run manually for a first test

```bash
venv/bin/gunicorn --bind 127.0.0.1:5000 app:app
```

For temporary direct LAN testing only:

```bash
venv/bin/gunicorn --bind 0.0.0.0:5000 app:app
```

Then open:

```text
http://server-name-or-ip:5000/
```

## 7. Install the systemd service

Create the destination directory if needed:

```bash
sudo mkdir -p /etc/systemd/system
```

Copy the example service:

```bash
sudo cp systemd/ldap-admin.service.example /etc/systemd/system/ldap-admin.service
```

Edit paths/user/group if required:

```bash
sudo nano /etc/systemd/system/ldap-admin.service
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ldap-admin.service
sudo systemctl status ldap-admin.service --no-pager
```

View logs:

```bash
sudo journalctl -u ldap-admin.service -f
```

## 8. Reverse proxy notes

For production, consider placing nginx or Apache in front of Gunicorn and leaving Gunicorn bound to:

```text
127.0.0.1:5000
```

Use HTTPS if the tool is accessed across a network.

## 9. Safety notes

Before using LIVE mode:

- Confirm `TEST_MODE` behaviour.
- Confirm `ADMIN_UID_ALLOWLIST`.
- Confirm your LDAP bind account has only the permissions it needs.
- Confirm generated password/export files are disabled unless your site needs them.
- Confirm any generated output directory is root-owned and not world-readable.

## 10. Troubleshooting

If the app fails with `Missing config.py`, create one from an example:

```bash
cp config_example.py config.py
nano config.py
```

If systemd starts but the web page does not load:

```bash
sudo systemctl status ldap-admin.service --no-pager
sudo journalctl -u ldap-admin.service -n 100 --no-pager
```
