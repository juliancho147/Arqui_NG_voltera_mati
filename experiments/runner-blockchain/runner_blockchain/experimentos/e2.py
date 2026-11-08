"""E2 — Integridad del certificado off-chain (R3).

E2 valida que el anclaje off-chain detecta **toda** manipulacion de un certificado PDF sin
falsos positivos. El flujo del experimento (design.md, seccion "Flujo por experimento"):

1. Partir de certificados PDF **integros previamente anclados on-chain** (su CID queda
   grabado en `MarketEscrow` via `ms_certificado`).
2. Producir exactamente **50 Certificado_Alterado** repartidos en las tres formas de
   alteracion, con **al menos una por forma** (R3.1):
     * ``byte``       — se cambia un unico byte del PDF.
     * ``metadatos``  — se modifican los metadatos (se añade/edita el bloque de metadatos
                        del PDF) sin tocar el texto visible.
     * ``reemplazo``  — se reemplaza por completo el archivo por otro PDF distinto.
3. Verificar cada caso contra el CID anclado via `ms_certificado` (`POST /verificaciones`):
   un alterado debe dar ``ALTERADO`` (R3.5) y un integro ``INTEGRO`` (R3.7).
4. Medir la **latencia de verificacion** de cada caso con `time.monotonic` (R3.9),
   calcular la **tasa de deteccion** (debe ser 100%, R3.6), los **falsos positivos** (deben
   ser 0, R3.8) y la **Latencia_p95** (debe ser <= 3 s, R3.10), y asignar el veredicto
   PASS/FAIL registrando esas metricas (R3.13).

Generacion reproducible (R7.4): el dataset de alteraciones se deriva de una **semilla fija**
calculada a partir del `runId` y los parametros, de modo que dos corridas con los mismos
parametros producen exactamente las mismas alteraciones.

Frontera on/off-chain: el CID anclado es la huella on-chain (real, inmutable); la generacion
del PDF, el almacenamiento de contenido direccionable (Pinata o fallback local) y la
recomputacion por contenido son off-chain reales. E2 no usa stubs para lo que mide.

Para mantener el experimento ejecutable y testeable sin un servidor HTTP vivo, el flujo se
expresa contra un *backend* de certificados (`BackendCertificado`) con dos operaciones:
anclar un certificado integro y verificar una oferta. El cableado del runner (tarea 13)
puede inyectar un backend HTTP real contra `ms_certificado`; aqui se provee un backend
en-proceso (`BackendEnProceso`) que usa la logica de dominio real de `ms_certificado`
(`CertificadoService`) sobre el almacen de contenido direccionable compartido.
"""
from __future__ import annotations

import hashlib
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..chain.chain_client import build_chain_client
from ..chain.deployment import Deployment
from ..reporte_modelo import FAIL, PASS, ExperimentResult, now_iso
from .. import progreso

logger = logging.getLogger(__name__)

# experiments/runner-blockchain/runner_blockchain/experimentos/e2.py -> repo root
_ROOT = Path(__file__).resolve().parents[4]
_MS_CERTIFICADO_DIR = _ROOT / "services" / "ms-certificado"

# --- Parametros del experimento (R3.1, R3.10) -------------------------------------------
TOTAL_ALTERADOS = 50          # exactamente 50 Certificado_Alterado (R3.1)
FORMAS = ("byte", "metadatos", "reemplazo")  # tres formas de alteracion (R3.1)
P95_UMBRAL_S = 3.0            # Latencia_p95 de verificacion <= 3 s (R3.10)
VERIFICACION_TIMEOUT_S = 30   # indisponibilidad de la verificacion (consistente con R5.9)

# Veredictos que devuelve `ms_certificado` (ver certificado_service.Veredicto).
INTEGRO = "INTEGRO"
ALTERADO = "ALTERADO"
ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Dataset de alteraciones (reproducible por semilla fija)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CasoAlterado:
    """Un Certificado_Alterado del dataset de E2.

    * `oferta_id`: oferta cuyo certificado integro se anclo y luego se altera.
    * `forma`: forma de alteracion aplicada (`byte` | `metadatos` | `reemplazo`).
    * `pdf_original`: bytes del PDF integro anclado (su CID es el anclado on-chain).
    * `pdf_alterado`: bytes del PDF tras la alteracion (debe producir un CID distinto).
    * `datos_compra`: datos con los que se genero el PDF original (para trazabilidad).
    """

    oferta_id: int
    forma: str
    pdf_original: bytes
    pdf_alterado: bytes
    datos_compra: dict[str, Any] = field(default_factory=dict)


