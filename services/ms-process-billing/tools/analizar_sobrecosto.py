#!/usr/bin/env python3
"""Percentiles por etapa a partir de logs de ms-process-billing (kubectl logs).

Uso:
  kubectl logs -n voltera -l app.kubernetes.io/name=ms-process-billing --prefix --tail=-1 > logs.txt
  python tools/analizar_sobrecosto.py logs.txt [--por-pod]

Lee las lineas JSON "mensaje procesado" (admite el prefijo `[pod/<nombre>/<contenedor>]` de --prefix y lineas
no JSON, que se ignoran) y reporta count/mean/p50/p90/p95/p99/max por etapa en ms, el sobrecosto frente al retardo
simulado y la tasa observada (mensajes/s entre el primer y el ultimo mensaje).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict

ETAPAS = ["claimMs", "delayMs", "sqsMs", "updateMs", "commitMs", "pollMs", "handleMs", "totalMs", "sobrecostoMs"]
PREFIX = re.compile(r"^\[pod/([^/\]]+)(?:/[^\]]*)?\]\s*")


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def parse(lines):
    for line in lines:
        pod = None
        m = PREFIX.match(line)
        if m:
            pod, line = m.group(1), line[m.end():]
        i = line.find("{")
        if i < 0:
            continue
        try:
            rec = json.loads(line[i:])
        except ValueError:
            continue
        if rec.get("message") == "mensaje procesado":
            rec["_pod"] = pod or rec.get("pod") or "?"
            yield rec


def stats(vals: list[float]) -> dict:
    s = sorted(vals)
    return {"n": len(s), "mean": sum(s) / len(s) if s else 0.0, "p50": percentile(s, .5), "p90": percentile(s, .9),
            "p95": percentile(s, .95), "p99": percentile(s, .99), "max": s[-1] if s else 0.0}


def tabla(recs: list[dict]) -> list[str]:
    out = [f"{'etapa':<14}{'n':>7}{'media':>10}{'p50':>10}{'p90':>10}{'p95':>10}{'p99':>10}{'max':>10}   (ms)"]
    for e in ETAPAS:
        vals = [float(r[e]) for r in recs if r.get(e) is not None]
        if not vals:
            continue
        s = stats(vals)
        out.append(f"{e:<14}{s['n']:>7}{s['mean']:>10.1f}{s['p50']:>10.1f}{s['p90']:>10.1f}{s['p95']:>10.1f}{s['p99']:>10.1f}{s['max']:>10.1f}")
    return out


def epoch(r: dict):
    from datetime import datetime, timezone
    ts = r.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", help="salida de kubectl logs ('-' = stdin)")
    ap.add_argument("--por-pod", action="store_true", help="tabla adicional por pod")
    a = ap.parse_args(argv)
    f = sys.stdin if a.archivo == "-" else open(a.archivo, encoding="utf-8", errors="replace")
    with f:
        recs = list(parse(f))
    if not recs:
        print("No hay lineas 'mensaje procesado' en el archivo.")
        return 1
    print(f"Mensajes analizados: {len(recs)}  pods: {len({r['_pod'] for r in recs})}")
    print("\n".join(tabla(recs)))
    ts = [t for t in map(epoch, recs) if t is not None]
    if len(ts) > 1 and max(ts) > min(ts):
        span = max(ts) - min(ts)
        print(f"\nVentana {span:.0f} s -> {len(recs) / span:.2f} msg/s observados (suma de todos los pods)")
    delay = sum(float(r.get("delayMs") or 0) for r in recs) / len(recs)
    sobre = sum(float(r.get("sobrecostoMs") or 0) for r in recs) / len(recs)
    print(f"Retardo simulado medio {delay:.0f} ms; sobrecosto medio {sobre:.0f} ms ({100 * sobre / (delay + sobre):.1f}% del tiempo por mensaje)"
          if delay + sobre else "")
    if a.por_pod:
        por = defaultdict(list)
        for r in recs:
            por[r["_pod"]].append(r)
        for pod, rs in sorted(por.items()):
            print(f"\n== {pod} ({len(rs)} mensajes)")
            print("\n".join(tabla(rs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
