#!/usr/bin/env python3
"""Genera N transacciones preprocesadas para un cicloId y las escribe en la tabla `transacciones`
(PK cicloId, SK facturaId). Soporta DynamoDB local (--endpoint-url) y --dry-run (no toca nada).

Ejemplos:
  python seed_transacciones.py --ciclo-id CICLO-202609 --n 10 --dry-run
  python seed_transacciones.py --ciclo-id CICLO-202609 --n 10 --table voltera-exp2-transacciones --region us-east-1
  python seed_transacciones.py --ciclo-id T1 --n 5 --endpoint-url http://localhost:8000
NO ejecutar contra AWS desde automatizaciones: el operador decide cuando y con que credenciales.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from decimal import Decimal

TARIFAS = ["RESIDENCIAL", "COMERCIAL", "INDUSTRIAL", "OFICIAL"]


def generar(ciclo_id: str, n: int, seed: int = 42, periodo: str | None = None, rechazos_tarifa: int = 0,
            rechazos_calculo: int = 0, retardo_segundos: float | None = None) -> list[dict]:
    """Items deterministas (mismo seed => mismos datos). facturaId = <cicloId>-F0001 (unico entre ciclos).

    rechazos_tarifa / rechazos_calculo: cuantas transacciones al final llevan datos que provocan rechazos de negocio
    (tipoTarifa inexistente / excedentes > consumo), para probar la rama de rechazo.
    """
    rng = random.Random(seed)
    periodo = periodo or (ciclo_id.split("-")[-1] if "-" in ciclo_id else "2026-09")
    items = []
    for i in range(1, n + 1):
        consumo = Decimal(rng.randint(80, 600))
        excedentes = Decimal(rng.randint(0, 40))
        tipo = TARIFAS[(i - 1) % len(TARIFAS)]
        if i > n - rechazos_tarifa:
            tipo = "INEXISTENTE"
        elif i > n - rechazos_tarifa - rechazos_calculo:
            excedentes = consumo + Decimal(10)
        item = {
            "cicloId": ciclo_id, "facturaId": f"{ciclo_id}-F{i:04d}", "clienteId": f"CLI-{rng.randint(1000, 9999)}",
            "tipoTarifa": tipo, "periodo": periodo, "consumoKwh": consumo, "excedentesKwh": excedentes, "estado": "PREPARADO",
        }
        if retardo_segundos is not None:
            item["retardoSegundos"] = Decimal(str(retardo_segundos))
        items.append(item)
    return items


def escribir(items: list[dict], table_name: str, region: str | None, endpoint_url: str | None, profile: str | None = None) -> int:
    import boto3

    session = boto3.Session(profile_name=profile, region_name=region)
    table = session.resource("dynamodb", endpoint_url=endpoint_url).Table(table_name)
    with table.batch_writer(overwrite_by_pkeys=["cicloId", "facturaId"]) as bw:
        for it in items:
            bw.put_item(Item=it)
    return len(items)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciclo-id", required=True)
    ap.add_argument("--n", type=int, default=int(os.environ.get("N_SOLICITUDES", "10")))
    ap.add_argument("--table", default=os.environ.get("TABLE_TRANSACCIONES", "voltera-exp2-transacciones"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--endpoint-url", default=None, help="DynamoDB local, p. ej. http://localhost:8000")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--periodo", default=None)
    ap.add_argument("--rechazos-tarifa", type=int, default=0)
    ap.add_argument("--rechazos-calculo", type=int, default=0)
    ap.add_argument("--retardo-segundos", type=float, default=None, help="retardo simulado por mensaje (Exp. 1)")
    ap.add_argument("--dry-run", action="store_true", help="imprime los items y no escribe nada")
    a = ap.parse_args(argv)

    if a.n < 1 or a.rechazos_tarifa + a.rechazos_calculo > a.n:
        ap.error("n debe ser >= 1 y los rechazos no pueden superar n")
    items = generar(a.ciclo_id, a.n, a.seed, a.periodo, a.rechazos_tarifa, a.rechazos_calculo, a.retardo_segundos)
    if a.dry_run:
        for it in items:
            print(json.dumps(it, default=str))
        print(f"[dry-run] {len(items)} items para {a.table} (no se escribio nada)", file=sys.stderr)
        return 0
    n = escribir(items, a.table, a.region, a.endpoint_url, a.profile)
    print(f"escritos {n} items en {a.table} (ciclo {a.ciclo_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
