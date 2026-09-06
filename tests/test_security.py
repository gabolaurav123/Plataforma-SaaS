import base64
import json
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from platform_app import models as m
from platform_app.security import validate_init_data, LocalKeyring, Vault, redact
from platform_app.errors import DomainError
from conftest import signed_data, MASTER_TOKEN, bot_parts


def test_initdata_signature_and_age():
    assert validate_init_data(signed_data(42), MASTER_TOKEN)["id"] == 42
    for raw in [
        signed_data(42, timestamp=m.now() - 301),
        signed_data(42, timestamp=m.now() + 31),
        signed_data(42) + "&auth_date=1",
    ]:
        with pytest.raises(DomainError):
            validate_init_data(raw, MASTER_TOKEN)
    with pytest.raises(DomainError):
        validate_init_data(signed_data(42), "wrong:token")


def test_envelope_bound_to_tenant_and_key_version():
    wrapper = LocalKeyring(
        {"v1": base64.b64encode(b"a" * 32).decode(), "v2": base64.b64encode(b"b" * 32).decode()}, "v2"
    )
    vault = Vault(wrapper)
    encrypted = vault.encrypt("private-token", "tenant-a:bot-a:token")
    assert "private-token" not in json.dumps(encrypted)
    assert encrypted["key_version"] == "v2"
    assert vault.decrypt(encrypted, "tenant-a:bot-a:token") == "private-token"
    with pytest.raises(Exception):
        vault.decrypt(encrypted, "tenant-b:bot-a:token")


@pytest.mark.parametrize(
    "resource",
    [
        "bots",
        "contacts",
        "plans",
        "payments",
        "receipts",
        "subscriptions",
        "conversations",
        "campaigns",
        "automations",
        "coupons",
        "referrals",
        "analytics",
        "team",
        "providers",
    ],
)
def test_tenant_a_cannot_list_tenant_b(env, resource):
    url = f"/api/t/{env['tb']}/" + ("analytics" if resource == "analytics" else f"resources/{resource}")
    assert env["client"].get(url, headers=env["a"]).status_code == 404


def test_idor_query_and_export(env):
    client, base = env["client"], f"/api/t/{env['ta']}"
    assert client.get(base + f"/bots/{env['bb']}/settings", headers=env["a"]).status_code == 404
    assert client.post(base + f"/bots/{env['bb']}/repair", headers=env["a"]).status_code == 404
    assert (
        client.get(base + "/resources/contacts", params={"bot_id": env["bb"]}, headers=env["a"]).status_code
        == 404
    )
    csv = client.get(base + "/export/contacts", headers=env["a"])
    assert csv.status_code == 200 and "Client 0" in csv.text and "Client 1" not in csv.text
    assert client.get(f"/api/t/{env['tb']}/export/contacts", headers=env["a"]).status_code == 404


def test_orm_automatic_scope_and_write_guard(env):
    with env["r"].db.tenant(env["ta"]) as db:
        rows = list(db.scalars(select(m.Contact)))
        assert len(rows) == 1 and rows[0].tenant_id == env["ta"]
    with pytest.raises(DomainError):
        with env["r"].db.tenant(env["ta"]) as db:
            db.add(
                m.Contact(
                    tenant_id=env["tb"],
                    bot_id=env["bb"],
                    telegram_user_id=777,
                    first_name="Forbidden",
                    last_seen_at=m.now(),
                )
            )
            db.flush()


def test_composite_foreign_key_blocks_cross_tenant(env):
    with pytest.raises(IntegrityError):
        with env["r"].db.system() as db:
            db.add(
                m.Contact(
                    tenant_id=env["ta"],
                    bot_id=env["bb"],
                    telegram_user_id=555,
                    first_name="Invalid",
                    last_seen_at=m.now(),
                )
            )


def test_read_only_cannot_configure_or_export(env):
    with env["r"].db.system() as db:
        db.scalar(select(m.TenantMember).where(m.TenantMember.user_id == env["ua"])).role = "READ_ONLY"
    base = f"/api/t/{env['ta']}"
    assert env["client"].post(base + f"/bots/{env['ba']}/repair", headers=env["a"]).status_code == 403
    assert env["client"].get(base + "/export/contacts", headers=env["a"]).status_code == 403


def test_customer_cannot_use_another_bots_initdata(env):
    ba, _, _ = bot_parts(env)
    bb, _, _ = bot_parts(env, "b")
    raw = signed_data(900001, env["fake"].tokens[ba.telegram_bot_id])
    assert env["client"].post(f"/api/auth/b/{bb.public_id}", json={"init_data": raw}).status_code == 401
    token = env["client"].post(f"/api/auth/b/{ba.public_id}", json={"init_data": raw}).json()["access_token"]
    assert (
        env["client"]
        .get(f"/api/b/{bb.public_id}/me", headers={"Authorization": f"Bearer {token}"})
        .status_code
        == 404
    )


def test_secrets_absent_in_ui_and_errors(env):
    response = env["client"].get(f"/api/t/{env['ta']}/resources/bots", headers=env["a"])
    assert "ciphertext" not in response.text and MASTER_TOKEN not in response.text
    result = env["client"].put(
        f"/api/t/{env['ta']}/providers/BANK_TRANSFER",
        headers=env["a"],
        json={"enabled": True, "clabe": "SECRET_INVALID"},
    )
    assert result.status_code == 422 and "SECRET_INVALID" not in result.text
    assert redact({"bot_token": MASTER_TOKEN, "error": MASTER_TOKEN}) == {
        "bot_token": "[REDACTED]",
        "error": "[REDACTED]",
    }
