"""Gmail unread digest via IMAP app-password. Read-only."""

import email
import imaplib
import logging
import os

log = logging.getLogger("deskd.gmail")


def unread_digest(host: str, user: str, password_env: str, max_n: int = 5):
    """Returns (count, [subject lines]) or None on failure/config-missing."""
    password = os.environ.get(password_env, "")
    if not (user and password):
        return None
    try:
        conn = imaplib.IMAP4_SSL(host, 993)
        conn.login(user, password)
        conn.select("inbox", readonly=True)
        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            return None
        ids = data[0].split()
        count = len(ids)
        subjects = []
        for eid in reversed(ids[-max_n * 3:])[:max_n]:
            _, msg_data = conn.fetch(eid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
            msg = email.message_from_bytes(msg_data[0][1])
            subj = str(email.header.make_header(
                email.header.decode_header(msg.get("Subject", "(no subject)"))))[:70]
            frm = email.utils.parseaddr(msg.get("From", ""))[0][:30]
            subjects.append(f"{frm}: {subj}")
        conn.logout()
        return count, subjects
    except Exception:
        log.exception("gmail check failed")
        return None


def spoken_digest(result, max_n: int = 5) -> str:
    count, subjects = result
    if count == 0:
        return "Your inbox is all clear, no unread mails."
    shown = min(count, max_n)
    lead = f"You have {count} unread mail{'' if count == 1 else 's'}."
    if subjects:
        listing = "; ".join(subjects[:max_n])
        lead += " Top ones: " + listing + "."
    return lead
