# Password Generation

The app includes two password generators, designed for different audiences. Both use Python's `secrets` module (cryptographically secure random number generator) for all random choices.

---

## Kid-friendly passwords (students)

**Format:** `AdjectiveNoun##?`

Two memorable words plus a two-digit number and a trailing `?`.

**Examples:**
```
HappyKangaroo47?
BraveWombat12?
QuickEagle83?
TallPlatypus06?
```

These are designed to be:
- Easy for school-age children to remember and type
- Strong enough for services like email, internet login (Sophos), and Teams
- Compliant with basic password policies (mixed case, digit, symbol)

### Word lists

| List | Contents | Size |
|---|---|---|
| `WORDS1` (adjectives) | big, small, happy, brave, fast, quiet… | 39 words |
| `WORDS2` (nouns) | Australian animals, natural features, general animals | 42 words |

Both lists are in `password_utils.py` and can be customised.

### Entropy

- 39 adjectives × 42 nouns × 99 numbers = **161,theid combinations**
- In practice: ~17 bits from words + 7 bits from number = ~24 bits
- Sufficient for an internal school system; not intended for high-security contexts

---

## Staff passwords

**Format:** `XXXX-XXXX-XXXXXX` (14 random characters, grouped with dashes)

**Examples:**
```
Kp7@-mQ3#-vRs2n+
Zj9%-bN4?-wLt8m=
Ax2_-cP6@-hGr5k#
```

Characters used:
- Letters: `ABCDEFGHJKLMNPQRSTUVWXYZ` + `abcdefghijkmnopqrstuvwxyz` (ambiguous characters like `0/O`, `1/I/l` removed)
- Digits: `23456789` (again, `0` and `1` removed)
- Symbols: `?@#%+=_`

At least one of each character class is guaranteed. The dashes are separators and make the password easier to read aloud or type from a printout.

---

## Using the generator in the UI

On the **Create New User**, **Check/Edit User**, and **Change Password** pages, a **Generate** button appears next to the password field. Clicking it:

1. Calls `POST /api/generate_password` with `{"kind": "kid"}` or `{"kind": "adult"}`
2. Fills the password field with the generated value
3. Selects the text so you can immediately copy it

The `kind` defaults to `"kid"` on most pages. Staff-facing pages may pass `"adult"`.

### API endpoint

The generator is also available as a JSON API for any page that needs it:

```
POST /api/generate_password
Content-Type: application/json

{"kind": "kid"}
```

Response:
```json
{"password": "HappyKangaroo47?", "kind": "kid"}
```

Valid `kind` values: `kid`, `child`, `student`, `school`, `adult`, `staff`, `strong`

---

## Customising the word lists

Edit `password_utils.py`:

```python
WORDS1 = [
    "big", "small", "happy", ...   # adjectives
]

WORDS2 = [
    "Kangaroo", "Wombat", "Eagle", ...  # nouns — can be school mascots, local landmarks, etc.
]
```

Tips:
- Avoid words that are confusing to spell or that could be offensive
- Keep both lists free of duplicates (duplicates reduce entropy)
- Australian-themed words work well for a school context — students find them memorable
- Words in `WORDS2` are used as-is (capitalised), so capitalise them in the list

---

## Audit CSV and passwords

When new accounts are created, the plaintext temporary password is written to the audit CSV in `NEW_USERS_AUDIT_DIR`. This is intentional — the password needs to be distributed to the student.

**Protect these files:**
```bash
sudo chown root:root /var/lib/ldap_admin_flask/audit
sudo chmod 700       /var/lib/ldap_admin_flask/audit
```

Delete or archive audit CSV files once passwords have been distributed and students have been asked to change them.
