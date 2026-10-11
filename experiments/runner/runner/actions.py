"""Acciones que modifican estado: disparo del cierre de mes, inyeccion de fallos (revertible) y redrive de DLQ."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from .config import SEED_DIR
from .context import Context
from .safety import arn_resource

FAULT_VARS = ("FORCE_FAIL", "FAIL_RATE")


# ----------------------------------------------------------------------------- disparo
def new_ciclo_id(tag: str = "EXP") -> str:
    return f"{tag}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def generar_transacciones(ciclo_id: str, n: int, retardo_segundos: float | None = None, **kw) -> list[dict]:
    """Reutiliza experiments/seed/seed_transacciones.generar (mismos items que el seed oficial)."""
    if str(SEED_DIR) not in sys.path:
        sys.path.insert(0, str(SEED_DIR))
    import seed_transacciones  # type: ignore

    periodo = kw.pop("periodo", None) or datetime.now(timezone.utc).strftime("%Y-%m")
    return seed_transacciones.generar(ciclo_id, n, periodo=periodo, retardo_segundos=retardo_segundos, **kw)


def seed(ctx: Context, ciclo_id: str, n: int, retardo_segundos: float | None = None, **kw) -> list[str]:
    items = generar_transacciones(ciclo_id, n, retardo_segundos, **kw)
    table = ctx.table("transacciones")
    ctx.guard(table.name, "tabla")
    with table.batch_writer(overwrite_by_pkeys=["cicloId", "facturaId"]) as bw:
        for it in items:
            bw.put_item(Item=it)
    return [it["facturaId"] for it in items]


def put_cierre_de_mes(ctx: Context, ciclo_id: str, n: int) -> dict:
    ctx.guard(ctx.cfg.bus_name, "bus de EventBridge")
    out = ctx.client("events").put_events(Entries=[{
        "Source": "voltera.runner", "DetailType": "CierreDeMes", "EventBusName": ctx.cfg.bus_name,
        "Detail": json.dumps({"cicloId": ciclo_id, "nSolicitudes": n}),
    }])
    if out.get("FailedEntryCount"):
        raise RuntimeError(f"PutEvents fallo: {out['Entries']}")
    return {"eventId": out["Entries"][0].get("EventId"), "bus": ctx.cfg.bus_name}


def dispatch_cierre(ctx: Context, ciclo_id: str, n: int, retardo_segundos: float | None = None, **seed_kw) -> dict:
    """Seed de N transacciones + PutEvents CierreDeMes. Devuelve ids inyectados y la marca de tiempo."""
    ids = seed(ctx, ciclo_id, n, retardo_segundos, **seed_kw)
    t0 = ctx.clock()
    ev = put_cierre_de_mes(ctx, ciclo_id, n)
    ctx.log(f"cierre de mes disparado: ciclo={ciclo_id} N={n} eventId={ev['eventId']}")
    return {"cicloId": ciclo_id, "n": n, "facturaIds": ids, "t0": t0, "event": ev, "retardoSegundos": retardo_segundos}


# ----------------------------------------------------------------------------- inyeccion de fallos
def _wait_updated(ctx: Context, fn: str) -> None:
    try:
        ctx.client("lambda").get_waiter("function_updated_v2").wait(FunctionName=fn, WaiterConfig={"Delay": 2, "MaxAttempts": 30})
    except Exception as exc:  # noqa: BLE001 - el waiter no existe/falla en emuladores; no es critico
        ctx.log(f"aviso: no se pudo esperar function_updated ({type(exc).__name__})")


def _set_env(ctx: Context, fn: str, values: dict[str, str | None]) -> None:
    lam = ctx.client("lambda")
    env = dict(lam.get_function_configuration(FunctionName=fn).get("Environment", {}).get("Variables", {}))
    for k, v in values.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    lam.update_function_configuration(FunctionName=fn, Environment={"Variables": env})
    _wait_updated(ctx, fn)


def inject_fault(ctx: Context, service: str, mode: str = "env", rate: float | None = None) -> str:
    """Degrada un servicio. mode=env (FORCE_FAIL=true) | concurrency (reserved concurrency = 0) | rate (FAIL_RATE=<rate>, fallo parcial).
    Registra el estado previo en la bitacora ANTES de modificar. Devuelve el id de la entrada."""
    fn = ctx.guard(ctx.cfg.lambda_name(service), "Lambda")
    lam = ctx.client("lambda")
    if mode == "concurrency":
        cur = lam.get_function_concurrency(FunctionName=fn).get("ReservedConcurrentExecutions")
        eid = ctx.journal.record("lambda_concurrency", fn, {"function": fn, "reserved": cur})
        lam.put_function_concurrency(FunctionName=fn, ReservedConcurrentExecutions=0)
        ctx.log(f"FALLO inyectado en {fn}: concurrencia reservada 0 (antes {cur})")
        return eid
    env = lam.get_function_configuration(FunctionName=fn).get("Environment", {}).get("Variables", {})
    before = {"function": fn, **{k: env.get(k) for k in FAULT_VARS}}
    eid = ctx.journal.record("lambda_env", fn, before)
    if mode == "rate":
        _set_env(ctx, fn, {"FAIL_RATE": str(rate if rate is not None else 0.3)})
        ctx.log(f"FALLO PARCIAL inyectado en {fn}: FAIL_RATE={rate if rate is not None else 0.3} (antes {before['FAIL_RATE']})")
        return eid
    _set_env(ctx, fn, {"FORCE_FAIL": "true"})
    ctx.log(f"FALLO inyectado en {fn}: FORCE_FAIL=true (antes {before['FORCE_FAIL']})")
    return eid


def restore_entry(ctx: Context, entry: dict) -> str:
    kind, b = entry["kind"], entry["before"]
    if kind == "lambda_env":
        fn = ctx.guard(b["function"], "Lambda")
        _set_env(ctx, fn, {k: b.get(k) for k in FAULT_VARS})
        msg = f"{fn}: FORCE_FAIL={b.get('FORCE_FAIL')} FAIL_RATE={b.get('FAIL_RATE')}"
    elif kind == "lambda_concurrency":
        fn = ctx.guard(b["function"], "Lambda")
        lam = ctx.client("lambda")
        if b.get("reserved") is None:
            lam.delete_function_concurrency(FunctionName=fn)
        else:
            lam.put_function_concurrency(FunctionName=fn, ReservedConcurrentExecutions=int(b["reserved"]))
        msg = f"{fn}: concurrencia reservada={b.get('reserved')}"
    else:
        return f"{kind}: no revertible"
    ctx.journal.mark_restored(entry["id"])
    ctx.log(f"RESTAURADO {msg}")
    return msg


def restore_ids(ctx: Context, ids: list[str]) -> list[str]:
    """Restaura las entradas indicadas (idempotente). Pensado para `finally`: no propaga errores individuales."""
    out = []
    pend = {e["id"]: e for e in ctx.journal.pending()}
    for eid in reversed(ids):
        if eid in pend:
            try:
                out.append(restore_entry(ctx, pend[eid]))
            except Exception as exc:  # noqa: BLE001
                out.append(f"ERROR restaurando {eid}: {exc}")
                ctx.log(f"ERROR restaurando {eid}: {exc}  -> ejecute `python -m runner restore`")
    return out


def restore_all(ctx: Context) -> list[str]:
    return restore_ids(ctx, [e["id"] for e in ctx.journal.pending()])


# ----------------------------------------------------------------------------- redrive
def redrive_dlq(ctx: Context, queue_key: str, timeout: float = 120) -> dict:
    """Devuelve los mensajes de la DLQ a la cola de origen: StartMessageMoveTask; si no esta disponible, manual."""
    q = ctx.cfg.queue(queue_key)
    ctx.guard(arn_resource(q["dlq_arn"]), "DLQ")
    sqs = ctx.client("sqs")
    before = int(sqs.get_queue_attributes(QueueUrl=q["dlq_url"], AttributeNames=["ApproximateNumberOfMessages"])["Attributes"]["ApproximateNumberOfMessages"])
    try:
        task = sqs.start_message_move_task(SourceArn=q["dlq_arn"])
        handle = task.get("TaskHandle")

        def done():
            tasks = sqs.list_message_move_tasks(SourceArn=q["dlq_arn"]).get("Results", [])
            mine = [t for t in tasks if t.get("TaskHandle") == handle] or tasks[:1]
            return mine[0] if mine and mine[0].get("Status") in ("COMPLETED", "FAILED", "CANCELLED") else None

        res, _ = ctx.wait_until(done, timeout, 3)
        return {"mode": "StartMessageMoveTask", "movidosAntes": before, "status": (res or {}).get("Status", "TIMEOUT"),
                "movidos": (res or {}).get("ApproximateNumberOfMessagesMoved")}
    except (ClientError, NotImplementedError, AttributeError) as exc:
        ctx.log(f"StartMessageMoveTask no disponible ({exc}); redrive manual")
    moved = 0
    while True:
        r = sqs.receive_message(QueueUrl=q["dlq_url"], MaxNumberOfMessages=10, WaitTimeSeconds=0, VisibilityTimeout=30)
        msgs = r.get("Messages", [])
        if not msgs:
            break
        for m in msgs:
            sqs.send_message(QueueUrl=q["url"], MessageBody=m["Body"])
            sqs.delete_message(QueueUrl=q["dlq_url"], ReceiptHandle=m["ReceiptHandle"])
            moved += 1
    return {"mode": "manual", "movidosAntes": before, "status": "COMPLETED", "movidos": moved}
