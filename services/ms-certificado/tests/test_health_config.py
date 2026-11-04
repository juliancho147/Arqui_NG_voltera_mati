"""Pruebas de config y health de ms_certificado (sin exponer credenciales, R3.4)."""
from __future__ import annotations

import config as config_mod
from config import cargar_config
from health import estado_salud


def test_config_sin_pinata_usa_fallback(monkeypatch) -> None:
    monkeypatch.delenv("PINATA_JWT", raising=False)
    cfg = cargar_config()
    assert cfg.pinata_habilitado is False
    assert cfg.pinata_gateway.endswith("/")


def test_config_con_pinata_habilitado(monkeypatch) -> None:
    monkeypatch.setenv("PINATA_JWT", "  secreto  ")
    cfg = cargar_config()
    assert cfg.pinata_habilitado is True
    assert cfg.pinata_jwt == "secreto"


def test_healthz_no_expone_credenciales(monkeypatch) -> None:
    monkeypatch.setenv("PINATA_JWT", "super-secreto")
    cfg = cargar_config()
    payload = estado_salud(cfg)
    assert payload["status"] == "ok"
    assert payload["service"] == "ms_certificado"
    # El JWT nunca debe aparecer en la carga de salud.
    assert "super-secreto" not in str(payload)
    assert payload["pinata"] == "habilitado"