def semilla_desde(run_id: str, *partes: Any) -> int:
    """Deriva una semilla entera estable de `run_id` y parametros (reproducibilidad, R7.4).

    Usa sha2-256 sobre la concatenacion de las partes, de modo que los mismos parametros
    produzcan siempre la misma semilla y, por tanto, el mismo dataset de alteraciones.
    """
    base = "|".join([str(run_id), *[str(p) for p in partes]])
    digest = hashlib.sha256(base.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _asignar_formas(total: int, rng: random.Random) -> list[str]:
    """Reparte `total` alteraciones entre las tres formas con >=1 por forma (R3.1).

    Primero garantiza una instancia por forma; el resto se reparte de forma pseudoaleatoria
    determinista (controlada por `rng`) y luego se baraja para mezclar el orden.
    """
    if total < len(FORMAS):
        raise ValueError(f"se requieren al menos {len(FORMAS)} alterados (uno por forma); pedidos {total}")
    formas = list(FORMAS)  # una por forma, garantiza el minimo (R3.1)
    for _ in range(total - len(FORMAS)):
        formas.append(rng.choice(FORMAS))
    rng.shuffle(formas)
    return formas


def _generar_pdf(oferta_id: int, datos_compra: dict[str, Any]) -> bytes:
    """Genera el PDF determinista del certificado reusando el generador de `ms_certificado`.

    Importe diferido para no acoplar el import del modulo a `services/ms-certificado`; el
    cableado agrega esa ruta al `sys.path`. Si no estuviera disponible, se cae a un PDF
    minimo determinista equivalente (mismo contrato: mismos datos -> mismos bytes).
    """
    try:
        from pdf import generar_pdf  # type: ignore[import-not-found]

        return generar_pdf(oferta_id, datos_compra)
    except Exception:  # pragma: no cover - fallback determinista si no esta el servicio
        lineas = [f"Certificado oferta {oferta_id}"]
        for clave in sorted(datos_compra):
            lineas.append(f"{clave}: {datos_compra[clave]}")
        cuerpo = "\n".join(lineas).encode("utf-8")
        return b"%PDF-1.4\n% certificado voltera\n" + cuerpo + b"\n%%EOF\n"


def _alterar_byte(pdf: bytes, rng: random.Random) -> bytes:
    """Cambia un unico byte del PDF por otro valor distinto (forma `byte`)."""
    if not pdf:
        return b"\x00"
    datos = bytearray(pdf)
    pos = rng.randrange(len(datos))
    datos[pos] = (datos[pos] + 1 + rng.randrange(255)) % 256
    if bytes(datos) == pdf:  # garantiza cambio efectivo (CID distinto)
        datos[pos] = (datos[pos] + 1) % 256
    return bytes(datos)


def _alterar_metadatos(pdf: bytes, rng: random.Random, etiqueta: int) -> bytes:
    """Añade/edita el bloque de metadatos del PDF sin tocar el texto visible (forma `metadatos`).

    Inserta un objeto `Info` con metadatos distintos antes del marcador de fin de archivo.
    El texto visible del certificado no cambia, pero los bytes del archivo (y por tanto su
    CID) si cambian: una alteracion de metadatos debe detectarse como ALTERADO (R3.5).
    """
    meta = (
        f"\n% metadatos alterados\n"
        f"<< /Producer (voltera-e2) /ModDate (D:{etiqueta:014d}) "
        f"/Alterado {rng.randrange(1_000_000)} >>\n"
    ).encode("latin-1", "replace")
    marcador = b"%%EOF"
    idx = pdf.rfind(marcador)
    if idx == -1:
        return pdf + meta
    return pdf[:idx] + meta + pdf[idx:]


def _alterar_reemplazo(oferta_id: int, rng: random.Random) -> bytes:
    """Reemplaza por completo el archivo por otro PDF distinto (forma `reemplazo`)."""
    datos_otro = {
        "reemplazo": True,
        "nonce": rng.randrange(1_000_000_000),
        "ofertaOriginal": oferta_id,
    }
    return _generar_pdf(oferta_id * 1000 + 7, datos_otro)


def _datos_compra(oferta_id: int) -> dict[str, Any]:
    """Datos de compra deterministas para el certificado integro de `oferta_id`."""
    return {
        "ofertaId": oferta_id,
        "comprador": f"0x{oferta_id:040x}",
        "kwh": 100 + oferta_id,
        "precio": 10,
    }


def generar_dataset(run_id: str, *, total: int = TOTAL_ALTERADOS, oferta_base: int = 1) -> list[CasoAlterado]:
    """Genera el dataset de E2: `total` alterados con >=1 por forma, reproducible por semilla.

    Para cada caso parte del PDF integro de una oferta (`_generar_pdf` determinista), le
    aplica la forma de alteracion asignada y comprueba que el PDF alterado difiere del
    original (condicion necesaria para que su CID sea distinto y la verificacion de ALTERADO).
    El `run_id` y los parametros fijan la semilla (R7.4): mismos parametros -> mismo dataset.
    """
    rng = random.Random(semilla_desde(run_id, "E2", total, oferta_base))
    formas = _asignar_formas(total, rng)
    casos: list[CasoAlterado] = []
    for i, forma in enumerate(formas):
        oferta_id = oferta_base + i
        datos = _datos_compra(oferta_id)
        original = _generar_pdf(oferta_id, datos)
        if forma == "byte":
            alterado = _alterar_byte(original, rng)
        elif forma == "metadatos":
            alterado = _alterar_metadatos(original, rng, etiqueta=oferta_id)
        elif forma == "reemplazo":
            alterado = _alterar_reemplazo(oferta_id, rng)
        else:  # pragma: no cover - formas controladas por _asignar_formas
            raise ValueError(f"forma de alteracion desconocida: {forma}")
        if alterado == original:  # salvaguarda: la alteracion debe ser efectiva
            alterado = original + b"\n% alteracion forzada\n"
        casos.append(
            CasoAlterado(
                oferta_id=oferta_id,
                forma=forma,
                pdf_original=original,
                pdf_alterado=alterado,
                datos_compra=datos,
            )
        )
    return casos


def conteo_por_forma(casos: list[CasoAlterado]) -> dict[str, int]:
    """Cuenta cuantos casos hay por forma de alteracion (para aseverar >=1 por forma)."""
    conteo = {forma: 0 for forma in FORMAS}
    for caso in casos:
        conteo[caso.forma] = conteo.get(caso.forma, 0) + 1
    return conteo


# ---------------------------------------------------------------------------
# Backend de certificados (anclaje + verificacion)
# ---------------------------------------------------------------------------
class BackendCertificado(Protocol):
    """Backend de `ms_certificado` que E2 ejercita.

    Mantiene la frontera on/off-chain real: anclar graba el CID del contenido integro
    on-chain; alterar sustituye el contenido almacenado (sin tocar el CID anclado); verificar
    recupera el contenido por el CID anclado, recalcula el identificador por contenido y
    devuelve el veredicto INTEGRO | ALTERADO | ERROR.
    """

    def anclar_integro(self, oferta_id: int, datos_compra: dict[str, Any]) -> bytes:
        """Genera, guarda y ancla el certificado integro; devuelve los bytes del PDF anclado."""
        ...

    def sustituir_contenido(self, oferta_id: int, pdf_alterado: bytes) -> None:
        """Reemplaza el contenido guardado bajo el CID anclado por `pdf_alterado`."""
        ...

    def verificar(self, oferta_id: int) -> dict[str, Any]:
        """Verifica la oferta y devuelve al menos `{"veredicto": INTEGRO|ALTERADO|ERROR}`."""
        ...


# ---------------------------------------------------------------------------
# Ejecucion del experimento
# ---------------------------------------------------------------------------
@dataclass
class MedicionVerificacion:
    """Una verificacion medida: oferta, forma esperada, veredicto obtenido y latencia."""

    oferta_id: int
    forma: str | None  # None para el caso integro de control
    veredicto: str
    latencia_s: float


def _percentil_95(muestras: list[float]) -> float:
    """p95 de `muestras` por el metodo del rango mas cercano (nearest-rank)."""
    if not muestras:
        return 0.0
    ordenadas = sorted(muestras)
    rango = max(1, int(-(-95 * len(ordenadas) // 100)))  # ceil(0.95 * n), >=1
    return ordenadas[rango - 1]


def _verificar_midiendo(backend: BackendCertificado, oferta_id: int, forma: str | None) -> MedicionVerificacion:
    """Ejecuta una verificacion midiendo su latencia con `time.monotonic` (R3.9)."""
    inicio = time.monotonic()
    respuesta = backend.verificar(oferta_id)
    latencia = time.monotonic() - inicio
    veredicto = str(respuesta.get("veredicto", ERROR)) if isinstance(respuesta, dict) else ERROR
    return MedicionVerificacion(oferta_id=oferta_id, forma=forma, veredicto=veredicto, latencia_s=latencia)


def ejecutar(
    backend: BackendCertificado,
    *,
    run_id: str,
    total: int = TOTAL_ALTERADOS,
    oferta_base: int = 1,
    incluir_control_integro: bool = True,
) -> ExperimentResult:
    """Ejecuta E2 de extremo a extremo y devuelve el `ExperimentResult` con veredicto PASS/FAIL.

    Pasos (R3.1, R3.5–R3.10, R3.13):
      1. Genera el dataset reproducible de 50 alterados (>=1 por forma).
      2. Ancla cada certificado integro on-chain (via `backend.anclar_integro`).
      3. (control) Verifica el integro recien anclado: debe dar INTEGRO (R3.7) — insumo de
         falsos positivos (R3.8).
      4. Sustituye el contenido por el PDF alterado y verifica: debe dar ALTERADO (R3.5).
      5. Mide la latencia de cada verificacion (R3.9); calcula tasa de deteccion, falsos
         positivos y Latencia_p95; asigna PASS sii deteccion=100%, falsos positivos=0 y
         p95<=3 s (R3.6, R3.8, R3.10), y registra las metricas (R3.13).
    """
    resultado = ExperimentResult(
        experiment="E2",
        title="E2 — Integridad del certificado off-chain",
        hypothesis=(
            "Toda alteracion de un certificado PDF (byte, metadatos o reemplazo) se detecta "
            "contra el CID anclado on-chain (deteccion 100%), un certificado integro se "
            "verifica como INTEGRO (0 falsos positivos) y la verificacion es rapida (p95 <= 3 s)."
        ),
        started=now_iso(),
    )

    try:
        casos = generar_dataset(run_id, total=total, oferta_base=oferta_base)
    except ValueError as exc:
        resultado.error = f"no se pudo generar el dataset de E2: {exc}"
        resultado.finished = now_iso()
        return resultado

    conteo = conteo_por_forma(casos)
    resultado.params = {
        "runId": run_id,
        "totalAlterados": len(casos),
        "conteoPorForma": conteo,
        "ofertaBase": oferta_base,
        "umbralP95Segundos": P95_UMBRAL_S,
    }

    detecciones = 0
    falsos_positivos = 0
    integros_ok = 0
    errores: list[dict[str, Any]] = []
    latencias: list[float] = []
    mediciones: list[MedicionVerificacion] = []

    progreso.emitir("inyeccion", f"E2: anclando y verificando {len(casos)} certificados", exp="E2",
                    total=len(casos))
    try:
        for idx, caso in enumerate(casos, 1):
            # 2) Anclar el certificado integro on-chain.
            backend.anclar_integro(caso.oferta_id, caso.datos_compra)

            # 3) Control integro: verificar antes de alterar debe dar INTEGRO (R3.7, R3.8).
            if incluir_control_integro:
                m_int = _verificar_midiendo(backend, caso.oferta_id, forma=None)
                mediciones.append(m_int)
                latencias.append(m_int.latencia_s)
                if m_int.veredicto == INTEGRO:
                    integros_ok += 1
                elif m_int.veredicto == ALTERADO:
                    falsos_positivos += 1  # integro marcado ALTERADO (R3.8)
                else:
                    errores.append({"ofertaId": caso.oferta_id, "fase": "control", "veredicto": m_int.veredicto})

            # 4) Alterar el contenido y verificar: debe dar ALTERADO (R3.5, R3.6).
            backend.sustituir_contenido(caso.oferta_id, caso.pdf_alterado)
            m_alt = _verificar_midiendo(backend, caso.oferta_id, forma=caso.forma)
            mediciones.append(m_alt)
            latencias.append(m_alt.latencia_s)
            progreso.emitir("inyeccion", f"E2: caso {idx}/{len(casos)} ({caso.forma}) -> {m_alt.veredicto}",
                            exp="E2", caso=idx, total=len(casos), forma=caso.forma, veredicto=m_alt.veredicto)
            if m_alt.veredicto == ALTERADO:
                detecciones += 1
            elif m_alt.veredicto == INTEGRO:
                errores.append({"ofertaId": caso.oferta_id, "forma": caso.forma, "veredicto": INTEGRO})
            else:
                errores.append({"ofertaId": caso.oferta_id, "forma": caso.forma, "veredicto": m_alt.veredicto})
    except Exception as exc:  # indisponibilidad / fallo del backend durante E2
        resultado.error = f"E2 abortado por fallo del backend de certificados: {exc.__class__.__name__}: {exc}"
        resultado.finished = now_iso()
        logger.exception("E2 abortado por fallo del backend")
        return resultado

    total_alterados = len(casos)
    tasa_deteccion = (detecciones / total_alterados) if total_alterados else 0.0
    p95 = _percentil_95(latencias)
    conteo_formas_detectadas = {forma: 0 for forma in FORMAS}
    for m in mediciones:
        if m.forma in conteo_formas_detectadas and m.veredicto == ALTERADO:
            conteo_formas_detectadas[m.forma] += 1

    resultado.data = {
        "mediciones": [
            {"ofertaId": m.oferta_id, "forma": m.forma, "veredicto": m.veredicto, "latenciaS": round(m.latencia_s, 6)}
            for m in mediciones
        ],
        "latenciasVerificacionS": [round(x, 6) for x in latencias],
    }

    # --- Criterios PASS/FAIL (R3.6, R3.8, R3.10) con esperado/observado (R3.13) ---------
    resultado.add(
        "R3.1",
        "Dataset de 50 alterados con >=1 por forma",
        ok=(total_alterados == TOTAL_ALTERADOS and all(conteo[f] >= 1 for f in FORMAS)),
        expected=f"{TOTAL_ALTERADOS} alterados; >=1 por forma {FORMAS}",
        observed=f"{total_alterados} alterados; conteo {conteo}",
        conteoPorForma=conteo,
    )
    resultado.add(
        "R3.6",
        "Tasa de deteccion de alteraciones = 100%",
        ok=(detecciones == total_alterados),
        expected="100% (todos los alterados -> ALTERADO)",
        observed=f"{detecciones}/{total_alterados} detectados ({tasa_deteccion * 100:.1f}%)",
        detecciones=detecciones,
        total=total_alterados,
        porForma=conteo_formas_detectadas,
        casosNoDetectados=errores,
    )
    if incluir_control_integro:
        resultado.add(
            "R3.8",
            "Falsos positivos = 0 (ningun integro marcado ALTERADO)",
            ok=(falsos_positivos == 0),
            expected="0 falsos positivos",
            observed=f"{falsos_positivos} falsos positivos; {integros_ok}/{total_alterados} integros OK",
            falsosPositivos=falsos_positivos,
            integrosOk=integros_ok,
        )
    resultado.add(
        "R3.10",
        "Latencia_p95 de verificacion <= 3 s",
        ok=(p95 <= P95_UMBRAL_S),
        expected=f"p95 <= {P95_UMBRAL_S} s",
        observed=f"p95 = {p95:.4f} s sobre {len(latencias)} verificaciones",
        p95Segundos=round(p95, 6),
        umbralSegundos=P95_UMBRAL_S,
        muestras=len(latencias),
    )

    resultado.params["metricas"] = {
        "tasaDeteccion": round(tasa_deteccion, 6),
        "deteccionesPorForma": conteo_formas_detectadas,
        "falsosPositivos": falsos_positivos,
        "p95VerificacionSegundos": round(p95, 6),
    }

    # FAIL marca la(s) metrica(s) incumplida(s) con valor y umbral (R7.5 / R3.13).
    incumplidas = [c.id for c in resultado.criteria if c.status == FAIL]
    if incumplidas:
        resultado.notes.append(f"E2 FAIL: criterios incumplidos {incumplidas}")
    resultado.notes.append(
        f"Veredicto E2: {resultado.verdict} | deteccion={tasa_deteccion * 100:.1f}% "
        f"falsosPositivos={falsos_positivos} p95={p95:.4f}s"
    )
    resultado.finished = now_iso()
    return resultado


# ---------------------------------------------------------------------------
# Siembra de una venta real on-chain (corrige CompraNoRealizada al anclar)
# ---------------------------------------------------------------------------
PRECIO_POR_KWH = 10       # precio fijado al emitir (debe ser > 0)
KWH_CERTIFICADO = 50      # kWh de la oferta que respalda cada certificado


class _SembradorVentaOnChain:
    """Crea una venta real on-chain para que exista un certificado anclable (R3).

    `MarketEscrow.anclar(ofertaId, cid)` exige estado Vendida; si no, revierte con
    CompraNoRealizada. Por eso, antes de anclar, se hace la venta completa por caso:
    emitir(vendedor, token, kwh, precio) -> publicar(...) -> comprar(ofertaId, comprador).
    Devuelve el ofertaId REAL asignado por el contrato (no el indice del dataset).
    """

    def __init__(self, chain):
        self._chain = chain

    def _addr(self, etiqueta):
        from web3 import Web3
        h = hashlib.sha256(f"e2-{etiqueta}".encode()).hexdigest()
        return Web3.to_checksum_address("0x" + h[-40:])

    def sembrar_venta(self, caso_id, token_id, kwh):
        from web3 import Web3
        et = self._chain.energy_token
        me = self._chain.market_escrow
        plat = self._chain.plataforma
        vendedor = self._addr(f"vendedor-{caso_id}")
        comprador = self._addr(f"comprador-{caso_id}")

        lectura = Web3.keccak(text=f"e2-seed-{token_id}-{caso_id}")
        tx = et.functions.emitir(vendedor, int(token_id), int(kwh), PRECIO_POR_KWH, lectura
                                 ).build_transaction({"from": plat, "nonce": self._chain.siguiente_nonce()})
        r = self._chain.enviar_y_esperar(tx)
        if not r.confirmada:
            raise RuntimeError(f"E2 seed: emitir no confirmo (caso {caso_id}): {r.estado.value}")

        tx = me.functions.publicar(vendedor, int(token_id), int(kwh)
                                   ).build_transaction({"from": plat, "nonce": self._chain.siguiente_nonce()})
        tx_hash = self._chain.enviar_tx(tx)
        rec = self._chain.esperar_recibo(tx_hash)
        if not rec.confirmada:
            raise RuntimeError(f"E2 seed: publicar no confirmo (caso {caso_id}): {rec.estado.value}")
        recibo = self._chain.w3.eth.get_transaction_receipt(tx_hash)
        evts = me.events.OfertaPublicada().process_receipt(recibo)
        oferta_id = int(evts[0]["args"]["ofertaId"])

        tx = me.functions.comprar(oferta_id, comprador
                                  ).build_transaction({"from": plat, "nonce": self._chain.siguiente_nonce()})
        r = self._chain.enviar_y_esperar(tx)
        if not r.confirmada:
            raise RuntimeError(f"E2 seed: comprar no confirmo (oferta {oferta_id}): {r.estado.value}")
        return oferta_id


# ---------------------------------------------------------------------------
# Backend en-proceso (logica de dominio real de ms_certificado)
# ---------------------------------------------------------------------------
class BackendEnProceso:
    """Backend de E2 que usa la logica de dominio real de `ms_certificado` en el proceso.

    Reutiliza `CertificadoService` (genera PDF, guarda en el almacen de contenido
    direccionable, ancla via el `ChainClient`) y el `AlmacenContenidoDisco` compartido. La
    alteracion se modela como el runner haria off-chain: se sustituye el blob guardado bajo
    el CID anclado por el PDF alterado, sin tocar el CID on-chain; al verificar, el servicio
    recupera ese contenido alterado, recalcula su CID y lo encuentra distinto -> ALTERADO.

    El cliente de cadena (`chain`) y el almacen se inyectan, lo que permite ejecutar E2 tanto
    contra Anvil real (cableado del runner) como contra dobles en pruebas.
    """

    def __init__(self, config: Any, chain: Any, almacen: Any) -> None:
        # Importe diferido: solo se necesita cuando se usa el backend en-proceso; el cableado
        # agrega `services/ms-certificado` al sys.path.
        from certificado_service import CertificadoService  # type: ignore[import-not-found]

        self._servicio = CertificadoService(config, chain, almacen=almacen)
        self._almacen = almacen
        self._sembrador = _SembradorVentaOnChain(chain)
        # Mapa caso_id (dataset) -> ofertaId REAL on-chain (para alterar/verificar).
        self._ofertas: dict[int, int] = {}

    def anclar_integro(self, oferta_id: int, datos_compra: dict[str, Any]) -> bytes:
        from pdf import generar_pdf  # type: ignore[import-not-found]
        from contenido import calcular_cid  # type: ignore[import-not-found]

        # 1) Sembrar una venta real on-chain -> ofertaId real en estado Vendida.
        token_id = 4_000_000 + int(oferta_id)
        oferta_real = self._sembrador.sembrar_venta(oferta_id, token_id, KWH_CERTIFICADO)
        self._ofertas[oferta_id] = oferta_real
        # 2) Generar el PDF, guardarlo en el almacen local y anclar su CID contra el id real.
        pdf_bytes = generar_pdf(oferta_id, datos_compra)
        cid = self._almacen.guardar(pdf_bytes)
        self._servicio._anclar(oferta_real, cid)  # noqa: SLF001 - anclaje directo con id real
        return pdf_bytes

    def _oferta_real(self, oferta_id: int) -> int:
        return self._ofertas.get(oferta_id, oferta_id)

    def sustituir_contenido(self, oferta_id: int, pdf_alterado: bytes) -> None:
        """Sobrescribe el blob guardado bajo el CID anclado con el PDF alterado."""
        oferta_real = self._oferta_real(oferta_id)
        cid_anclado = self._servicio._leer_cid_anclado(oferta_real)  # noqa: SLF001
        if not cid_anclado:
            raise RuntimeError(f"la oferta {oferta_real} no tiene CID anclado; no se puede alterar")
        ruta = self._almacen._ruta(cid_anclado)  # noqa: SLF001
        ruta.write_bytes(bytes(pdf_alterado))
        self._almacen._blobs.pop(cid_anclado, None)  # noqa: SLF001

    def verificar(self, oferta_id: int) -> dict[str, Any]:
        return self._servicio.verificar_certificado(self._oferta_real(oferta_id)).as_dict()


class BackendPinataSubidaLocalVerificacion:
    """Backend de E2 (Opcion B): sube a Pinata REAL para el anclaje, verifica contra el local.

    Motivacion: Pinata es un almacen direccionable por contenido, asi que recuperar por el CID
    anclado SIEMPRE devuelve el contenido original (el CID es el hash del contenido). Por eso
    el modelo de "alterar el blob y re-verificar el mismo CID" solo es observable contra el
    almacen local. Esta variante mantiene la integracion REAL con Pinata donde si tiene sentido
    (subir el PDF integro y anclar su CID real) y mide la deteccion de alteraciones contra el
    almacen local (que si refleja la sustitucion del contenido).

    Flujo por caso:
      * `anclar_integro`: sube el PDF integro a Pinata (`pinFileToIPFS`, CID real), lo guarda en
        el almacen local bajo ese mismo CID (determinado por contenido) y ancla el CID on-chain.
      * `sustituir_contenido`: sobrescribe el blob local del CID anclado con el PDF alterado.
      * `verificar`: recupera del almacen local (donde vive la alteracion), recalcula el CID y
        lo compara con el anclado -> INTEGRO/ALTERADO/ERROR.
    """

    def __init__(self, config: Any, chain: Any, almacen: Any, *, jwt: str) -> None:
        # El servicio se construye SIN credenciales de Pinata, de modo que su verificacion
        # recupere del almacen local (donde se aplica la alteracion). La subida real a Pinata
        # se hace aparte, explicitamente, en anclar_integro.
        from certificado_service import CertificadoService  # type: ignore[import-not-found]

        self._servicio = CertificadoService(config, chain, almacen=almacen)
        self._almacen = almacen
        self._jwt = jwt
        self._sembrador = _SembradorVentaOnChain(chain)
        self._ofertas: dict[int, int] = {}  # caso_id -> ofertaId real
        # Evidencia de integracion real: CID devuelto por Pinata por caso.
        self.cids_pinata: dict[int, str] = {}

    def anclar_integro(self, oferta_id: int, datos_compra: dict[str, Any]) -> bytes:
        import pinata  # type: ignore[import-not-found]
        from pdf import generar_pdf  # type: ignore[import-not-found]

        # 1) Sembrar venta real on-chain -> ofertaId real en estado Vendida.
        token_id = 4_000_000 + int(oferta_id)
        oferta_real = self._sembrador.sembrar_venta(oferta_id, token_id, KWH_CERTIFICADO)
        self._ofertas[oferta_id] = oferta_real
        # 2) Generar PDF; subida REAL a Pinata (integracion genuina).
        pdf_bytes = generar_pdf(oferta_id, datos_compra)
        cid_pinata = pinata.subir_pdf(pdf_bytes, jwt=self._jwt)
        self.cids_pinata[oferta_id] = cid_pinata
        # 3) Guardar copia local y anclar su CID contra el ofertaId real.
        cid_local = self._almacen.guardar(pdf_bytes)
        self._servicio._anclar(oferta_real, cid_local)  # noqa: SLF001
        return pdf_bytes

    def _oferta_real(self, oferta_id: int) -> int:
        return self._ofertas.get(oferta_id, oferta_id)

    def sustituir_contenido(self, oferta_id: int, pdf_alterado: bytes) -> None:
        oferta_real = self._oferta_real(oferta_id)
        cid_anclado = self._servicio._leer_cid_anclado(oferta_real)  # noqa: SLF001
        if not cid_anclado:
            raise RuntimeError(f"la oferta {oferta_real} no tiene CID anclado; no se puede alterar")
        ruta = self._almacen._ruta(cid_anclado)  # noqa: SLF001
        ruta.write_bytes(bytes(pdf_alterado))
        self._almacen._blobs.pop(cid_anclado, None)  # noqa: SLF001

    def verificar(self, oferta_id: int) -> dict[str, Any]:
        return self._servicio.verificar_certificado(self._oferta_real(oferta_id)).as_dict()


def construir_backend_pinata_local(
    deployment: "Deployment",
    *,
    jwt: str,
    almacen_dir: "Path | None" = None,
) -> BackendPinataSubidaLocalVerificacion:
    """Fabrica del backend Opcion B: Pinata real para subir+anclar, local para verificar.

    Construye el `CertificadoService` con un `Config` SIN JWT (verificacion contra el local) y
    pasa el `jwt` aparte para la subida real a Pinata en `anclar_integro`.
    """
    _asegurar_ms_certificado_en_path()
    from config import Config  # type: ignore[import-not-found]
    from contenido import AlmacenContenidoDisco  # type: ignore[import-not-found]

    directorio = Path(almacen_dir) if almacen_dir is not None else (_ROOT / ".certificados-local")
    config = Config(
        port=0,
        rpc_url=deployment.rpc_url,
        deployment_path=deployment.ruta,
        almacen_dir=directorio,
        pinata_jwt=None,  # verificacion contra el almacen local (donde se aplica la alteracion)
        pinata_gateway="https://gateway.pinata.cloud/ipfs/",
    )
    chain = build_chain_client(deployment.rpc_url, contratos=dict(deployment.contratos))
    almacen = AlmacenContenidoDisco(directorio)
    return BackendPinataSubidaLocalVerificacion(config, chain, almacen, jwt=jwt)


def _asegurar_ms_certificado_en_path() -> None:
    """Agrega `services/ms-certificado/` al `sys.path` para importar su logica de dominio.

    `ms_certificado` importa `config`/`certificado_service`/`contenido`/`pdf` como modulos
    de nivel superior (patron del repo); el backend en-proceso de E2 los reutiliza sin
    duplicar codigo, por lo que la carpeta del servicio debe estar en el path.
    """
    ruta = str(_MS_CERTIFICADO_DIR)
    if _MS_CERTIFICADO_DIR.is_dir() and ruta not in sys.path:
        sys.path.insert(0, ruta)


def construir_backend_en_proceso(
    deployment: Deployment,
    *,
    almacen_dir: Path | None = None,
    pinata_jwt: str | None = None,
) -> BackendEnProceso:
    """Construye el `BackendEnProceso` de E2 cableado al despliegue de la corrida (tarea 13.1).

    Reutiliza la logica de dominio real de `ms_certificado`:

    * un `Config` que apunta al mismo `deployment.json`/RPC de la corrida, al directorio del
      almacen local de contenido direccionable (fallback de Pinata, R3.3) y, si se provee,
      al JWT de Pinata (nunca se registra; R3.4),
    * un `ChainClient` compartido apuntando a `MarketEscrow`/`EnergyToken` del despliegue
      (firma custodial con `PLATAFORMA_PRIVATE_KEY`),
    * el `AlmacenContenidoDisco` sobre `almacen_dir`.

    De este modo E2 ancla y verifica certificados contra la misma cadena y el mismo CID
    on-chain que el resto de la corrida, manteniendo la frontera on/off-chain real.
    """
    _asegurar_ms_certificado_en_path()
    from config import Config  # type: ignore[import-not-found]
    from contenido import AlmacenContenidoDisco  # type: ignore[import-not-found]

    directorio = almacen_dir if almacen_dir is not None else (_ROOT / ".certificados-local")
    directorio = Path(directorio)

    jwt = pinata_jwt.strip() if pinata_jwt and pinata_jwt.strip() else None
    config = Config(
        port=0,  # el backend en-proceso no abre un servidor HTTP
        rpc_url=deployment.rpc_url,
        deployment_path=deployment.ruta,
        almacen_dir=directorio,
        pinata_jwt=jwt,
        pinata_gateway="https://gateway.pinata.cloud/ipfs/",
    )
    chain = build_chain_client(deployment.rpc_url, contratos=dict(deployment.contratos))
    almacen = AlmacenContenidoDisco(directorio)
    return BackendEnProceso(config, chain, almacen)
