"""Campaign composer, explicit audience/preview/confirmation and queued delivery."""

from urllib.parse import urlparse
import hashlib
import json
from sqlalchemy import select, func
from .. import models as m
from ..errors import DomainError
from . import business as b
from .common import enqueue, audit, emit
from .texts import validate_text

SEGMENTS = {
    "all": "ui_bd02b9a7d7",
    "active": "ui_a114da7782",
    "without": "ui_5b50af8895",
    "expired": "ui_65d23c6308",
    "plan": "ui_4bdd388b44",
    "channel": "ui_8d1a37a8ad",
    "selected": "ui_8ec04b2e9a",
    "tags": "ui_137cb944c5",
}


def version(row):
    return hashlib.sha256(
        json.dumps([row.text, row.media, row.buttons, row.segment], sort_keys=True).encode()
    ).hexdigest()


def detail(ui, row):
    counts = dict(
        ui.db.execute(
            select(m.CampaignRecipient.status, func.count())
            .where(
                m.CampaignRecipient.campaign_id == row.id, m.CampaignRecipient.tenant_id == ui.bot.tenant_id
            )
            .group_by(m.CampaignRecipient.status)
        ).all()
    )
    ui.say(
        ui.t(
            "ui_be8d017030",
            p0=row.name,
            p1=row.status,
            p2=ui.caption(SEGMENTS.get(row.segment.get("kind", "all"), "—")),
            p3=row.audience_count,
            p4=counts.get("SENT", 0),
            p5=counts.get("FAILED", 0),
            p6=counts.get("BLOCKED", 0),
            p7=counts.get("DELIVERY_UNKNOWN", 0),
            p8=row.text[:1000],
        ),
        (
            [
                [ui.button(ui.t("ui_4de0ad27ba"), "campaign_audience", id=row.id)],
                [
                    ui.button(ui.t("ui_22cd26baf8"), "campaign_content", id=row.id),
                    ui.button(ui.t("ui_8f56865c5a"), "campaign_buttons", id=row.id),
                ],
                [ui.button(ui.t("ui_eb02ca78d4"), "campaign_preview", id=row.id)],
            ]
            if row.status == "DRAFT"
            else [
                [ui.button(ui.t("ui_eea6aee201"), "detail", resource="campaigns", id=row.id)],
                [
                    ui.button(
                        ui.t("ui_5685e1faf0") if row.status == "PAUSED" else ui.t("ui_cd25ee5b1d"),
                        "campaign_resume" if row.status == "PAUSED" else "campaign_pause",
                        id=row.id,
                    )
                ],
            ]
            if row.status != "COMPLETED"
            else []
        ),
    )


def dispatch(ui, action, d):
    ui.ctx(ui.bot.tenant_id, "sales")
    if action == "campaign":
        ui.ask("biz:campaign_name", ui.t("ui_e2a573d70b"))
        return
    row = b.entity(ui.db, m.Campaign, d["id"], ui.bot)
    if action in {"campaign_pause", "campaign_resume"}:
        if action == "campaign_pause" and row.status in {"RUNNING", "SCHEDULED"}:
            row.status = "PAUSED"
        elif action == "campaign_resume" and row.status == "PAUSED":
            ui.r.campaigns.start(ui.db, row)
        audit(ui.db, ui.bot.tenant_id, ui.user.id, "CAMPAIGN_" + row.status, row.id, {"bot_id": ui.bot.id})
        detail(ui, row)
        return
    if row.status != "DRAFT":
        raise DomainError(
            "CAMPAIGN_STATE", "Esta difusión ya fue confirmada. Crea otra para cambiar contenido o audiencia."
        )
    if action == "campaign_audience":
        ui.say(
            ui.t("ui_c654c831c3"),
            [[ui.button(label, "campaign_segment", id=row.id, kind=key)] for key, label in SEGMENTS.items()],
        )
    elif action == "campaign_segment":
        kind = d["kind"]
        if kind not in SEGMENTS:
            raise DomainError("INVALID_AUDIENCE", "Audiencia no válida.")
        if kind in {"all", "active", "without", "expired"}:
            row.segment = {"kind": kind}
            detail(ui, row)
        elif kind in {"plan", "channel"}:
            model = m.Plan if kind == "plan" else m.Channel
            query = select(model).where(model.bot_id == ui.bot.id, model.tenant_id == ui.bot.tenant_id)
            if d.get("after"):
                query = query.where(model.id > d["after"])
            values = list(ui.db.scalars(query.order_by(model.id).limit(9)))
            buttons = [
                [ui.button(ui.label(value), "campaign_segment_id", id=row.id, kind=kind, target_id=value.id)]
                for value in values[:8]
            ]
            if len(values) > 8:
                buttons.append(
                    [ui.button(ui.t("next"), "campaign_segment", id=row.id, kind=kind, after=values[7].id)]
                )
            ui.say(ui.t("select"), buttons)
        else:
            ui.ask(
                "biz:campaign_segment",
                ui.t("ui_bb7b58a4ab") if kind == "selected" else ui.t("ui_8806753ae0"),
                id=row.id,
                kind=kind,
            )
    elif action == "campaign_segment_id":
        kind = d["kind"]
        if kind not in {"plan", "channel"}:
            raise DomainError("INVALID_AUDIENCE", "Audiencia no válida.")
        b.entity(ui.db, m.Plan if kind == "plan" else m.Channel, d["target_id"], ui.bot)
        row.segment = {"kind": kind, kind + "_id": d["target_id"]}
        detail(ui, row)
    elif action == "campaign_content":
        ui.ask("biz:campaign_content", ui.t("ui_c25cdfcf7e"), id=row.id)
    elif action == "campaign_buttons":
        ui.ask("biz:campaign_buttons", ui.t("ui_74f3c61f2d"), id=row.id)
    elif action == "campaign_preview":
        enqueue(
            ui.db,
            "CAMPAIGN_PREVIEW",
            ui.bot.tenant_id,
            {"campaign_id": row.id, "viewer_id": ui.actor["id"]},
            "campaign-preview:" + row.id + ":" + str(ui.update["update_id"]),
            ui.bot.id,
        )
        ui.say(ui.t("ui_aef99d1b58"))
    elif action == "campaign_confirm":
        if d.get("version") != version(row):
            raise DomainError(
                "PREVIEW_CHANGED", "La difusión cambió. Revisa una nueva vista previa antes de enviar."
            )
        row.actor_id = ui.user.id
        ui.r.campaigns.start(ui.db, row)
        audit(
            ui.db,
            ui.bot.tenant_id,
            ui.user.id,
            "CAMPAIGN_CONFIRMED",
            row.id,
            {"bot_id": ui.bot.id, "preview_count": d.get("count"), "segment": row.segment},
        )
        emit(
            ui.db,
            ui.bot.tenant_id,
            "BROADCAST_CREATED",
            "broadcast:" + row.id,
            ui.bot.id,
            data={"campaign_id": row.id},
        )
        ui.say(
            ui.t("broadcast_queued"),
            [[ui.button(ui.t("ui_0be56afd40"), "detail", resource="campaigns", id=row.id)]],
        )


