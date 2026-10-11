"""Configuracion del runner: salidas de `terraform output -json` (base y, si aplica, platform) o un JSON propio.

Formatos aceptados (se puede mezclar varios archivos/fuentes; los valores posteriores pisan a los anteriores):
  * salida cruda de terraform: {"sqs": {"value": {...}, "type": ...}, ...}
  * JSON ya "desenvuelto": {"sqs": {...}, ...}
  * clave opcional "runner": {...} con overrides (namespaces de k8s, nombres de deployment, etc.)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]  # codigo_fuente_voltera/
DEFAULT_BASE_DIR = ROOT / "infra" / "terraform" / "base"
DEFAULT_PLATFORM_DIR = ROOT / "infra" / "terraform" / "ephemeral" / "platform"
REPORTS_DIR = ROOT / "experiments" / "reports"
SEED_DIR = ROOT / "experiments" / "seed"
ASYNCAPI_PATH = ROOT / "mesh" / "asyncapi.yaml"

SERVICES = ["ms-orchestrator-billing", "outbox-relay", "ms-tarifas", "ms-calculo-consumo-neto",
            "ms-facturacion", "ms-comprobante-factura"]
TABLE_KEYS = ["transacciones", "outbox", "process-billing", "idem-facturacion", "idem-comprobante"]


class ConfigError(RuntimeError):
    pass


def unwrap(obj: Any) -> Any:
    """Quita el envoltorio {"value":..., "type":...} de `terraform output -json` (solo en el primer nivel)."""
    if not isinstance(obj, dict):
        return obj
    return {k: (v["value"] if isinstance(v, dict) and "value" in v and "type" in v else v) for k, v in obj.items()}


def terraform_output(chdir: Path, runner=None) -> dict:
    run = runner or subprocess.run
    cp = run(["terraform", f"-chdir={chdir}", "output", "-json"], capture_output=True, text=True, timeout=60)
    if cp.returncode != 0:
        raise ConfigError(f"terraform output fallo en {chdir}: {cp.stderr.strip()[:300]}")
    return unwrap(json.loads(cp.stdout or "{}"))


@dataclass
class Config:
    region: str = "us-east-1"
    profile: str | None = None
    prefix: str = "voltera-exp2"
    tables: dict[str, str] = field(default_factory=dict)
    queues: dict[str, dict[str, str]] = field(default_factory=dict)  # transacciones|comprobantes -> url,arn,dlq_url,dlq_arn
    bus_name: str = ""
    lambdas: dict[str, dict[str, str]] = field(default_factory=dict)
    sfn_arn: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    # Kubernetes
    app_namespace: str = "voltera"
    kafka_namespace: str = "kafka"
    deployment: str = "ms-process-billing"
    scaledobject: str = "ms-process-billing"
    kube_context: str | None = None
    topic_ingreso: str = "voltera.consumo-facturable-preparado"
    topic_eventos: str = "voltera.eventos"
    topic_eventos_mirror: str = "billing.voltera.eventos"
    kafka_cluster_billing: str = "billing"
    kafka_cluster_dominios: str = "dominios"
    schema_registry_url: str = "http://apicurio-registry.kafka.svc:8080/apis/registry/v3"
    placeholder: bool = False  # True = valores por defecto (dry-run sin config)

    # ---- accesores
    def table(self, key: str) -> str:
        try:
            return self.tables[key]
        except KeyError as exc:
            raise ConfigError(f"falta la tabla '{key}' en la configuracion") from exc

    def queue(self, key: str) -> dict[str, str]:
        try:
            return self.queues[key]
        except KeyError as exc:
            raise ConfigError(f"falta la cola '{key}' en la configuracion") from exc

    def lambda_name(self, service: str) -> str:
        info = self.lambdas.get(service)
        return info["name"] if info else f"{self.prefix}-{service}"

    def param(self, name: str, default: Any = None) -> Any:
        v = self.params.get(name)
        return default if v is None else v

    @property
    def n_default(self) -> int:
        return int(self.param("n_solicitudes", 10))

    @classmethod
    def defaults(cls, prefix: str = "voltera-exp2", region: str = "us-east-1", profile: str | None = None) -> "Config":
        base = f"https://sqs.{region}.amazonaws.com/000000000000"
        arn = f"arn:aws:sqs:{region}:000000000000"
        q = {}
        for k in ("transacciones", "comprobantes"):
            q[k] = {"url": f"{base}/{prefix}-{k}", "arn": f"{arn}:{prefix}-{k}",
                    "dlq_url": f"{base}/{prefix}-{k}-dlq", "dlq_arn": f"{arn}:{prefix}-{k}-dlq"}
        return cls(
            region=region, profile=profile, prefix=prefix, tables={k: f"{prefix}-{k}" for k in TABLE_KEYS}, queues=q,
            bus_name=f"{prefix}-bus", lambdas={s: {"name": f"{prefix}-{s}", "arn": ""} for s in SERVICES},
            sfn_arn=f"arn:aws:states:{region}:000000000000:stateMachine:{prefix}-facturacion",
            params={"n_solicitudes": 10, "simulated_delay_seconds": 5, "keda_lag_threshold": 2, "process_billing_min": 1,
                    "process_billing_max": 5, "batch_sla_seconds": 120, "max_receive_count": 3,
                    "sfn_retry": {"max_attempts": 3, "interval_seconds": 2, "backoff_rate": 2.0}},
            placeholder=True,
        )

    @classmethod
    def from_outputs(cls, merged: dict, region: str | None = None, profile: str | None = None, prefix: str | None = None) -> "Config":
        d = merged
        names = (d.get("dynamodb_tables") or {}).get("names", {})
        sqs = d.get("sqs") or {}
        bus = (d.get("eventbridge") or {}).get("bus_name", "")
        if not prefix:
            prefix = bus[:-4] if bus.endswith("-bus") else "voltera-exp2"
        cfg = cls.defaults(prefix, region or d.get("region") or "us-east-1", profile)
        cfg.placeholder = False
        if names:
            cfg.tables = dict(names)
        if sqs:
            cfg.queues = {k: dict(v) for k, v in sqs.items()}
        if bus:
            cfg.bus_name = bus
        if d.get("lambdas"):
            cfg.lambdas = {k: dict(v) for k, v in d["lambdas"].items()}
        if d.get("step_functions"):
            cfg.sfn_arn = d["step_functions"].get("arn", cfg.sfn_arn)
        if d.get("experiment_parameters"):
            cfg.params = dict(d["experiment_parameters"])
            cfg.topic_ingreso = cfg.params.get("kafka_topic", cfg.topic_ingreso)
        for k, v in (d.get("runner") or {}).items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        if d.get("schema_registry_url_internal"):
            cfg.schema_registry_url = d["schema_registry_url_internal"]
        return cfg


def load_config(config_path: str | None = None, *, dry_run: bool = False, region: str | None = None,
                profile: str | None = None, prefix: str | None = None, tf_runner=None) -> Config:
    region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    profile = profile or os.environ.get("AWS_PROFILE")
    prefix = prefix or os.environ.get("VOLTERA_PREFIX")
    merged: dict = {}
    if config_path:
        merged.update(unwrap(json.loads(Path(config_path).read_text(encoding="utf-8"))))
    elif not dry_run:
        base_dir = Path(os.environ.get("VOLTERA_TF_BASE_DIR", DEFAULT_BASE_DIR))
        merged.update(terraform_output(base_dir, tf_runner))
        plat_dir = Path(os.environ.get("VOLTERA_TF_PLATFORM_DIR", DEFAULT_PLATFORM_DIR))
        try:  # platform es opcional (puede no estar aplicado)
            merged.update({k: v for k, v in terraform_output(plat_dir, tf_runner).items() if k not in merged})
        except (ConfigError, OSError, json.JSONDecodeError):
            pass
    if not merged:
        return Config.defaults(prefix or "voltera-exp2", region, profile)
    return Config.from_outputs(merged, region, profile, prefix)
