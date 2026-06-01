# User Guide

## Logging in

Open the app in your browser and sign in with your **LDAP admin account** (the same credentials you use for LDAP admin tools).

Only accounts listed in `ADMIN_UID_ALLOWLIST` in `config.py` are permitted. If your login credentials are correct but you see *"Login OK — but this User is not an Admin"*, ask whoever manages `config.py` to add your uid to the allowlist.

---

## TEST MODE vs LIVE MODE

A coloured banner at the top of every page shows the current mode.

| Banner colour | What it means |
|---|---|
| 🟡 Yellow — **TEST MODE** | No changes are written to LDAP. All actions show you what *would* happen. |
| 🔴 Red — **LIVE MODE** | Changes are applied immediately to the real LDAP directory. |

**Always test in TEST MODE first**, especially for bulk operations.  
Use the **Switch to LIVE mode** button in the banner when you are ready to commit changes.  
The mode is per browser session — different admins can be in different modes simultaneously.

---

## Dashboard

The dashboard is your home page after login. It provides tiles linking to every feature.

It also shows:
- Which LDAP admin account you are logged in as
- The current TEST / LIVE mode

---

## Create New User

**Path:** Dashboard → *Create New User*

Creates a single LDAP user account.

### Fields

| Field | Required | Notes |
|---|---|---|
| First Name | Yes | Stored as `givenName` |
| Last Name | Yes | Stored as `sn` |
| Full Name | No | Defaults to `First Last`. Stored as `cn` and `displayName`. |
| Username | Yes | Must be unique. Use **Generate** to auto-create from first name + first letter of surname (e.g. `alices`). |
| Password | Yes | Use **Generate** for a kid-friendly or staff password. See [Password Generation](Password-Generation). |
| Class / Group | Yes | Determines the user's primary `gidNumber` and `homeDirectory`. |

### What happens on submit

1. The username is checked for collisions — if `alices` exists, `alices1` is tried, then `alices2`, etc.
2. A `uidNumber` is allocated (max existing + 1, starting from `UID_BASE_NUMBER`).
3. The user is created with `objectClass: inetOrgPerson, posixAccount, shadowAccount`.
4. The user is added to the `posixGroup` matching their primary `gidNumber` (auto-created for class groups if missing).
5. An audit CSV record is written to `NEW_USERS_AUDIT_DIR`.
6. If Zimbra provisioning is configured, a `zmprov ca` command is appended to the script file.

In **TEST MODE** none of the above writes happen — only a log entry is made.

---

## Check / Edit User

**Path:** Dashboard → *Check / Edit User*

Search for an existing user, review their LDAP attributes, edit selected fields, and check group membership.

### Searching

Type a **username fragment** and click **Look Up**. The search uses `uid=*fragment*`, so `ali` will match `alice`, `alison`, `chalice`, etc.

- If exactly one user matches, their details load immediately.
- If multiple users match, a list appears — click **Select** next to the right one.

### Editable fields

| Field | LDAP attribute |
|---|---|
| First Name | `givenName` |
| Full Name / Display Name | `cn`, `displayName` |
| Home Directory | `homeDirectory` |
| Login Shell | `loginShell` |
| Class / Group | `gidNumber` (and optionally `homeDirectory`) |

Changing **Class / Group** updates the user's primary `gidNumber` and adds them to the new class `posixGroup`.

### Group membership status

Below the edit form, the page shows whether the user is a `memberUid` of the `posixGroup` matching their primary `gidNumber`. If they are missing, a **Fix Membership** button appears.

### Test password (inline)

You can test the user's current password directly from this page without leaving the search result.

---

## Change Password

**Path:** Dashboard → *Change Password*

Resets one or many LDAP user passwords.

### Single password change

1. Search for the user by username fragment (same as Check/Edit User).
2. Enter a new password, or use **Generate** to produce one.
3. Click **Change Password**.

### Bulk password change (CSV)

