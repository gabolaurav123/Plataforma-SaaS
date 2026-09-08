from ..errors import DomainError
from . import crypto_wallets as wallets, payment_methods as methods
from .common import audit


def details(ui, w):
    return (
        f"{w['asset']} · {w['network']}\n"
        + ui.t("crypto_address")
        + ": "
        + w["address"]
        + "\nMemo / Tag: "
        + (w.get("memo") or "—")
        + ("\n" + w["instructions"] if w.get("instructions") else "")
    )


def menu(ui):
    method = methods.get(ui.db, ui.bot, "CRYPTO_MANUAL", True)
    rows = [
        [
            ui.button(
                ("✅ " if w["enabled"] else "⬜ ") + w["asset"] + " · " + w["network"],
                "wallet_detail",
                id=w["id"],
            )
        ]
        for w in wallets.wallets(ui.db, ui.bot, active_only=False)
    ]
    rows += [
        [ui.button(ui.t("crypto_add"), "wallet_add")],
        [
            ui.button(
                ui.t("crypto_disable" if method.enabled else "crypto_enable"),
                "method_toggle",
                provider="CRYPTO_MANUAL",
            )
        ],
    ]
    ui.say(ui.t("crypto_intro") + "\n\n" + ui.t("active" if method.enabled else "inactive"), rows)


def dispatch(ui, action, d):
    ui.ctx(ui.bot.tenant_id, "payment_config")
    if action in {"method_edit", "method_toggle"}:
        return menu(ui)
    if action == "wallet_add":
        ui.state().data = {}
        ui.say(ui.t("crypto_asset"), [[ui.button(a, "wallet_asset", asset=a)] for a in wallets.ASSETS])
    elif action == "wallet_asset":
        if d.get("asset") not in wallets.ASSETS:
            raise DomainError("INVALID_ASSET", ui.t("crypto_asset"))
        ui.say(
            ui.t("crypto_network_prompt"),
            [
                [ui.button(n, "wallet_network", asset=d["asset"], network=n)]
                for n in wallets.NETWORKS[d["asset"]]
            ]
            + [[ui.button(ui.t("crypto_custom_network"), "wallet_network", asset=d["asset"], network="")]],
        )
    elif action == "wallet_network":
        if d.get("asset") not in wallets.ASSETS:
            raise DomainError("INVALID_ASSET", ui.t("crypto_asset"))
        ui.ask(
            "biz:crypto_address" if d.get("network") else "biz:crypto_network",
            ui.t("crypto_address_prompt" if d.get("network") else "crypto_network_prompt"),
            wallet=d,
        )
    elif action == "wallet_confirm":
        state = ui.state().data
        if state.get("flow") != "biz:crypto_confirm":
            raise DomainError("EXPIRED", ui.t("crypto_restart"))
        wallets.save(ui.db, ui.bot, ui.user.id, state["wallet"])
        ui.state().data = {}
        ui.say(ui.t("saved"))
        menu(ui)
    elif action in {"wallet_detail", "wallet_toggle"}:
        method = methods.get(ui.db, ui.bot, "CRYPTO_MANUAL", True)
        rows = wallets.wallets(ui.db, ui.bot, active_only=False)
        wallet = next((w for w in rows if w["id"] == d.get("id")), None)
        if not wallet:
            raise DomainError("NOT_FOUND", ui.t("empty"), 404)
        if action == "wallet_toggle":
            wallet["enabled"] = not wallet["enabled"]
            method.public_config = {**method.public_config, "wallets": rows}
            if not any(w["enabled"] for w in rows):
                method.enabled = False
            audit(
                ui.db,
                ui.bot.tenant_id,
                ui.user.id,
                "CRYPTO_WALLET_TOGGLED",
                wallet["id"],
                {"bot_id": ui.bot.id, "enabled": wallet["enabled"]},
            )
        ui.say(
            details(ui, wallet),
            [
                [
                    ui.button(
                        ui.t("crypto_disable" if wallet["enabled"] else "crypto_enable"),
                        "wallet_toggle",
                        id=wallet["id"],
                    )
                ],
                [ui.button(ui.t("methods"), "methods")],
            ],
        )


def answer(ui, flow, state, text, message):
    ui.ctx(ui.bot.tenant_id, "payment_config")
    w = dict(state["wallet"])
    field = flow.removeprefix("crypto_")
    if field == "confirm":
        raise DomainError("CONFIRM_REQUIRED", ui.t("crypto_press_confirm"))
    if field not in {"network", "address", "memo", "instructions", "qr"}:
        raise DomainError("INVALID_FIELD", ui.t("crypto_restart"))
    if field == "qr":
        if text != "-" and not message.get("photo"):
            raise DomainError("IMAGE_REQUIRED", ui.t("crypto_qr_prompt"))
        w["qr_file_id"] = message["photo"][-1]["file_id"] if message.get("photo") else ""
        w = wallets.validate(w)
        ui.state().data = {"business": True, "flow": "biz:crypto_confirm", "wallet": w}
        ui.say(
            ui.t("crypto_review") + "\n\n" + details(ui, w), [[ui.button(ui.t("confirm"), "wallet_confirm")]]
        )
        return
    limits = {"network": 64, "address": 200, "memo": 128, "instructions": 600}
    if not text or len(text) > limits[field] or (field in {"network", "address"} and text == "-"):
        raise DomainError("INVALID_WALLET", ui.t("crypto_invalid"))
    w[field] = "" if text == "-" else text
    if field == "address":
        wallets.validate(w)
    next_field = {"network": "address", "address": "memo", "memo": "instructions", "instructions": "qr"}[
        field
    ]
    ui.ask("biz:crypto_" + next_field, ui.t("crypto_" + next_field + "_prompt"), wallet=w)
