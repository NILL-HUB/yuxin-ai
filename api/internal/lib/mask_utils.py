"""脱敏工具。"""


def mask_email(email: str) -> str:
    email = (email or "").strip()
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local}***@{domain}"
    return f"{local[:2]}***{local[-2:]}@{domain}"


def mask_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"
