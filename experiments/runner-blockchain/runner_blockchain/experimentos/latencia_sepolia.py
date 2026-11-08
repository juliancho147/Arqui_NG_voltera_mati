"""Medicion de latencia real en Sepolia (acuse e inclusion) — R2.8/R3.10 (lamina 13).

Corre un subconjunto pequeno de operaciones reales en la testnet Sepolia y mide dos latencias
por transaccion:
  * ACUSE     : desde que se envia la tx firmada hasta que el RPC devuelve el hash (recepcion).
  * INCLUSION : desde el envio hasta que la tx queda incluida en un bloque (recibo).
Calcula el p95 de cada una y lo compara contra los umbrales de la lamina 13:
  * p95 acuse     <= 2 s
  * p95 inclusion <= 60 s

SEGURIDAD: NO hardcodea credenciales. Lee de entorno:
  * SEPOLIA_RPC_URL           (p.ej. Infura/Alchemy)
  * PLATAFORMA_PRIVATE_KEY    (cuenta con ETH de faucet; se usa SOLO en testnet)
  * deployment-sepolia.json   (direcciones desplegadas en Sepolia)
Gasta gas de testnet real: por eso el subconjunto por defecto es 20 emisiones + 10 compras.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..reporte_modelo import ExperimentResult, now_iso

P95_ACUSE_S = 2.0
P95_INCLUSION_S = 60.0


def _p95(muestras: list[float]) -> float:
    if not muestras:
        return 0.0
    o = sorted(muestras)
    i = max(1, int(-(-95 * len(o) // 100))) - 1  # nearest-rank
    return o[i]


@dataclass
class Medicion:
    op: str
    acuse_s: float
    inclusion_s: float
    tx_hash: str
    estado: str


def _enviar_y_medir(chain: Any, op: str, fn_tx: dict[str, Any]) -> Medicion:
    """Envia una tx ya construida y mide acuse (envio->hash) e inclusion (envio->recibo)."""
    t0 = time.monotonic()
    tx_hash = chain.enviar_tx(fn_tx)          # firma + send_raw_transaction
    t_acuse = time.monotonic()
    rec = chain.esperar_recibo(tx_hash, 120)  # tope holgado para testnet
    t_inc = time.monotonic()
    return Medicion(op=op, acuse_s=t_acuse - t0, inclusion_s=t_inc - t0,
                    tx_hash=getattr(rec, "transactionHash", tx_hash),
                    estado=getattr(getattr(rec, "estado", None), "value", "desconocido"))


def ejecutar(chain: Any, *, run_id: str = "RUN-SEPOLIA",
             emisiones: int = 20, compras: int = 10) -> ExperimentResult:
    """Corre `emisiones` emisiones + `compras` compras en Sepolia y evalua p95 acuse/inclusion."""
    import hashlib
    from web3 import Web3

    r = ExperimentResult(
        experiment="SEPOLIA",
        title="Latencia real en Sepolia (acuse / inclusion)",
        hypothesis="En Sepolia, p95 de acuse <= 2 s y p95 de inclusion <= 60 s (lamina 13).",
        started=now_iso(),
    )
    et, me, plat = chain.energy_token, chain.market_escrow, chain.plataforma
    mediciones: list[Medicion] = []

    def addr(e): 
        h = hashlib.sha256(f"sep-{e}".encode()).hexdigest()
        return Web3.to_checksum_address("0x" + h[-40:])

    # Emisiones (acuse/inclusion por emitir)
    for i in range(emisiones):
        token = 9_000_000 + i
        tx = et.functions.emitir(addr(f"a{i}"), token, 100, 10, Web3.keccak(text=f"sep-{i}")
            ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()})
        mediciones.append(_enviar_y_medir(chain, "emitir", tx))

    # Compras: montar oferta y comprar (mide la compra)
    for j in range(compras):
        token = 9_500_000 + j
        v, c = addr(f"v{j}"), addr(f"c{j}")
        chain.enviar_y_esperar(et.functions.emitir(v, token, 100, 10, Web3.keccak(text=f"sv-{j}")
            ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()}))
        h = chain.enviar_tx(me.functions.publicar(v, token, 100
            ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()}))
        chain.esperar_recibo(h, 120)
        recibo = chain.w3.eth.get_transaction_receipt(h)
        oferta = int(me.events.OfertaPublicada().process_receipt(recibo)[0]["args"]["ofertaId"])
        tx = me.functions.comprar(oferta, c).build_transaction(
            {"from": plat, "nonce": chain.siguiente_nonce()})
        mediciones.append(_enviar_y_medir(chain, "comprar", tx))

    acuses = [m.acuse_s for m in mediciones]
    incls = [m.inclusion_s for m in mediciones]
    p95_acuse, p95_incl = _p95(acuses), _p95(incls)

    r.add("LAT-ACUSE", "p95 de acuse (envio -> hash)", ok=(p95_acuse <= P95_ACUSE_S),
          expected=f"p95 <= {P95_ACUSE_S} s", observed=f"p95 = {p95_acuse:.3f} s sobre {len(acuses)} tx")
    r.add("LAT-INCL", "p95 de inclusion (envio -> recibo)", ok=(p95_incl <= P95_INCLUSION_S),
          expected=f"p95 <= {P95_INCLUSION_S} s", observed=f"p95 = {p95_incl:.3f} s sobre {len(incls)} tx")
    r.params = {"runId": run_id, "emisiones": emisiones, "compras": compras,
                "red": "sepolia", "umbralAcuseS": P95_ACUSE_S, "umbralInclusionS": P95_INCLUSION_S}
    r.data = {"mediciones": [m.__dict__ for m in mediciones],
              "p95AcuseS": round(p95_acuse, 4), "p95InclusionS": round(p95_incl, 4)}
    r.finished = now_iso()
    return r
