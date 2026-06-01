# Class and Group Model

Understanding how this tool models classes and groups is important before doing any bulk operations. OpenLDAP uses two separate mechanisms for group membership, and this tool manages both.

---

## Two types of group membership

### 1. Primary group — `gidNumber`

Every POSIX user has a **primary `gidNumber`** stored directly on their user object.

```
uid: alices
gidNumber: 2026        ← this is the primary group
homeDirectory: /schoolNet/classes/class2026/alices
```

In this tool, the primary `gidNumber` represents the user's **class** (or staff). It determines:
- Which class directory the user's home is under (in `graduation_year_group` mode)
- Which `posixGroup` object the user should be a `memberUid` of

### 2. Supplementary groups — `memberUid`

Users can also belong to additional `posixGroup` entries via the `memberUid` attribute:

```
dn: cn=science-tools,ou=groups,dc=school,dc=local
objectClass: posixGroup
cn: science-tools
gidNumber: 601
memberUid: alices
memberUid: bjones
```

These supplementary groups are used to control access to shared resources — internet filters (Sophos), shared drives, printers, Teams, etc.

---

## posixGroup objects

Each class **must** have a corresponding `posixGroup` object in `LDAP_GROUP_BASE_DN`.

| Group | cn | gidNumber |
|---|---|---|
| Staff | `staff` | `STAFF_GID_NUMBER` (e.g. 500) |
| Class 12 / 2026 | `class2026` | 2026 |
| Class 11 / 2027 | `class2027` | 2027 |
| Science tools | `science-tools` | 601 (arbitrary) |

### Auto-creation of class groups

When a new user is created with a class `gidNumber`, the app checks whether the matching `posixGroup` exists. If it does **not** exist:

- **Class groups** (year-range gidNumbers, typically 2020–2200): created automatically.
- **Staff group**: never auto-created. It must be created manually on the Create Group page or via LDAP tooling. The app will warn you if it is missing.

### Manual group creation

Use the **Create Group** page to create any `posixGroup` by `cn` and `gidNumber`.

---

## Group Audit

The **Group Audit** tool checks:

1. **Missing posixGroup objects** — users have a `gidNumber` but no matching group exists.
2. **Missing memberUid memberships** — a group exists but the user is not listed in its `memberUid`.

Both issues can cause login or access problems, especially for services that check POSIX group membership.

**Best practice:** run a Group Audit after any bulk import or year-rollover operation.

---

## Year rollover

At the start of each academic year:

1. New students join (Class 7 intake) → use **Bulk Import** with the new `Class 7` class key.
2. Graduated students (former Class 12) can be **exported** to an XLSX for records, then **deleted** via the Delete Users page after filtering by their `gidNumber`.
3. The `CLASS_OPTIONS` in `config.py` recalculate automatically — `Class 12` maps to the new year's `gidNumber`.

Because `gidNumber` equals the graduation year, you will never accidentally reuse a group number for a new cohort — a new Class 12 cohort gets the current year's number, and the previous year's group (and home directories) remain intact until you deliberately remove them.

---

## Summary diagram

```
User object (ou=people)
  uid: alices
  gidNumber: 2026   ──────────────►  posixGroup (ou=groups)
  homeDirectory: …                     cn: class2026
                                        gidNumber: 2026
                                        memberUid: alices   ◄── must be present
                                        memberUid: bjones

Supplementary group (ou=groups)
  cn: science-tools
  gidNumber: 601
  memberUid: alices  ◄── optional; managed via Manage User Groups
```
