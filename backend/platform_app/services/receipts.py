import base64
import json
from pathlib import Path
from sqlalchemy import select
from ..models import BankReceipt, Payment, Contact, now, uid
from ..security import inspect_receipt
from ..errors import DomainError
from .common import audit, emit, send
from .payments import MANUAL_PROVIDERS


class ReceiptService:
    def __init__(self, runtime):
        self.r = runtime

    def submit(self, session, bot, payment, data):
        payment = session.scalar(
            select(Payment)
            .where(Payment.id == payment.id, Payment.tenant_id == bot.tenant_id, Payment.bot_id == bot.id)
            .with_for_update()
        )
        if (
            not payment
            or payment.provider not in MANUAL_PROVIDERS
            or payment.status not in {"PENDING", "RECEIPT_SUBMITTED"}
        ):
            raise DomainError(
                "RECEIPT_NOT_EXPECTED", "No hay un pago manual pendiente para este comprobante.", 409
            )
        image = inspect_receipt(data, self.r.settings.max_upload_bytes)
        previous = session.scalar(
            select(BankReceipt).where(
                BankReceipt.payment_id == payment.id, BankReceipt.sha256 == image["sha256"]
            )
        )
        if previous:
            return previous
        exact_duplicate = session.scalar(
            select(BankReceipt.id)
            .where(BankReceipt.tenant_id == bot.tenant_id, BankReceipt.sha256 == image["sha256"])
            .limit(1)
        )
        candidates = session.execute(
            select(BankReceipt.sha256, BankReceipt.perceptual_hash)
            .where(BankReceipt.tenant_id == bot.tenant_id, BankReceipt.created_at > now() - 365 * 86400)
            .order_by(BankReceipt.created_at.desc())
            .limit(500)
        )
        duplicate = bool(exact_duplicate) or any(
            x.sha256 == image["sha256"]
            or (
                x.perceptual_hash
                and image.get("perceptual_hash")
                and (int(x.perceptual_hash, 16) ^ int(image["perceptual_hash"], 16)).bit_count() <= 4
            )
            for x in candidates
        )
        receipt = BankReceipt(
            id=uid(),
            tenant_id=bot.tenant_id,
            payment_id=payment.id,
            sha256=image["sha256"],
            perceptual_hash=image.get("perceptual_hash"),
            storage_key=f"{bot.tenant_id}/{uid()}.json",
            media_type=image["media_type"],
            duplicate=duplicate,
            suspicious=duplicate,
        )
        encrypted = self.r.vault.encrypt(
            base64.b64encode(image["bytes"]).decode(), f"{bot.tenant_id}:{receipt.id}:receipt"
        )
        if self.r.settings.receipt_storage == "database":
            receipt.receipt_ciphertext = encrypted
            receipt.storage_key = f"database/{receipt.id}"
        else:
            path = Path(self.r.settings.storage_path) / receipt.storage_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(encrypted), encoding="utf-8")
        session.add(receipt)
        payment.status = "RECEIPT_SUBMITTED"
        contact = session.get(Contact, payment.contact_id)
        contact.stage = "RECEIPT_SUBMITTED"
        emit(session, bot.tenant_id, "RECEIPT_SUBMITTED", f"receipt:{receipt.id}", bot.id, contact.id)
        from .notifications import notify

        notify(
            session,
            self.r,
            bot,
            "new_receipt",
            {
                "key": "duplicate_receipt_notice" if duplicate else "receipt_notice",
                "values": {"bot": bot.name, "name": contact.first_name},
            },
            "receipt:" + receipt.id,
            "payments",
            "detail",
            {"resource": "receipts", "id": receipt.id},
        )
        return receipt

    def read(self, receipt):
        encrypted = receipt.receipt_ciphertext
        if encrypted is None:
            root = Path(self.r.settings.storage_path).resolve()
            path = (root / receipt.storage_key).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise DomainError("RECEIPT_UNAVAILABLE", "Comprobante no disponible.", 404)
            encrypted = json.loads(path.read_text(encoding="utf-8"))
        value = self.r.vault.decrypt(encrypted, f"{receipt.tenant_id}:{receipt.id}:receipt")
        return base64.b64decode(value)

    def review(self, session, bot, receipt, actor, decision, note="", accept_duplicate=False):
        receipt = session.scalar(
            select(BankReceipt)
            .where(BankReceipt.id == receipt.id, BankReceipt.tenant_id == bot.tenant_id)
            .with_for_update()
        )
        if not receipt:
            raise DomainError("NOT_FOUND", "Comprobante no disponible.", 404)
        payment = session.scalar(
            select(Payment)
            .where(
                Payment.id == receipt.payment_id, Payment.bot_id == bot.id, Payment.tenant_id == bot.tenant_id
            )
            .with_for_update()
        )
        if not payment:
            raise DomainError("NOT_FOUND", "Comprobante no disponible.", 404)
        if receipt.status != "PENDING":
            return receipt
        if decision == "APPROVE":
            if receipt.suspicious and not accept_duplicate:
                raise DomainError(
                    "SUSPICIOUS_RECEIPT",
                    "Revisa la alerta de duplicado y confirma expresamente la aprobación.",
                    409,
                )
            prefix = "crypto" if payment.provider == "CRYPTO_MANUAL" else "bank"
            self.r.payments.confirm(session, bot, payment, f"{prefix}:{payment.id}", actor)
            receipt.status = "APPROVED"
        elif decision == "REJECT":
            if payment.status == "APPROVED":
                raise DomainError("PAYMENT_FINALIZED", "El pago ya fue aprobado.", 409)
            receipt.status, payment.status = "REJECTED", "REJECTED"
        elif decision == "REQUEST_NEW":
            receipt.status, payment.status = "REPLACEMENT_REQUESTED", "PENDING"
        elif decision == "SUSPICIOUS":
            receipt.suspicious = True
        else:
            raise DomainError("INVALID_DECISION", "Acción no válida.")
        receipt.reviewed_by, receipt.review_note, receipt.reviewed_at = actor, note[:1000], now()
        audit(
            session,
            bot.tenant_id,
            actor,
            f"RECEIPT_{decision}",
            receipt.id,
            {"bot_id": bot.id, "payment_id": payment.id, "note": note[:1000]},
        )
        contact = session.get(Contact, payment.contact_id)
        from .texts import bot_text

        if decision in {"REJECT", "REQUEST_NEW"}:
            key = "PAYMENT_REJECTED" if decision == "REJECT" else "RECEIPT_REQUEST"
            send(
                session,
                bot,
                contact.telegram_user_id,
                bot_text(session, bot, key, locale=contact.locale) + ("\n" + note[:1000] if note else ""),
                f"receipt-result:{receipt.id}:{decision}",
                service_message=True,
            )
        emit(
            session,
            bot.tenant_id,
            "RECEIPT_" + decision,
            f"receipt-review:{receipt.id}:{decision}",
            bot.id,
            contact.id,
            {"receipt_id": receipt.id, "payment_id": payment.id},
        )
        return receipt
