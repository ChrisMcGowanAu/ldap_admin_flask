# LDAP Admin Flask Tool – pretty UI + username collision + editable Check User

Features:

- Dynamic class → cohort mapping (Class 12..7 → classYYYY home dirs)
- Login using uid (or fragment), resolved to cn=Full Name DNs under ou=people,dc=lorien
- Username generator (given name + first letter of family name)
- Password generator (TwoWordsNN?)
- Username collision handling:
  - If requested uid exists, automatically uses uid1, uid2, ...
- Dark, prettier UI
- Check User:
  - Accepts full or partial uid (first matching entry is used)
  - Shows attributes
  - Allows editing: givenName, sn, displayName, homeDirectory, loginShell


## Local fixes included

- `TEST_MODE` default set to `False` in `config_example.py`
- Login now enforces `ADMIN_UID_ALLOWLIST` (edit in your real `config.py`)
- Username generation now uses given name + **first letter** of family name
