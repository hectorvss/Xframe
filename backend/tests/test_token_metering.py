"""
Tests de la medición de tokens del agente → créditos (`app/agent/metering.py`).

Tres propiedades que se pagan en dinero si fallan:

1. El precio de tokens es el del modelo concreto, y las lecturas cacheadas se cobran a su
   tarifa reducida, no a la del input normal.
2. `debit_tokens` mueve el libro (kind 'tokens', importe negativo) y puede dejar el saldo
   en negativo: el coste ya se incurrió y negarlo perdería la traza.
3. `meter_tokens` nunca rompe el turno: sin uso medible o ante un fallo, devuelve 0.

Se reutiliza el doble de base de datos de `test_jobs` (mismo libro append-only).
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test/test")

from app.agent import metering
from app.jobs import credits
from tests.test_jobs import FakeDB, install_fake_db, run


def _profile(db: FakeDB, balance: int) -> Any:
    from uuid import uuid4

    pid = uuid4()
    db.profiles[pid] = {"id": pid, "credits": balance}
    return pid


# --------------------------------------------------------------------------- #
# 1. Precio de tokens                                                          #
# --------------------------------------------------------------------------- #


def test_token_cost_prices_by_model_and_discounts_cache() -> None:
    # Opus: 5 $/M input, 25 $/M output. 100k input + 10k output = 0.5 + 0.25 = 0.75 USD.
    cost = metering.token_cost_usd(
        "claude-opus-4-8", {"input_tokens": 100_000, "output_tokens": 10_000}
    )
    assert cost == Decimal("0.75")

    # 40k input de los cuales 30k son lectura cacheada (0.5 $/M) y 10k normales (5 $/M),
    # más 5k output (25 $/M): 10k*5 + 30k*0.5 + 5k*25 = 50000+15000+125000 (µUSD) → 0.19.
    cached = metering.token_cost_usd(
        "claude-opus-4-8",
        {
            "input_tokens": 40_000,
            "output_tokens": 5_000,
            "input_token_details": {"cache_read": 30_000},
        },
    )
    assert cached == Decimal("0.19")


def test_unknown_model_falls_back_to_config_default_never_zero() -> None:
    # Un modelo que no está en la tabla no se mide a 0: usa el default de la config.
    price = metering.price_for("un-modelo-que-no-existe-9000")
    assert price.input_per_mtok > 0 and price.output_per_mtok > 0
    cost = metering.token_cost_usd(
        "un-modelo-que-no-existe-9000", {"input_tokens": 1_000_000, "output_tokens": 0}
    )
    assert cost == price.input_per_mtok  # 1M input exacto = precio de 1M


# --------------------------------------------------------------------------- #
# 2. Débito en el libro                                                        #
# --------------------------------------------------------------------------- #


def test_debit_tokens_moves_the_ledger_and_can_go_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDB()
    install_fake_db(monkeypatch, db)
    pid = _profile(db, balance=50)

    after = run(credits.debit_tokens(pid, 30, "tokens root claude-opus: 1 in / 1 out"))
    assert after == 20
    assert run(credits.balance(pid)) == 20
    row = db.ledger[-1]
    assert row["kind"] == "tokens" and row["amount"] == -30

    # El coste ya se incurrió: cobra aunque deje el saldo en negativo (corta el siguiente
    # gasto, no este). El espejo profiles.credits se satura a 0.
    run(credits.debit_tokens(pid, 100, "otro turno caro"))
    assert run(credits.balance(pid)) == -80
    assert db.profiles[pid]["credits"] == 0


def test_debit_tokens_zero_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    install_fake_db(monkeypatch, db)
    pid = _profile(db, balance=10)
    before = len(db.ledger)
    # No escribe fila: un turno de coste 0 (cacheado o vacío) no es un movimiento.
    run(credits.debit_tokens(pid, 0, "turno cacheado"))
    assert len(db.ledger) == before


# --------------------------------------------------------------------------- #
# 3. meter_tokens end-to-end (respuesta → créditos), robusto                   #
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, usage: dict[str, Any] | None) -> None:
        self.usage_metadata = usage


def test_meter_tokens_charges_the_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    install_fake_db(monkeypatch, db)
    pid = _profile(db, balance=1000)

    # Opus, 40k in + 4k out = 0.20 + 0.10 = 0.30 USD → usd_to_credits(0.30) al K vigente.
    response = _FakeResponse({"input_tokens": 40_000, "output_tokens": 4_000})
    charged = run(
        metering.meter_tokens(
            response, profile_id=str(pid), model_name="claude-opus-4-8", purpose="root"
        )
    )
    expected = credits.usd_to_credits(Decimal("0.30"))
    assert charged == expected
    assert run(credits.balance(pid)) == 1000 - expected
    assert db.ledger[-1]["kind"] == "tokens"


def test_meter_tokens_without_usage_is_zero_and_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDB()
    install_fake_db(monkeypatch, db)
    pid = _profile(db, balance=1000)

    charged = run(
        metering.meter_tokens(
            _FakeResponse(None), profile_id=str(pid), model_name="claude-opus-4-8", purpose="root"
        )
    )
    assert charged == 0
    assert db.ledger == [], "sin uso medible no se escribe nada en el libro"
