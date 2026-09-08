"""Public deposit instructions only; settlement is always reviewed by a human."""

import re
from ..errors import DomainError
from ..models import uid
from . import payment_methods
from .common import audit

ASSETS = ("USDT", "USDC", "BTC", "BNB", "ETH", "SOL", "TON", "XRP")
NETWORKS = {
    "USDT": ("TRON (TRC20)", "Ethereum (ERC20)", "BNB Smart Chain (BEP20)", "Solana", "TON"),
    "USDC": ("Ethereum (ERC20)", "Solana", "Polygon", "Base", "Arbitrum"),
    "BTC": ("Bitcoin", "BNB Smart Chain (BEP20)"),
    "BNB": ("BNB Smart Chain (BEP20)",),
    "ETH": ("Ethereum (ERC20)", "Arbitrum", "Base", "Optimism", "BNB Smart Chain (BEP20)"),
    "SOL": ("Solana",),
    "TON": ("TON",),
    "XRP": ("XRP Ledger",),
}


def wallets(db, bot, currency=None, *, active_only=True):
    method = payment_methods.get(db, bot, "CRYPTO_MANUAL")
    return [
        dict(w)
        for w in (method.public_config.get("wallets", []) if method else [])
        if (not active_only or w.get("enabled")) and (currency is None or w["asset"] == currency)
    ]


def validate(values):
    result = {
        k: str(values.get(k, "")).strip()
        for k in ("asset", "network", "address", "memo", "instructions", "qr_file_id")
    }
    if result["asset"] not in ASSETS or not 2 <= len(result["network"]) <= 64:
        raise DomainError("INVALID_WALLET", "Revisa la moneda y la red de depósito.")
    if not re.fullmatch(r"[A-Za-z0-9:_-]{14,200}", result["address"]):
        raise DomainError("INVALID_ADDRESS", "Copia solo la dirección pública de depósito, sin espacios.")
    network, address = result["network"].lower(), result["address"]
    pattern = None
    if any(
        name in network
        for name in ("ethereum", "erc20", "bep20", "smart chain", "arbitrum", "base", "optimism", "polygon")
    ):
        pattern = r"0x[0-9a-fA-F]{40}"
    elif "tron" in network or "trc20" in network:
        pattern = r"T[1-9A-HJ-NP-Za-km-z]{33}"
    elif network == "bitcoin":
        pattern = r"(?:[13][1-9A-HJ-NP-Za-km-z]{25,34}|bc1[a-z0-9]{25,87})"
    elif network == "solana":
        pattern = r"[1-9A-HJ-NP-Za-km-z]{32,44}"
    elif network == "ton":
        pattern = r"(?:[EU]Q[A-Za-z0-9_-]{46}|(?:0|-1):[0-9a-fA-F]{64})"
    elif "xrp" in network:
        pattern = r"r[1-9A-HJ-NP-Za-km-z]{24,34}"
    if (pattern and not re.fullmatch(pattern, address)) or re.fullmatch(r"[0-9a-fA-F]{64}", address):
        raise DomainError(
            "INVALID_ADDRESS",
            "La dirección no coincide con el formato público de esta red. Copia los datos de depósito de tu billetera.",
        )
    if len(result["memo"]) > 128 or len(result["instructions"]) > 600 or len(result["qr_file_id"]) > 256:
        raise DomainError("INVALID_WALLET", "El memo o las instrucciones son demasiado largos.")
    return result


def save(db, bot, actor, values):
    values = validate(values)
    method = payment_methods.get(db, bot, "CRYPTO_MANUAL", True)
    rows = wallets(db, bot, active_only=False)
    if len(rows) >= 20:
        raise DomainError("WALLET_LIMIT", "Puedes guardar hasta 20 direcciones por bot.")
    if any(all(w[k] == values[k] for k in ("asset", "network", "address", "memo")) for w in rows):
        raise DomainError("WALLET_EXISTS", "Esta dirección y red ya están guardadas.")
    wallet = {**values, "id": uid(), "enabled": True}
    method.public_config = {**method.public_config, "wallets": rows + [wallet]}
    audit(
        db,
        bot.tenant_id,
        actor,
        "CRYPTO_WALLET_ADDED",
        wallet["id"],
        {"bot_id": bot.id, "asset": wallet["asset"], "network": wallet["network"]},
    )
    return wallet


def snapshot(db, bot, currency, wallet_id):
    matches = [w for w in wallets(db, bot, currency) if wallet_id is None or w["id"] == wallet_id]
    if len(matches) != 1:
        raise DomainError("WALLET_REQUIRED", "Selecciona una dirección y red disponibles para esta moneda.")
    return validate(matches[0]) | {"wallet_id": matches[0]["id"]}
