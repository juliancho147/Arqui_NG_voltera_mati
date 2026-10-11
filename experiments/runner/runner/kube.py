"""Ejecutor de kubectl inyectable. En produccion usa subprocess; en tests se reemplaza por un falso."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass
class KubeResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class KubeError(RuntimeError):
    pass


Runner = Callable[[list[str], float], KubeResult]


def subprocess_runner(args: list[str], timeout: float) -> KubeResult:
    cp = subprocess.run(["kubectl", *args], capture_output=True, text=True, timeout=timeout)
    return KubeResult(cp.returncode, cp.stdout, cp.stderr)


class Kube:
    def __init__(self, runner: Runner | None = None, context: str | None = None):
        self.runner = runner or subprocess_runner
        self.context = context
        self.calls: list[list[str]] = []

    def run(self, args: list[str], timeout: float = 60, check: bool = True) -> KubeResult:
        full = (["--context", self.context] if self.context else []) + list(args)
        self.calls.append(full)
        res = self.runner(full, timeout)
        if check and res.returncode != 0:
            raise KubeError(f"kubectl {' '.join(full[:6])} fallo ({res.returncode}): {res.stderr.strip()[:300]}")
        return res

    def get_json(self, args: list[str], timeout: float = 60) -> dict:
        res = self.run(["get", *args, "-o", "json"], timeout)
        return json.loads(res.stdout or "{}")

    # ---- consultas
    def deployment_status(self, ns: str, name: str) -> dict:
        d = self.get_json(["deploy", name, "-n", ns])
        st = d.get("status", {})
        return {"spec": d.get("spec", {}).get("replicas"), "replicas": st.get("replicas", 0),
                "ready": st.get("readyReplicas", 0), "available": st.get("availableReplicas", 0), "raw": d}

    def hpa_desired(self, ns: str, scaledobject: str) -> int | None:
        """KEDA crea un HPA 'keda-hpa-<scaledobject>'. Devuelve desiredReplicas o None si no existe."""
        res = self.run(["get", "hpa", f"keda-hpa-{scaledobject}", "-n", ns, "-o", "json"], check=False)
        if res.returncode != 0:
            return None
        return json.loads(res.stdout).get("status", {}).get("desiredReplicas")

    def pods(self, ns: str, selector: str) -> list[dict]:
        items = self.get_json(["pods", "-n", ns, "-l", selector]).get("items", [])
        return [{"name": p["metadata"]["name"], "phase": p.get("status", {}).get("phase"),
                 "uid": p["metadata"].get("uid"),
                 "ready": all(c.get("ready") for c in p.get("status", {}).get("containerStatuses", []) or [{}])}
                for p in items if not p["metadata"].get("deletionTimestamp")]

    def delete_pod(self, ns: str, name: str, force: bool = True) -> KubeResult:
        extra = ["--grace-period=0", "--force"] if force else []
        return self.run(["delete", "pod", name, "-n", ns, *extra], timeout=90)

    def exec(self, ns: str, pod: str, command: list[str], container: str | None = None, timeout: float = 120,
             check: bool = True) -> KubeResult:
        c = ["-c", container] if container else []
        return self.run(["exec", "-n", ns, pod, *c, "--", *command], timeout=timeout, check=check)
