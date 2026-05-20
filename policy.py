import config


def compute_email_for_uid(
    uid: str, class_key: str | None = None, gid_number: int | None = None
) -> str:
    uid = (uid or "").strip().lower()
    if not uid:
        return ""

    # Prefer explicit class key if we have it
    if class_key:
        ck = class_key.strip().lower()
        if ck == "staff":
            return f"{uid}@lorien.nsw.edu.au"
        # Anything else we treat as student
        return f"{uid}@students.lorien.nsw.edu.au"

    # Fallback to gidNumber if provided
    try:
        gid = int(gid_number) if gid_number is not None else None
    except Exception:
        gid = None

    if gid is not None and gid == int(config.STAFF_GID_NUMBER):
        return f"{uid}@lorien.nsw.edu.au"

    # Default: student
    return f"{uid}@students.lorien.nsw.edu.au"
