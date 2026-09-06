from sqlalchemy import select
from .. import models as m
from ..errors import DomainError
from .common import audit
from .texts import TEXTS, VARIABLES, default_text, validate_text, render
from .i18n import LANGUAGES


def dispatch(ui, action, d):
    ui.ctx(ui.bot.tenant_id, "configure")
    language = d.get("locale", ui.language)
    if language not in LANGUAGES:
        raise DomainError("INVALID_LANGUAGE", "Idioma no válido.")
    if action == "templates":
        ui.say(
            ui.t("messages") + " · " + LANGUAGES[language],
            [[ui.button(label, "templates", locale=key) for key, label in LANGUAGES.items()]]
            + [
                [ui.button(ui.t("template_" + key), "template_select", key=key, locale=language)]
                for key in TEXTS
            ],
        )
        return
    key = d.get("key")
    if key not in TEXTS:
        raise DomainError("INVALID_TEMPLATE", "Mensaje no disponible.")
    row = ui.db.scalar(
        select(m.BotText).where(
            m.BotText.tenant_id == ui.bot.tenant_id,
            m.BotText.bot_id == ui.bot.id,
            m.BotText.locale == language,
            m.BotText.key == key,
        )
    )
    if action == "template_restore":
        if row:
            ui.db.delete(row)
        audit(
            ui.db,
            ui.bot.tenant_id,
            ui.user.id,
            "TEMPLATE_RESTORED",
            ui.bot.id,
            {"key": key, "locale": language},
        )
        ui.say(ui.t("saved"))
    elif action == "template_edit":
        ui.ask(
            "biz:template_value",
            ui.t("edit")
            + ": "
            + ui.t("template_" + key)
            + "\n"
            + " ".join("{" + x + "}" for x in sorted(VARIABLES)),
            key=key,
            locale=language,
        )
    else:
        value = row.value if row else default_text(key, language)
        preview = render(
            value,
            {
                "name": "Alex",
                "username": "@alex",
                "plan": "Premium",
                "price": "10.00",
                "currency": "USD",
                "expiration_date": "2026-10-01",
                "days_remaining": 3,
                "channel": "VIP",
                "bot_name": ui.bot.name,
            },
        )
        ui.say(
            ui.t("template_" + key) + "\n" + value + "\n\n👁\n" + preview,
            [
                [ui.button(ui.t("edit"), "template_edit", **d)],
                [ui.button(ui.t("restore"), "template_restore", **d)],
            ],
        )


def answer(ui, flow, state, text):
    if flow != "template_value":
        return False
    ui.ctx(ui.bot.tenant_id, "configure")
    validate_text(text)
    row = ui.db.scalar(
        select(m.BotText).where(
            m.BotText.bot_id == ui.bot.id, m.BotText.key == state["key"], m.BotText.locale == state["locale"]
        )
    )
    before = row.value if row else None
    if not row:
        row = m.BotText(
            tenant_id=ui.bot.tenant_id, bot_id=ui.bot.id, key=state["key"], locale=state["locale"], value=text
        )
        ui.db.add(row)
    else:
        row.value = text
    audit(
        ui.db,
        ui.bot.tenant_id,
        ui.user.id,
        "TEMPLATE_UPDATED",
        ui.bot.id,
        {"key": state["key"], "locale": state["locale"], "before": before, "after": text},
    )
    ui.state().data = {}
    ui.say(ui.t("saved"))
    return True
