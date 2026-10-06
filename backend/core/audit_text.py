"""Audit-log entries as one plain sentence: the action taken.

Each entry stores the action code, who or what it was about (subject)
and any extra detail. This turns them into what a person would write in
a register: "Added student Ada Obi (M1), Computer Engineering, level 200".
"""


def _with(text, detail, sep=" - "):
    return f"{text}{sep}{detail}" if detail else text


SENTENCES = {
    # students and cards
    "student_create": lambda s, d: _with(f"Added student {s}", d, ", "),
    "student_update": lambda s, d: f"Edited student {s}" + (f" ({d.replace('changed: ', '')})" if d else ""),
    "student_delete": lambda s, d: f"Deleted student {s}",
    "card_bind":      lambda s, d: f"Registered {d} to {s}",
    "card_create":    lambda s, d: _with(f"Added {s}", d),
    "card_update":    lambda s, d: f"Set {s} {d}" if d else f"Changed {s}",
    "card_revoke":    lambda s, d: _with(f"Revoked {s}", d),
    # courses, enrolment, venues
    "course_create":  lambda s, d: _with(f"Added {s}", d),
    "course_update":  lambda s, d: _with(f"Edited {s}", d),
    "course_delete":  lambda s, d: f"Deleted {s}",
    "enroll_add":     lambda s, d: f"Enrolled {s} on {d}",
    "enroll_remove":  lambda s, d: f"Removed {s} from {d}",
    "enroll_bulk":    lambda s, d: f"Enrolled {d} on {s}",
    "venue_create":   lambda s, d: _with(f"Added {s}", d),
    "venue_update":   lambda s, d: _with(f"Edited {s}", d),
    "venue_delete":   lambda s, d: f"Deleted {s}",
    # timetable and lectures
    "slot_create":    lambda s, d: f"Scheduled a lecture: {d}",
    "slot_update":    lambda s, d: f"Moved a lecture to {d}",
    "slot_delete":    lambda s, d: f"Removed a lecture: {d}",
    "session_open":   lambda s, d: f"Opened the {s} lecture of {d}",
    "session_close":  lambda s, d: f"Closed the {s} lecture of {d}",
    "taps_recheck":   lambda s, d: (f"Placed {s} and re-checked its taps: {d}" if s
                                    else f"Re-checked taps for {d}"),
    # readers
    "device_add":     lambda s, d: _with(f"Added {s}", d),
    "device_update":  lambda s, d: f"Set {s} to {d}" if d else f"Changed {s}",
    "device_remove":  lambda s, d: _with(f"Removed {s}", d),
    "device_repair":  lambda s, d: f"Re-paired {s}" + (f" ({d})" if d else ""),
    "device_token_reveal": lambda s, d: f"Viewed the sign-in token of {s}",
    "device_token_rotate": lambda s, d: f"Replaced the sign-in token of {s}",
    # staff and accounts
    "staff_add":      lambda s, d: f"Added staff member {s} {d}".strip(),
    "staff_role":     lambda s, d: f"Changed the role of {s} from {d.replace(' -> ', ' to ')}",
    "staff_remove":   lambda s, d: f"Removed staff member {s}" + (f" ({d})" if d else ""),
    "staff_password": lambda s, d: f"Gave {s} a new temporary password",
    "org_disable":    lambda s, d: f"Disabled {s}: nobody in it can sign in",
    "org_enable":     lambda s, d: f"Re-enabled {s}",
    "user_disable":   lambda s, d: f"Disabled the account of {s}",
    "user_enable":    lambda s, d: f"Re-enabled the account of {s}",
    "user_update":    lambda s, d: f"Edited the account of {s}" + (f" ({d})" if d else ""),
    "user_delete":    lambda s, d: f"Deleted the account of {s}",
    "org_update":     lambda s, d: f"Changed organisation settings: {d}",
    "profile_update": lambda s, d: "Edited their own profile" + (f" ({d})" if d else ""),
    "password_change": lambda s, d: "Changed their own password",
    "sign_in":        lambda s, d: "Signed in",
    "sign_in_failed": lambda s, d: f"Failed sign-in to {s}" + (f" ({d})" if d else ""),
}


def describe(entry):
    """The action taken, as a sentence."""
    s, d = entry.subject or "", entry.detail or ""
    make = SENTENCES.get(entry.action)
    if make:
        try:
            return make(s, d)
        except Exception:
            pass
    # Older entries (before subjects were recorded) and anything unknown.
    return " ".join(p for p in (entry.action.replace("_", " ").capitalize(), s, d) if p)
