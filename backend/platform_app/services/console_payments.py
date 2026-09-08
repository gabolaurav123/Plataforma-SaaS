from . import payment_methods as methods
from .common import audit, enqueue
from ..errors import DomainError

LABELS = {
    "bank": "ui_c3eb9ca000",
    "holder": "ui_1b32f4ae07",
    "account": "ui_cbf28b1516",
    "currency": "ui_d6919eba9d",
    "instructions": "ui_d1bbd1ed38",
    "additional": "ui_a18123343e",
    "qr_file_id": "ui_6e81e31a40",
    "secret_key": "ui_f47a99ebcf",
    "webhook_secret": "ui_48c7cde407",
    "client_id": "ui_8726db0139",
    "client_secret": "ui_4aded5faf1",
    "webhook_id": "ui_e0e251a172",
    "environment": "ui_5b832c4889",
}


def dispatch(ui, action, d):
    ui.ctx(ui.bot.tenant_id, "payment_config")
    if action == "methods":
        rows = []
        for provider, label in methods.PROVIDERS.items():
            row = methods.get(ui.db, ui.bot, provider)
            label = (
                ui.t("crypto_label")
                if provider == "CRYPTO_MANUAL"
                else ui.t("bank_transfer")
                if provider == "BANK_TRANSFER"
                else label
            )
            rows.append(
                [
                    ui.button(
                        ("✅ " if row and row.enabled else "⬜ ") + label,
                        "method_edit",
                        provider=provider,
                    )
                ]
            )
        ui.say(ui.t("ui_170615fe9b"), rows)
        return
    provider = d["provider"]
    row = methods.get(ui.db, ui.bot, provider, True)
    if action == "method_toggle":
        if row.enabled:
            row.enabled = False
            audit(
                ui.db, ui.bot.tenant_id, ui.user.id, "PAYMENT_METHOD_DISABLED", row.id, {"bot_id": ui.bot.id}
            )
        else:
            methods.enable(ui.db, ui.r, ui.bot, row, ui.user.id)
    elif action == "method_field":
        field = d["field"]
        if field not in methods.PUBLIC_FIELDS[provider] | methods.SECRET_FIELDS[provider]:
            raise DomainError("INVALID_FIELD", "Campo no disponible.")
        ui.ask(
            "biz:method_value",
            ui.caption(LABELS[field])
            + (ui.t("ui_4397348d23") if field in methods.SECRET_FIELDS[provider] else ""),
            provider=provider,
            field=field,
        )
        return
    if provider == "CRYPTO_MANUAL":
        from .console_crypto import menu

        return menu(ui)
    private = methods.secrets(ui.r, row) if provider in {"STRIPE", "PAYPAL"} else {}
    public_config = methods.public_config(ui.r, row)
    text = (
        methods.PROVIDERS[provider] + "\n" + (ui.t("ui_6bb777626f") if row.enabled else ui.t("ui_b8a21ed746"))
    )
    for key in sorted(methods.PUBLIC_FIELDS[provider] | methods.SECRET_FIELDS[provider]):
        value = ui.t("ui_54a0560489") if key in private else public_config.get(key, ui.t("ui_2ef68536d8"))
        text += (
            "\n"
            + ui.caption(LABELS[key])
            + ": "
            + (ui.t("ui_b3b865b157") if key == "qr_file_id" and key in row.public_config else str(value))
        )
    if provider in {"STRIPE", "PAYPAL"}:
        text += (
            "\n\nWebhook: " + ui.r.settings.public_api_url.rstrip("/") + "/payments/hooks/" + row.webhook_key
        )
        text += ui.t("ui_adc7700099") + (
            "checkout.session.completed, checkout.session.async_payment_succeeded, checkout.session.async_payment_failed, checkout.session.expired, charge.refunded"
            if provider == "STRIPE"
            else "CHECKOUT.ORDER.APPROVED, PAYMENT.CAPTURE.COMPLETED, PAYMENT.CAPTURE.DENIED, PAYMENT.CAPTURE.PENDING, PAYMENT.CAPTURE.REFUNDED"
        )
    ui.say(
        text,
        [
            [ui.button(LABELS[key], "method_field", provider=provider, field=key)]
            for key in sorted(methods.PUBLIC_FIELDS[provider] | methods.SECRET_FIELDS[provider])
        ]
        + [
            [
                ui.button(
                    ui.t("ui_7ef1cd2d34") if row.enabled else ui.t("ui_8e38c2571d"),
                    "method_toggle",
                    provider=provider,
                )
            ]
        ],
    )


def answer(ui, flow, state, text, message):
    ui.ctx(ui.bot.tenant_id, "payment_config")
    provider, field = state["provider"], state["field"]
    if field == "qr_file_id":
        if not message.get("photo"):
            raise DomainError("IMAGE_REQUIRED", "Envía una imagen del QR.")
        text = message["photo"][-1]["file_id"]
    methods.update(ui.db, ui.r, ui.bot, provider, ui.user.id, field, text)
    if field in methods.SECRET_FIELDS[provider]:
        enqueue(
            ui.db,
            "DELETE_MESSAGE",
            ui.bot.tenant_id,
            {"chat_id": ui.actor["id"], "message_id": message["message_id"]},
            f"delete-secret:{ui.bot.id}:{ui.update['update_id']}",
            ui.bot.id,
            lane="interactive",
        )
    ui.state().data = {}
    ui.say(ui.t("saved"))
