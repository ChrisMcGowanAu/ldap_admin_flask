import config


def compute_email_for_uid(
    uid: str, class_key: str | None = None, gid_number: int | None = None
) -> str:
    """Return an email address for the given uid.

    Domain names are read from config so this works for any deployment:
      - Staff:   ZIMBRA_STAFF_DOMAIN    (e.g. "example.org")
      - Students: ZIMBRA_STUDENT_DOMAIN (e.g. "students.example.org")

    Both settings fall back to sensible placeholder values if not configured,
    but should always be set explicitly in config.py.
    """
    uid = (uid or "").strip().lower()
    if not uid:
        return ""

    staff_domain = getattr(config, "ZIMBRA_STAFF_DOMAIN", "example.org")
    student_domain = getattr(config, "ZIMBRA_STUDENT_DOMAIN", "students.example.org")

    # Prefer explicit class key if we have it
    if class_key:
        ck = class_key.strip().lower()
        if ck == "staff":
            return f"{uid}@{staff_domain}"
        # Anything else we treat as student
        return f"{uid}@{student_domain}"

    # Fallback to gidNumber if provided
    try:
        gid = int(gid_number) if gid_number is not None else None
    except Exception:
        gid = None

    if gid is not None and gid == int(config.STAFF_GID_NUMBER):
        return f"{uid}@{staff_domain}"

    # Default: student
    return f"{uid}@{student_domain}"
