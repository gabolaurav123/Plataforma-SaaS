from sqlalchemy import inspect

PRIVATE_COLUMNS = {
    "token_hash",
    "token_ciphertext",
    "webhook_ciphertext",
    "webhook_secret_hash",
    "secrets_ciphertext",
    "storage_key",
    "sha256",
    "perceptual_hash",
    "invoice_payload",
    "payload",
    "dedup_key",
    "native_invite_link",
}
MONEY_COLUMNS = {"amount_minor", "amount_xtr"}


def public(record):
    if record is None:
        return None
    return {
        c.key: str(getattr(record, c.key)) if c.key in MONEY_COLUMNS else getattr(record, c.key)
        for c in inspect(record).mapper.column_attrs
        if c.key not in PRIVATE_COLUMNS
    }
