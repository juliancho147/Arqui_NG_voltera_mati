#!/usr/bin/env python3
"""Lanza un experimento en modo demo con UNA linea (usa el venv del runner y toma la clave de Grafana de observability/.env).

Ejemplos (desde experiments/):
  python3 correr.py fact=1500                      # Exp1 con 1500 facturas
  python3 correr.py exp=2 fact=300 caso=B          # Exp2 (Resiliencia ante fallos), cae ms-comprobante-factura
  python3 correr.py exp=2 fact=300 matar=2 fallos=0.25 ventana=90 dupl=50
  python3 correr.py exp=1 fact=500 retardo=2 sla=360 sinpausa=1
  python3 correr.py exp=2 fact=300 ensayo=1        # solo muestra el plan (todas las fases), no toca nada

Parametros (todos opcionales):
  exp      1|2 (defecto 1). exp=3 es alias de 2: el antiguo Exp. 3 (cero perdida) se unio al Exp. 2 y se ejecuta lo mismo
  fact     numero de facturas (defecto 500 en exp1, 150 en exp2)
  retardo  segundos simulados/msg (defecto 0.1 en exp1, 1 en exp2)       sla     limite del lote en s (solo exp1)
  Exp. 2:  caso    A (cae ms-tarifas) | B (cae ms-comprobante-factura, defecto)
           matar   pods de ms-process-billing a matar (defecto 2)        fallos  fraccion FAIL_RATE en ms-facturacion (defecto 0.25)
           ventana segundos del fallo FAIL_RATE (defecto 30)             dupl    copias duplicadas a proposito por SQS y Kafka (defecto 30; 0 = omitir)
           observar s de observacion tras tumbar el dependiente (defecto 15)   espera_metricas s maximos esperando a CloudWatch (defecto 60)
  sinpausa 1 = sin esperar Enter       ensayo   1 = --dry-run
  si       1 = no pedir confirmacion   resultados 0 = no escribir en RESULTADOS.md
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / "runner"
PY = RUNNER / ".venv" / "bin" / "python"
DEFECTO_FACT = {"1": "500", "2": "150"}
AVISO_EXP3 = "AVISO: el antiguo Exp. 3 (cero perdida) se unio al Exp. 2 (Resiliencia ante fallos: aislamiento + cero perdida); se ejecuta exp=2."


def parse(argv: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in argv:
        if a in ("-h", "--help", "help"):
            print(__doc__)
            sys.exit(0)
        if "=" not in a:
            sys.exit(f"argumento invalido '{a}': usa clave=valor (ver --help)")
        k, v = a.split("=", 1)
        out[k.strip().lower().lstrip("-")] = v.strip()
    return out


def leer_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
    return env


def construir(p: dict[str, str]) -> list[str]:
    """Traduce los parametros clave=valor al comando del runner (consume `p`; lo que sobre es un parametro desconocido)."""
    exp = p.pop("exp", "1").lower().replace("exp", "")
    if exp == "3":
        print(AVISO_EXP3, file=sys.stderr, flush=True)
        exp = "2"
    if exp not in DEFECTO_FACT:
        sys.exit("exp debe ser 1 o 2 (el 3 es alias del 2)")
    fact = p.pop("fact", DEFECTO_FACT[exp])

    cmd = [str(PY), "-m", "runner", "demo", f"exp{exp}", "--n", fact]
    if "retardo" in p:
        cmd += ["--delay", p.pop("retardo")]
    else:
        cmd += ["--delay", "0.1" if exp == "1" else "1"]  # exp1: casi natural pero con algo de backlog; exp2: mensajes en vuelo y lote lo bastante largo
    if exp == "1" and "sla" in p:
        cmd += ["--sla", p.pop("sla")]
    if exp == "2":
        cmd += ["--case", p.pop("caso", "B").upper(), "--kill-pods", p.pop("matar", "2"), "--fail-rate", p.pop("fallos", "0.25"),
                "--fault-window", p.pop("ventana", "30"), "--dupl", p.pop("dupl", "30"),
                "--observe", p.pop("observar", "15"), "--timeout-metricas", p.pop("espera_metricas", "60")]
    if p.pop("sinpausa", "0") == "1":
        cmd.append("--no-pause")
    if p.pop("ensayo", "0") == "1":
        cmd.append("--dry-run")
    if p.pop("si", "0") == "1":
        cmd.append("--yes")
    if p.pop("resultados", "1") == "0":
        cmd.append("--no-resultados")
    if p:
        sys.exit(f"parametros desconocidos: {', '.join(p)} (ver --help)")
    return cmd


def main() -> None:
    cmd = construir(parse(sys.argv[1:]))
    if not PY.exists():
        sys.exit(f"no existe {PY}; crea el venv del runner (ver DEMO.md)")

    env = dict(os.environ)
    env.setdefault("AWS_REGION", "us-east-1")
    env.setdefault("AWS_DEFAULT_REGION", env["AWS_REGION"])
    # Anotaciones automaticas en Grafana si hay clave en observability/.env
    g = leer_env(ROOT.parent / "observability" / ".env")
    if g.get("GRAFANA_ADMIN_PASSWORD") and "GRAFANA_PASSWORD" not in env and "GRAFANA_TOKEN" not in env:
        env.setdefault("GRAFANA_URL", "http://localhost:3000")
        env.setdefault("GRAFANA_USER", "admin")
        env["GRAFANA_PASSWORD"] = g["GRAFANA_ADMIN_PASSWORD"]

    print("$ " + " ".join(cmd[1:]), flush=True)
    sys.exit(subprocess.call(cmd, cwd=RUNNER, env=env))


if __name__ == "__main__":
    main()
