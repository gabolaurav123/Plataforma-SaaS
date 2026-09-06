import base64
import json
from pathlib import Path
from sqlalchemy import select
from ..models import BankReceipt, Payment, Contact, TenantMember, PlatformUser, now, uid
from ..security import inspect_image
from ..errors import DomainError
from .common import audit, emit, send


class ReceiptService:
    def __init__(self, runtime):
        self.r = runtime

    def submit(self, session, bot, payment, data):
        if (
            payment.bot_id != bot.id
            or payment.provider != "BANK_TRANSFER"
            or payment.status not in {"PENDING", "RECEIPT_SUBMITTED"}
        ):
            raise DomainError(
                "RECEIPT_NOT_EXPECTED", "No hay un pago bancario pendiente para este comprobante.", 409
            )
        image = inspect_image(data, self.r.settings.max_upload_bytes)
        candidates = session.scalars(
            select(BankReceipt).where(
                BankReceipt.tenant_id == bot.tenant_id, BankReceipt.created_at > now() - 365 * 86400
            )
        )
        duplicate = any(
            x.sha256 == image["sha256"]
            or (
                x.perceptual_hash
                and (int(x.perceptual_hash, 16) ^ int(image["perceptual_hash"], 16)).bit_count() <= 4
            )
            for x in candidates
        )
        receipt = BankReceipt(
            id=uid(),
            tenant_id=bot.tenant_id,
            payment_id=payment.id,
            sha256=image["sha256"],
            perceptual_hash=image["perceptual_hash"],
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
        admins = session.scalars(
            select(PlatformUser)
            .join(TenantMember, TenantMember.user_id == PlatformUser.id)
            .where(
                TenantMember.tenant_id == bot.tenant_id,
                TenantMember.active.is_(True),
                TenantMember.role.in_(["OWNER", "SUPERVISOR", "PAYMENTS"]),
            )
        )
        for admin in admins:
            send(
                session,
                None,
                admin.telegram_user_id,
                f"Comprobante pendiente en {bot.name}. Revísalo en tu panel.",
                f"receipt-admin:{receipt.id}:{admin.id}",
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
        value = self.r.vault.decrypt(
            encrypted, f"{receipt.tenant_id}:{receipt.id}:receipt"
        )
        return base64.b64decode(value)

    def review(self, session, bot, receipt, actor, decision, note="", accept_duplicate=False):
        receipt = session.scalar(select(BankReceipt).where(BankReceipt.id == receipt.id).with_for_update())
        if receipt.status != "PENDING":
            return receipt
        payment = session.scalar(select(Payment).where(Payment.id == receipt.payment_id).with_for_update())
        if decision == "APPROVE":
            if receipt.suspicious and not accept_duplicate:
                raise DomainError(
                    "SUSPICIOUS_RECEIPT",
                    "Revisa la alerta de duplicado y confirma expresamente la aprobación.",
                    409,
                )
            self.r.payments.confirm(session, bot, payment, f"bank:{payment.id}", actor)
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
        receipt.reviewed_by, receipt.review_note = actor, note
        audit(session, bot.tenant_id, actor, f"RECEIPT_{decision}", receipt.id)
        return receipt
