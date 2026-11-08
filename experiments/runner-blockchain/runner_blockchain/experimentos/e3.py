"""Experimento E3 — Tokenizacion sin doble venta (R4).

E3 valida de extremo a extremo que el escrow garantiza **exactamente una venta por oferta**
bajo compras concurrentes y que la tokenizacion **conserva los kWh**. El flujo por
repeticion es:

1. Publicar **1 oferta Activa** via `ms_venta` (`POST /ofertas` ->
   `MarketEscrow.publicar(vendedor, id, kwh)`, que devuelve `ofertaId`).
2. Lanzar **100 compras concurrentes** sobre esa oferta via el modo concurrente de
   `ms_compra` (`POST /compras/concurrentes` -> envio en paralelo con nonces explicitos).
   Para una oferta Activa, el escrow confirma **una** compra y revierte las 99 restantes
   con `OfertaNoDisponible` (lo garantiza el contrato, no el runner).
3. Repetir el escenario sobre **10 ofertas distintas** (cada repeticion una oferta nueva).

Al terminar, el runner recolecta la evidencia on-chain via el `Lector_Eventos` (R6) y
calcula las metricas y el veredicto (R4.4–R4.9):

* **Ventas exitosas por oferta:** exactamente 1 evento `Compra` por oferta (R4.4).
* **Dobles ventas:** toda oferta con ≥2 eventos `Compra` cuenta como doble venta; el total
  debe ser 0 (R4.4, R4.5).
* **Gas por operacion:** se suma el `gasUsed` del recibo de cada operacion on-chain (R4.7).
* **Conservacion de kWh:** la suma de kWh tokenizados (eventos `Emitido`) debe ser
  exactamente igual a la suma de kWh validados, con diferencia absoluta 0 (R4.6).
* **Veredicto PASS** solo si ventas==1 por oferta en las 10 repeticiones, dobles ventas==0
  y conservacion de kWh del 100% (R4.8); FAIL en cualquier otro caso, registrando la
  metrica incumplida con su valor y umbral (R7.5).

Reproducibilidad (R7.4): la generacion de casos (ofertas, vendedores, compradores) usa una
**semilla fija derivada del `runId` y los parametros**, de modo que la misma corrida produce
el mismo dataset y el mismo veredicto.

Frontera on/off-chain: la atomicidad de la venta y la emision viven on-chain (contratos
`MarketEscrow`/`EnergyToken`); E3 solo dispara las operaciones a traves de los
microservicios reales y mide el resultado observado on-chain.
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..eventos.lector import EventoOnChain, LectorEventos, LectorEventosError
from .. import progreso
from ..reporte_modelo import ExperimentResult, now_iso

logger = logging.getLogger(__name__)

# --- Parametros del escenario E3 (fijos por el requisito R4.1) ---------------------------
REPETICIONES = 10          # ofertas distintas (R4.1)
COMPRAS_POR_OFERTA = 100   # compras concurrentes por oferta (R4.1)
KWH_POR_OFERTA = 100       # kWh tokenizados/validados por oferta (constante, conservacion R4.6)
PRECIO_POR_KWH = 10        # precio por kWh fijado al emitir cada token (debe ser > 0)

# URLs por defecto de los microservicios (puertos del repo: ms_venta 8083, ms_compra 8084).
DEFAULT_MS_VENTA_URL = "http://127.0.0.1:8083"
DEFAULT_MS_COMPRA_URL = "http://127.0.0.1:8084"
HTTP_TIMEOUT_S = 300  # las 100 compras concurrentes (cada una espera recibo) pueden tardar; tope holgado por lote.


# =========================================================================================
# Puertos de los microservicios (inyectables para pruebas con dobles)
# =========================================================================================
class VentaClientLike(Protocol):
    """Lo que E3 necesita de `ms_venta`: publicar una oferta Activa y obtener su `ofertaId`."""

    def publicar(self, vendedor: str, token_id: int, kwh: int) -> int | None:
        ...


class CompraClientLike(Protocol):
    """Lo que E3 necesita de `ms_compra`: disparar N compras concurrentes sobre una oferta."""

    def comprar_concurrente(self, oferta_id: int, compradores: list[str]) -> list[dict[str, Any]]:
        ...


class HttpVentaClient:
    """Cliente HTTP de `ms_venta` (`POST /ofertas`)."""

    def __init__(self, base_url: str = DEFAULT_MS_VENTA_URL, *, timeout_s: int = HTTP_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def publicar(self, vendedor: str, token_id: int, kwh: int) -> int | None:
        cuerpo = {"vendedor": _checksum(vendedor), "id": int(token_id), "kwh": int(kwh)}
        respuesta = _post_json(f"{self.base_url}/ofertas", cuerpo, self.timeout_s)
        oferta_id = respuesta.get("ofertaId")
        return int(oferta_id) if oferta_id is not None else None


class HttpCompraClient:
    """Cliente HTTP de `ms_compra` (`POST /compras/concurrentes`)."""

    def __init__(self, base_url: str = DEFAULT_MS_COMPRA_URL, *, timeout_s: int = HTTP_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def comprar_concurrente(self, oferta_id: int, compradores: list[str]) -> list[dict[str, Any]]:
        cuerpo = {"ofertaId": int(oferta_id), "compradores": [_checksum(c) for c in compradores]}
        respuesta = _post_json(f"{self.base_url}/compras/concurrentes", cuerpo, self.timeout_s)
        resultados = respuesta.get("resultados")
        return list(resultados) if isinstance(resultados, list) else []


class SembradorLike(Protocol):
    """Siembra el estado on-chain de una oferta antes de publicarla.

    `MarketEscrow.publicar` exige que el token `id` tenga precio configurado y que el
    vendedor posea los kWh (los bloquea en el escrow). Antes de publicar hay que emitir esos
    kWh al vendedor via `EnergyToken.emitir` (que ademas fija el precio en la primera
    emision del id). El modelo custodial autoriza al mercado a mover los tokens del vendedor,
    asi que basta la emision previa; no hace falta approve.
    """

    def emitir(self, vendedor: str, token_id: int, kwh: int, precio: int) -> int | None:
        """Emite `kwh` del token `token_id` al `vendedor`. Devuelve kWh emitidos o None si fallo."""
        ...


class ChainSembrador:
    """Siembra via el `ChainClient` comun: `EnergyToken.emitir(vendedor, id, kwh, precio, lecturaId)`.

    Firma de forma custodial con la llave de la plataforma (igual que ms_energia) y espera la
    confirmacion on-chain. Es la preparacion de estado necesaria para que `publicar` no revierta
    por `TokenSinPrecio` ni por balance insuficiente del vendedor.
    """

    def __init__(self, chain: Any, *, precio: int = PRECIO_POR_KWH) -> None:
        self._chain = chain
        self._precio = precio

    def emitir(self, vendedor: str, token_id: int, kwh: int, precio: int | None = None) -> int | None:
        from web3 import Web3

        precio_final = self._precio if precio is None else precio
        destino = Web3.to_checksum_address(vendedor)
        # lecturaId es solo trazabilidad del evento Emitido; aqui se deriva del (token, vendedor).
        lectura_id = Web3.keccak(text=f"e3-seed-{token_id}-{vendedor}")
        fn = self._chain.energy_token.functions.emitir(
            destino, int(token_id), int(kwh), int(precio_final), lectura_id
        )
        tx = fn.build_transaction({"from": self._chain.plataforma, "nonce": self._chain.siguiente_nonce()})
        resultado = self._chain.enviar_y_esperar(tx)
        if getattr(resultado, "confirmada", False):
            return int(kwh)
        logger.warning("E3 seed: la emision del token %s al vendedor %s no confirmo (%s)",
                       token_id, vendedor, getattr(getattr(resultado, "estado", None), "value", resultado))
        return None


def _post_json(url: str, payload: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    """POST JSON y devuelve el cuerpo JSON de la respuesta (dict). Acepta 2xx y 4xx de dominio."""
    datos = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=datos, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (URL interna controlada)
            crudo = resp.read()
    except urllib.error.HTTPError as exc:
        # ms_compra responde 409 por reversion/timeout y ms_venta 502 ante fallo on-chain:
        # el cuerpo sigue siendo JSON util para el analisis, no es un fallo de transporte.
        crudo = exc.read()
    except (urllib.error.URLError, OSError) as exc:  # servicio no disponible
        raise E3Error(f"no se pudo contactar {url}: {exc}") from exc
    try:
        cuerpo = json.loads(crudo) if crudo else {}
    except ValueError as exc:
        raise E3Error(f"respuesta no-JSON de {url}: {exc}") from exc
    return cuerpo if isinstance(cuerpo, dict) else {"resultados": cuerpo}


# =========================================================================================
# Generacion de casos por semilla fija (reproducible, R7.4)
# =========================================================================================
@dataclass(frozen=True)
class CasoOferta:
    """Una oferta del escenario E3 con sus compradores concurrentes.

    * `indice`: 0..9 (repeticion).
    * `vendedor`: direccion del vendedor de la oferta.
    * `token_id`: id de token (fuente+epoca) distinto por oferta.
    * `kwh`: kWh de la oferta (constante `KWH_POR_OFERTA`; base de la conservacion).
    * `compradores`: 100 direcciones distintas que compiten por la oferta.
    """

    indice: int
    vendedor: str
    token_id: int
    kwh: int
    compradores: list[str]


def _addr_desde_semilla(semilla: str, etiqueta: str, n: int) -> str:
    """Direccion EVM (20 bytes, checksum-less) derivada de forma determinista de la semilla.

    Usa SHA-256 sobre `semilla|etiqueta|n` y toma los 20 bytes finales. Es solo para
    identificar participantes de forma reproducible en el dataset; no es una cuenta con
    llave (el modelo es custodial: la plataforma firma todas las tx).
    """
    h = hashlib.sha256(f"{semilla}|{etiqueta}|{n}".encode()).hexdigest()
    return "0x" + h[-40:]


def generar_casos(
    run_id: str,
    *,
    repeticiones: int = REPETICIONES,
    compras_por_oferta: int = COMPRAS_POR_OFERTA,
    kwh_por_oferta: int = KWH_POR_OFERTA,
    params: dict[str, Any] | None = None,
) -> list[CasoOferta]:
    """Genera `repeticiones` ofertas distintas con `compras_por_oferta` compradores cada una.

    La semilla se deriva del `run_id` y de los parametros para que dos corridas con los
    mismos parametros produzcan el mismo dataset (R7.4). Cada oferta usa un `token_id`
    distinto (no reutilizado en repeticiones previas, R4.1) y compradores distintos.
    """
    semilla = _semilla(run_id, params or {}, repeticiones, compras_por_oferta, kwh_por_oferta)
    casos: list[CasoOferta] = []
    for i in range(repeticiones):
        vendedor = _addr_desde_semilla(semilla, f"vendedor-{i}", i)
        compradores = [
            _addr_desde_semilla(semilla, f"comprador-{i}", j) for j in range(compras_por_oferta)
        ]
        casos.append(
            CasoOferta(
                indice=i,
                vendedor=vendedor,
                token_id=_token_id(i),
                kwh=kwh_por_oferta,
                compradores=compradores,
            )
        )
    return casos


def _semilla(
    run_id: str,
    params: dict[str, Any],
    repeticiones: int,
    compras_por_oferta: int,
    kwh_por_oferta: int,
) -> str:
    """Semilla fija derivada del runId + parametros (determinista y estable)."""
    base = json.dumps(
        {
            "runId": run_id,
            "params": params,
            "repeticiones": repeticiones,
            "comprasPorOferta": compras_por_oferta,
            "kwhPorOferta": kwh_por_oferta,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(base.encode()).hexdigest()


def _token_id(indice: int) -> int:
    """Id de token distinto por oferta (base fija + indice; no reutilizado entre repeticiones)."""
    return 3_000_000 + indice


# =========================================================================================
# Metricas y analisis de evidencia on-chain
# =========================================================================================
@dataclass
class MetricasE3:
    """Metricas agregadas de E3 derivadas de la evidencia on-chain (R4.4–R4.9)."""

    ventas_por_oferta: dict[int, int] = field(default_factory=dict)
    dobles_ventas: int = 0
    ofertas_con_una_venta: int = 0
    kwh_tokenizados: int = 0
    kwh_validados: int = 0
    gas_por_operacion: list[dict[str, Any]] = field(default_factory=list)
    gas_total: int = 0

    @property
    def diff_kwh(self) -> int:
        """Diferencia absoluta entre kWh tokenizados y validados (debe ser 0, R4.6)."""
        return abs(self.kwh_tokenizados - self.kwh_validados)

    @property
    def conservacion_pct(self) -> float:
        """Conservacion de kWh en porcentaje (100.0 si tokenizados == validados, R4.6)."""
        if self.kwh_validados == 0:
            return 100.0 if self.kwh_tokenizados == 0 else 0.0
        return 100.0 * self.kwh_tokenizados / self.kwh_validados

    def as_dict(self) -> dict[str, Any]:
        return {
            "ventasPorOferta": {str(k): v for k, v in sorted(self.ventas_por_oferta.items())},
            "doblesVentas": self.dobles_ventas,
            "ofertasConUnaVenta": self.ofertas_con_una_venta,
            "kwhTokenizados": self.kwh_tokenizados,
            "kwhValidados": self.kwh_validados,
            "diffKwh": self.diff_kwh,
            "conservacionKwhPct": round(self.conservacion_pct, 6),
            "gasTotal": self.gas_total,
            "gasPorOperacion": self.gas_por_operacion,
        }


def analizar_evidencia(
    eventos: list[EventoOnChain],
    ofertas_esperadas: list[int],
    kwh_validados: int,
    tokens_esperados: list[int] | None = None,
) -> MetricasE3:
    """Calcula las metricas de E3 a partir de los eventos `Compra`/`Emitido` observados.

    * Cuenta `Compra` por `ofertaId` para las ofertas del escenario (R4.4): exactamente 1
      es venta valida; ≥2 es doble venta (R4.5).
    * Suma kWh tokenizados de los eventos `Emitido` (R4.6) y los compara con `kwh_validados`.
    * Suma el gas (`gasUsed`) de cada operacion on-chain observada (R4.7).
    """
    m = MetricasE3(kwh_validados=kwh_validados)
    esperadas = set(ofertas_esperadas)
    # kWh tokenizados: solo las emisiones de los token_ids de E3 (evita mezclar Emitido de
    # otros experimentos que compartan la misma cadena/rango de bloques).
    tokens_e3 = set(tokens_esperados) if tokens_esperados is not None else None
    m.ventas_por_oferta = {oid: 0 for oid in ofertas_esperadas}

    for ev in eventos:
        if ev.gas_used is not None:
            m.gas_total += int(ev.gas_used)
            m.gas_por_operacion.append(
                {
                    "tipo": ev.tipo,
                    "ofertaId": ev.args.get("ofertaId"),
                    "transactionHash": ev.transaction_hash,
                    "blockNumber": ev.block_number,
                    "gasUsed": int(ev.gas_used),
                }
            )
        if ev.tipo == "Compra":
            oid = _opt_int(ev.args.get("ofertaId"))
            if oid is not None and oid in esperadas:
                m.ventas_por_oferta[oid] = m.ventas_por_oferta.get(oid, 0) + 1
        elif ev.tipo == "Emitido":
            token = _opt_int(ev.args.get("id"))
            if tokens_e3 is None or (token is not None and token in tokens_e3):
                m.kwh_tokenizados += _opt_int(ev.args.get("kwh")) or 0

    m.ofertas_con_una_venta = sum(1 for c in m.ventas_por_oferta.values() if c == 1)
    m.dobles_ventas = sum(1 for c in m.ventas_por_oferta.values() if c >= 2)
    return m


# =========================================================================================
# Ejecucion del experimento
# =========================================================================================
class E3Error(RuntimeError):
    """Fallo irrecuperable al ejecutar E3 (servicio inalcanzable, evidencia no legible)."""


@dataclass
class ResultadoEjecucionE3:
    """Resultado de disparar el escenario (ofertas publicadas + desenlaces de compra).

    Es el insumo para el analisis de evidencia y para las notas del `ExperimentResult`.
    """

    ofertas: list[int] = field(default_factory=list)
    tokens: list[int] = field(default_factory=list)
    publicaciones_fallidas: list[int] = field(default_factory=list)
    confirmadas_reportadas: dict[int, int] = field(default_factory=dict)
    kwh_validados: int = 0


def ejecutar_escenario(
    casos: list[CasoOferta],
    venta: VentaClientLike,
    compra: CompraClientLike,
    sembrador: "SembradorLike | None" = None,
) -> ResultadoEjecucionE3:
    """Publica cada oferta y dispara sus 100 compras concurrentes (R4.1).

    Devuelve los `ofertaId` on-chain publicados, las publicaciones que no confirmaron y, por
    oferta, cuantas compras reporto `ms_compra` como confirmadas (evidencia auxiliar; la
    verdad on-chain la da el `Lector_Eventos`). `kwh_validados` acumula los kWh de cada
    oferta efectivamente publicada (base de la conservacion, R4.6).
    """
    out = ResultadoEjecucionE3()
    total = len(casos)
    progreso.emitir("inyeccion", f"E3: publicando {total} ofertas y disparando compras", exp="E3",
                    ofertas=total)
    for caso in casos:
        # Siembra on-chain: emitir los kWh de la oferta al vendedor (fija precio + da balance)
        # para que publicar() no revierta por TokenSinPrecio ni por balance insuficiente.
        if sembrador is not None:
            emitidos = sembrador.emitir(caso.vendedor, caso.token_id, caso.kwh, PRECIO_POR_KWH)
            if emitidos is None:
                logger.warning("E3: no se pudo sembrar (emitir) la oferta %d (token %d)", caso.indice, caso.token_id)
                out.publicaciones_fallidas.append(caso.indice)
                continue
        oferta_id = venta.publicar(caso.vendedor, caso.token_id, caso.kwh)
        if oferta_id is None:
            logger.warning("E3: la oferta %d (token %d) no se pudo publicar", caso.indice, caso.token_id)
            out.publicaciones_fallidas.append(caso.indice)
            continue
        out.ofertas.append(oferta_id)
        out.tokens.append(caso.token_id)
        out.kwh_validados += caso.kwh
        progreso.emitir("inyeccion", f"E3: oferta {len(out.ofertas)}/{total} publicada (id={oferta_id}), "
                        f"disparando {len(caso.compradores)} compras concurrentes", exp="E3",
                        ofertaId=oferta_id, publicadas=len(out.ofertas), ofertas=total,
                        comprasPorOferta=len(caso.compradores))
        resultados = compra.comprar_concurrente(oferta_id, caso.compradores)
        out.confirmadas_reportadas[oferta_id] = sum(
            1 for r in resultados if isinstance(r, dict) and r.get("exito")
        )
    return out


def evaluar(
    run_id: str,
    metricas: MetricasE3,
    ejecucion: ResultadoEjecucionE3,
    *,
    repeticiones: int,
    compras_por_oferta: int,
    eventos: list[EventoOnChain],
    params: dict[str, Any] | None = None,
) -> ExperimentResult:
    """Construye el `ExperimentResult` de E3 con sus criterios PASS/FAIL (R4.8, R4.9, R7).

    Criterios:
      * R4.4 — exactamente 1 `Compra` por oferta en las 10 repeticiones.
      * R4.5 — dobles ventas totales == 0.
      * R4.6 — conservacion de kWh del 100% (diff absoluta 0).
      * R4.1 — las 10 ofertas se publicaron (no quedan publicaciones fallidas).
    El veredicto global es PASS solo si todos los criterios cuantitativos pasan (R4.8).
    """
    r = ExperimentResult(
        experiment="E3",
        title="E3 — Tokenizacion sin doble venta",
        hypothesis=(
            "Bajo 100 compras concurrentes sobre una misma oferta Activa, el escrow confirma "
            "exactamente una venta y revierte el resto; repetido sobre 10 ofertas, no hay dobles "
            "ventas y los kWh tokenizados igualan a los validados."
        ),
        started=now_iso(),
    )
    r.params = {
        "runId": run_id,
        "repeticiones": repeticiones,
        "comprasPorOferta": compras_por_oferta,
        "kwhPorOferta": KWH_POR_OFERTA,
        **(params or {}),
    }

    ofertas_publicadas = len(ejecucion.ofertas)
    todas_publicadas = not ejecucion.publicaciones_fallidas and ofertas_publicadas == repeticiones
    r.add(
        "R4.1",
        "Se publicaron las 10 ofertas distintas y se dispararon las 100 compras concurrentes",
        todas_publicadas,
        expected=f"{repeticiones} ofertas publicadas",
        observed=f"{ofertas_publicadas} publicadas, {len(ejecucion.publicaciones_fallidas)} fallidas",
    )

    # R4.4: exactamente 1 Compra por oferta.
    ventas_ok = (
        ofertas_publicadas > 0
        and metricas.ofertas_con_una_venta == ofertas_publicadas
        and all(c == 1 for c in metricas.ventas_por_oferta.values())
    )
    r.add(
        "R4.4",
        "Exactamente 1 evento Compra por oferta",
        ventas_ok,
        expected="1 venta por oferta en todas las ofertas",
        observed=f"{metricas.ofertas_con_una_venta}/{ofertas_publicadas} ofertas con exactamente 1 venta",
        ventasPorOferta={str(k): v for k, v in sorted(metricas.ventas_por_oferta.items())},
    )

    # R4.5: dobles ventas == 0.
    r.add(
        "R4.5",
        "Conteo total de dobles ventas igual a 0",
        metricas.dobles_ventas == 0,
        expected="0 dobles ventas",
        observed=f"{metricas.dobles_ventas} dobles ventas",
    )

    # R4.6: conservacion de kWh (diff absoluta 0).
    r.add(
        "R4.6",
        "Conservacion de kWh: tokenizados == validados (diff 0)",
        metricas.diff_kwh == 0,
        expected="diff absoluta 0 kWh (conservacion 100%)",
        observed=(
            f"tokenizados={metricas.kwh_tokenizados}, validados={metricas.kwh_validados}, "
            f"diff={metricas.diff_kwh}, conservacion={metricas.conservacion_pct:.2f}%"
        ),
    )

    # R4.7/R4.9: gas por operacion registrado (informativo; no condiciona PASS/FAIL por si solo).
    r.add(
        "R4.7",
        "Gas consumido registrado por operacion on-chain",
        len(metricas.gas_por_operacion) > 0 if eventos else None,
        expected="gasUsed por operacion",
        observed=f"{len(metricas.gas_por_operacion)} operaciones con gas, gasTotal={metricas.gas_total}",
    )

    r.data = {
        "metricas": metricas.as_dict(),
        "ofertas": ejecucion.ofertas,
        "publicacionesFallidas": ejecucion.publicaciones_fallidas,
        "confirmadasReportadasPorMsCompra": {
            str(k): v for k, v in ejecucion.confirmadas_reportadas.items()
        },
        "fronteraOnChain": "Compra/Emitido on-chain (MarketEscrow/EnergyToken); disparo off-chain via ms_venta/ms_compra",
        "evidencia": [e.as_dict() for e in eventos],
    }
    r.finished = now_iso()
    return r


def ejecutar_e3(
    run_id: str,
    lector: LectorEventos,
    *,
    venta: VentaClientLike | None = None,
    compra: CompraClientLike | None = None,
    sembrador: "SembradorLike | None" = None,
    sembrar: bool = True,
    from_block: int | str = 0,
    to_block: int | str = "latest",
    repeticiones: int = REPETICIONES,
    compras_por_oferta: int = COMPRAS_POR_OFERTA,
    kwh_por_oferta: int = KWH_POR_OFERTA,
    params: dict[str, Any] | None = None,
) -> ExperimentResult:
    """Ejecuta E3 completo: genera casos, dispara el escenario, lee evidencia y evalua (R4).

    * `run_id`: identificador de la corrida (semilla y trazado de eventos).
    * `lector`: `Lector_Eventos` ya configurado con las direcciones de `deployment.json`.
    * `venta` / `compra`: clientes de `ms_venta` / `ms_compra`; por defecto los HTTP reales.
    * `from_block`: bloque desde el que leer eventos (idealmente el previo al inicio de E3).

    Devuelve el `ExperimentResult` con veredicto PASS/FAIL. Si la cadena no responde a la
    lectura de eventos (R6.4), el resultado queda en FAIL con el error registrado.
    """
    venta = venta if venta is not None else HttpVentaClient()
    compra = compra if compra is not None else HttpCompraClient()
    # Sembrador por defecto: usa el ChainClient del lector para emitir tokens on-chain antes
    # de publicar. Se puede desactivar (sembrar=False) o inyectar uno falso en pruebas.
    if sembrador is None and sembrar:
        sembrador = ChainSembrador(lector.client)

    casos = generar_casos(
        run_id,
        repeticiones=repeticiones,
        compras_por_oferta=compras_por_oferta,
        kwh_por_oferta=kwh_por_oferta,
        params=params,
    )
    ejecucion = ejecutar_escenario(casos, venta, compra, sembrador)

    try:
        eventos = lector.leer_eventos(run_id, from_block=from_block, to_block=to_block)
    except LectorEventosError as exc:
        logger.error("E3: no se pudo leer la evidencia on-chain: %s", exc)
        r = ExperimentResult(
            experiment="E3",
            title="E3 — Tokenizacion sin doble venta",
            hypothesis="Exactamente una venta por oferta bajo concurrencia; conservacion de kWh.",
            started=now_iso(),
            finished=now_iso(),
            error=f"indisponibilidad de la Cadena_Local al leer eventos: {exc}",
        )
        r.params = {"runId": run_id, "repeticiones": repeticiones, "comprasPorOferta": compras_por_oferta}
        return r

    metricas = analizar_evidencia(
        eventos, ejecucion.ofertas, ejecucion.kwh_validados, tokens_esperados=ejecucion.tokens
    )
    return evaluar(
        run_id,
        metricas,
        ejecucion,
        repeticiones=repeticiones,
        compras_por_oferta=compras_por_oferta,
        eventos=eventos,
        params=params,
    )


def _checksum(direccion: str) -> str:
    """Normaliza una direccion a checksum EIP-55 (web3 lo exige en los argumentos)."""
    from web3 import Web3

    return Web3.to_checksum_address(direccion)


def _opt_int(value: Any) -> int | None:
    """Convierte a int si es posible; None en otro caso."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