Upload a CSV with `Username` and `Password` columns. See [CSV Formats — Password Reset](CSV-Formats#password-reset-csv) for the exact layout.

1. Click **Choose File** and select your CSV.
2. Click **Preview** to validate all rows without making changes.
3. Review the preview table — rows marked `warn` have usernames that don't exist in LDAP.
4. In LIVE MODE, tick the confirmation checkbox and click **Apply** to commit.

---

## Bulk Import Users

**Path:** Dashboard → *Bulk Import (CSV)*

Creates many users at once from a CSV file.

### Recommended workflow

1. Prepare your CSV. Download the template from the *Download template CSV* link on the page.
2. Switch to **TEST MODE**.
3. Upload and submit the CSV — check the results table for any `FAIL` or `Skipped` rows.
4. Fix your CSV if needed and repeat until all rows show `OK`.
5. Switch to **LIVE MODE**.
6. Upload the same CSV again — accounts are now created for real.

See [CSV Formats — Bulk Import](CSV-Formats#bulk-import-csv) for column details.

---

## Group Audit

**Path:** Dashboard → *Group Audit*

Checks that every user's primary `gidNumber` has a matching `posixGroup` object **and** that the user appears in that group's `memberUid` list.

### Audit modes

| Mode | What it checks |
|---|---|
| **Current cohorts** | Staff group + class groups defined in `CLASS_OPTIONS` only |
| **All users** | Every user in `LDAP_USER_BASE_DN` |
| **Single group** | One specific group by `gidNumber` or dropdown |

### Results

| Section | Meaning |
|---|---|
| Missing group objects | A `gidNumber` exists on users but no `posixGroup` has that `gidNumber` |
| Missing memberships | A `posixGroup` exists but the user is not in its `memberUid` list |
| Skipped users | Users with invalid or empty `uid`/`gidNumber` (data quality issues) |
| Outside scope | Users ignored because their `gidNumber` is not in the selected audit scope |

### Fixing missing groups

Class groups (gidNumbers in the year range) can be auto-created by selecting them and clicking **Create selected missing groups**. The staff group is never auto-created — it must be created manually via the *Create Group* page.

Missing `memberUid` memberships can be fixed via the [Manage User Groups](User-Guide#manage-user-groups) page or by using the **Check / Edit User** fix button on individual accounts.

---

## Users by Primary Group

**Path:** Dashboard → *Users by Primary Group*

Lists all users whose primary `gidNumber` matches a chosen group. Useful for reviewing who is in a particular class cohort before deleting a year group.

Select a group from the dropdown or type a `gidNumber` manually, then click **List Users**.

---

## Manage User Groups

**Path:** Dashboard → *Manage User Groups*

Adds or removes users from **supplementary** `posixGroup` entries (stored as `memberUid`).

This is separate from the primary `gidNumber` — it manages secondary group memberships such as internet access groups, shared resource groups, etc.

### Single user

Search for a user, then use the **Add Group** dropdown or **Remove** buttons next to existing groups.

### Bulk group membership (CSV)

Upload a CSV with `username` and `gid` or `group` columns. See [CSV Formats — Group Membership](CSV-Formats#group-membership-csv).

1. Upload the CSV and click **Preview** — validates users and groups exist.
2. In LIVE MODE, tick the confirmation box and click **Apply**.

---

## Export Users (XLSX)

**Path:** Dashboard → *Export Users*

Downloads an Excel workbook containing all LDAP users.

The workbook contains:
- An **All Users** sheet sorted by uid
- One sheet per primary `gidNumber`, named `<gidNumber>_<group cn>` (e.g. `2026_class2026`)
- Columns: uid, cn, givenName, sn, gidNumber, primaryGroup, primaryGroupStatus, secondaryGroups, homeDirectory, loginShell, dn

Secondary groups are listed semicolon-separated in the `secondaryGroups` column.

Useful for annual audits, handing user lists to teachers, or cross-checking against a student information system.

---

## Test User Password

**Path:** Dashboard → *Test User Password*

Performs an LDAP bind test for a given username and password — confirms whether the credentials are valid.

This is useful when a user says "my password isn't working". You can:
1. Search for their account
2. Try their reported password
3. Confirm whether the issue is the wrong password, a locked account, or something else

No changes are made to LDAP regardless of TEST / LIVE mode.

---

## Delete User(s)

**Path:** Dashboard → *Delete User(s)*

Deletes one or more LDAP user accounts.

### Finding users to delete

- **Search by username fragment** — e.g. type `2022` to find accounts containing that string
- **List by primary gidNumber** — useful for removing an entire graduated class cohort at once

Select users with the checkboxes, then click **Delete Selected**.

A confirmation step shows how many users will be deleted. In TEST MODE, the deletion is simulated only.

> **Note:** Deleting a user does **not** automatically remove them from supplementary `memberUid` groups. Use the Group Audit afterwards to find and clean up orphaned memberships.

---

## Create Group

**Path:** nav → *Create Group*

Creates a new `posixGroup` with a given `cn` and `gidNumber`.

The tool checks that neither the `cn` nor the `gidNumber` is already in use before creating.

---

## Delete Group(s)

**Path:** nav → *Delete Group(s)*

Search for groups by `cn` fragment or `gidNumber`, review member counts and primary-gid user counts, then delete selected groups with confirmation.

> Groups that have users with that `gidNumber` as their **primary** group are highlighted as a warning. Deleting such a group leaves those users without a valid primary group.

---

## Logout

Click **Logout** in the navigation bar to clear the session. The TEST/LIVE mode toggle is also reset.