def answer(ui, flow, state, text, message):
    ui.ctx(ui.bot.tenant_id, "sales")
    if flow == "campaign_name":
        if not 2 <= len(text) <= 100:
            raise DomainError("INVALID_NAME", "Usa un nombre entre 2 y 100 caracteres.")
        row = m.Campaign(
            id=m.uid(),
            tenant_id=ui.bot.tenant_id,
            bot_id=ui.bot.id,
            name=text,
            text="",
            segment={"kind": "all"},
            actor_id=ui.user.id,
        )
        ui.db.add(row)
        ui.db.flush()
        ui.ask("biz:campaign_content", ui.t("ui_9f700d12b5"), id=row.id)
        return
    row = b.entity(ui.db, m.Campaign, state["id"], ui.bot)
    if row.status != "DRAFT":
        raise DomainError("CAMPAIGN_STATE", "La difusión ya está confirmada.")
    if flow == "campaign_content":
        value, media = text or message.get("caption", ""), {}
        if message.get("photo"):
            media = {"kind": "photo", "file_id": message["photo"][-1]["file_id"]}
        for key in ["video", "document"]:
            if message.get(key):
                media = {"kind": key, "file_id": message[key]["file_id"]}
        validate_text(value)
        if not (value or media) or media and len(value) > 1024:
            raise DomainError("INVALID_CONTENT", "Revisa el contenido y el tamaño del pie de mensaje.")
        row.text, row.media = value, media
    elif flow == "campaign_buttons":
        buttons = []
        for line in [] if text == "-" else text.splitlines():
            label, url = [part.strip() for part in line.split("|", 1)]
            parsed = urlparse(url)
            if (
                not 1 <= len(label) <= 64
                or parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or len(url) > 1000
            ):
                raise DomainError("INVALID_LINK", "Usa un título y una URL HTTPS válida.")
            buttons.append({"text": label, "url": url})
        if len(buttons) > 4:
            raise DomainError("TOO_MANY_BUTTONS", "Usa hasta cuatro botones.")
        row.buttons = buttons
    elif flow == "campaign_segment":
        values = list(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))
        kind = state["kind"]
        if kind == "selected":
            ids = [int(value) for value in values]
            if len(ids) > 1000 or any(value <= 0 for value in ids):
                raise ValueError()
            row.segment = {"kind": kind, "telegram_ids": ids}
        else:
            if len(values) > 10 or any(len(value) > 40 for value in values):
                raise ValueError()
            row.segment = {"kind": "tags", "tags": values}
    audit(
        ui.db, ui.bot.tenant_id, ui.user.id, "CAMPAIGN_EDITED", row.id, {"bot_id": ui.bot.id, "field": flow}
    )
    ui.db.flush()
    ui.state().data = {}
    detail(ui, row)
