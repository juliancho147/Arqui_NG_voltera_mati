"""Exp. 4 - Event Mesh: completitud, linea de tiempo, replay, MirrorMaker 2 y contrato de eventos."""
from __future__ import annotations

import collections
import copy

from .. import actions, evidence, mesh
from ..kube import KubeError
from ..report import ExperimentResult
from .base import Experiment, fmt_ids


class Exp4(Experiment):
    name = "exp4"
    title = "Exp. 4 - Event Mesh (observabilidad y contexto de eventos)"
    hypothesis = ("El mesh registra todos los eventos con su correlacion, permite reconstruir el recorrido de cada factura, hace replay "
                  "sin efectos duplicados, replica a 'dominios' y los eventos cumplen el catalogo AsyncAPI.")

    def plan(self) -> list[str]:
        c = self.cfg
        return [
            (f"Disparar el cierre: seed de {self.n} transacciones + PutEvents CierreDeMes (ciclo {self.ciclo_id})"
             if not self.ctx.opt("no_dispatch", False) else f"Reutilizar el ciclo existente {self.ciclo_id} (--no-dispatch)"),
            f"Esperar a que el ciclo termine (META COMPLETADO / {self.n} FACT# terminales en {c.table('process-billing')})",
            f"Leer {c.topic_eventos} del clúster '{c.kafka_cluster_billing}': kubectl exec -n {c.kafka_namespace} <pod billing> -- kafka-console-consumer.sh --from-beginning",
            "Completitud: eventos esperados por factura (segun FACT#) vs recibidos; cada evento con cicloid/facturaid/subject/clave/headers",
            "Linea de tiempo por factura (orden por `time`, coherente con el orden canonico del flujo y con el estado FACT#)",
            "Replay por offset (--partition P --offset 0) en cada particion: mismos ids, sin ids duplicados; estado de DynamoDB sin cambios",
            f"Comparar con {c.topic_eventos_mirror} en el clúster '{c.kafka_cluster_dominios}' (MirrorMaker 2) hasta {int(self.ctx.opt('mirror_timeout', 90))} s",
            "Validar cada evento contra mesh/asyncapi.yaml (jsonschema) y comprobar que un evento invalido (sin cicloid) se detecta",
            f"Apicurio ({c.schema_registry_url}): intentar listar artefactos via curl desde un pod; si no es accesible, queda como paso MANUAL",
            "Trazas X-Ray / dashboard de CloudWatch: paso MANUAL",
        ]

    def execute(self, r: ExperimentResult) -> None:
        ctx, c, n = self.ctx, self.cfg, self.n
        ciclo = self.ciclo_id
        if ctx.opt("no_dispatch", False):
            ids = evidence.injected_ids(ctx, ciclo)
            n = self.n = len(ids)
        else:
            d = actions.dispatch_cierre(ctx, ciclo, n, retardo_segundos=ctx.opt("delay"))
            ids = d["facturaIds"]
        r.params["N"] = n

        def finished():
            return len(evidence.fact_states(ctx, ciclo)) >= n
        ok, secs = ctx.wait_until(finished, float(ctx.opt("timeout", 300)), ctx.opt("poll", 5))
        facts = evidence.fact_states(ctx, ciclo)
        meta = evidence.ciclo_meta(ctx, ciclo)
        r.add("E4.0", "Precondicion: el ciclo termina antes de auditar el mesh", bool(ok), f"{n} FACT# terminales",
              f"{len(facts)} en {secs:.0f} s; META={meta.get('estado')}", meta=meta)

        # ---- lectura del mesh
        try:
            recs = mesh.consume(ctx, c.kafka_cluster_billing, c.topic_eventos, timeout_ms=int(ctx.opt("kafka_timeout_ms", 20000)))
        except KubeError as exc:
            r.add("E4.1", "Lectura de voltera.eventos en el clúster billing (kubectl exec)", False, "eventos legibles", str(exc))
            return
        mine = [x for x in recs if x.value and x.value.get("cicloid") == ciclo]
        per = collections.defaultdict(list)
        for x in mine:
            per[x.value["facturaid"]].append(x)

        # ---- completitud
        faltantes: dict[str, list[str]] = {}
        esperados = recibidos = 0
        for f in ids:
            obs = {mesh.type_to_name(x.value["type"]) for x in per.get(f, [])}
            exp = mesh.expected_types(facts.get(f), obs)
            esperados += len(exp)
            miss = [t for t in exp if t not in obs]
            recibidos += len(exp) - len(miss)
            if miss:
                faltantes[f] = miss
        ciclo_names = collections.Counter(mesh.type_to_name(x.value["type"]) for x in per.get("CICLO", []))
        ciclo_exp = ["CicloDeFacturacionIniciado"] + (["ProcesoDeFacturacionCompletado"] if meta.get("estado") == "COMPLETADO"
                                                       else ["ProcesoDeFacturacionFallido"] if meta.get("estado") == "FALLIDO" else [])
        ciclo_miss = [t for t in ciclo_exp if ciclo_names[t] == 0]
        esperados += len(ciclo_exp)
        recibidos += len(ciclo_exp) - len(ciclo_miss)
        r.add("E4.1", "Completitud: eventos esperados por factura (y de nivel ciclo) presentes en el mesh", not faltantes and not ciclo_miss,
              f"{esperados} eventos", f"{recibidos} recibidos; facturas con faltantes={len(faltantes)}; ciclo faltantes={ciclo_miss}",
              esperados=esperados, recibidos=recibidos, faltantes=faltantes, eventosDeCiclo=dict(ciclo_names), totalLeidos=len(recs), delCiclo=len(mine))

        # ---- correlacion
        malos = []
        for x in mine:
            v, h = x.value, x.headers
            problemas = []
            if not v.get("facturaid") or not v.get("cicloid"):
                problemas.append("falta cicloid/facturaid")
            if v.get("subject") != v.get("facturaid"):
                problemas.append("subject != facturaid")
            if x.key is not None and x.key != v.get("facturaid"):
                problemas.append("clave != facturaid")
            if h and (h.get("cicloId") != v.get("cicloid") or h.get("facturaId") != v.get("facturaid")):
                problemas.append("headers != extensiones")
            if problemas:
                malos.append({"id": v.get("id"), "type": v.get("type"), "problemas": problemas})
        r.add("E4.2", "Todo evento lleva correlacion cicloId + facturaId (extensiones, subject, clave y headers coherentes)",
              not malos and bool(mine), "100% de los eventos", f"{len(mine) - len(malos)}/{len(mine)} correctos", incorrectos=malos[:10],
              conHeaders=sum(1 for x in mine if x.headers))

        # ---- linea de tiempo
        orden = {t: i for i, t in enumerate(mesh.CANONICAL_ORDER)}
        timeline, desorden = {}, {}
        for f in ids:
            evs = sorted(per.get(f, []), key=lambda x: (x.value.get("time", ""), orden.get(mesh.type_to_name(x.value["type"]), 99)))
            names = [mesh.type_to_name(x.value["type"]) for x in evs]
            timeline[f] = [{"time": x.value.get("time"), "evento": nm, "source": x.value.get("source"), "particion": x.partition, "offset": x.offset}
                           for x, nm in zip(evs, names)]
            idx = [orden.get(nm, 99) for nm in names]
            terminal_ok = (facts.get(f) != "OK") or (names and names[-1] == "FacturaNotificada")
            if idx != sorted(idx) or not terminal_ok:
                desorden[f] = names
        r.data["lineaDeTiempo"] = timeline
        r.add("E4.3", "Se reconstruye la linea de tiempo completa de cada factura desde el mesh (orden coherente y cierre acorde al estado FACT#)",
              not desorden and all(timeline.values()), "orden canonico y ultimo evento acorde al estado",
              f"{len(timeline) - len(desorden)}/{len(timeline)} facturas coherentes", incoherentes=desorden,
              ejemplo={k: [e["evento"] for e in v] for k, v in list(timeline.items())[:2]})

        # ---- duplicados e ids
        id_count = collections.Counter(x.id for x in mine)
        dup_ids = [i for i, k in id_count.items() if k > 1]

        # ---- replay por offset
        self._replay(r, mine, facts, meta, dup_ids)

        # ---- MirrorMaker 2
        self._mirror(r, mine)

        # ---- contrato
        self._contract(r, mine)

        r.manual("E4.9", "Trazas X-Ray / dashboard de CloudWatch muestran el estado del ciclo en vivo",
                 "Abrir la consola de X-Ray (service map) y el dashboard de CloudWatch durante la corrida; el runner no los consulta.")
        r.manual("E4.10", "Consumidor de reportes en 'dominios' recibe los eventos sin tocar los servicios existentes",
                 "No hay manifiesto de un consumidor de reportes en k8s/ (ver incidencias); la replicacion se verifica leyendo billing.voltera.eventos (E4.6).")

    # ------------------------------------------------------------------
    def _snapshot(self, ids) -> dict:
        ctx, ciclo = self.ctx, self.ciclo_id
        return {"meta": evidence.ciclo_meta(ctx, ciclo), "fact": evidence.fact_states(ctx, ciclo),
                "emitidas": sorted(evidence.account(ctx, ciclo, ids).emitidas.items()), "consecutivo": evidence.consecutivo(ctx)}

    def _replay(self, r, mine, facts, meta, dup_ids) -> None:
        ctx, c = self.ctx, self.cfg
        parts = collections.defaultdict(list)
        for x in mine:
            parts[x.partition].append(x)
        if None in parts or not parts:
            r.manual("E4.4", "Replay por offset sin duplicados", "No se pudo parsear particion/offset de la salida del consumidor.")
            return
        ids = sorted(facts)
        before = self._snapshot(ids)
        diffs = {}
        for p, lst in parts.items():
            # El topico mezcla ciclos: se relee TODA la particion y se filtra el ciclo.
            todo = sorted(lst, key=lambda x: x.offset)
            hasta = todo[-1].offset
            rep = mesh.consume(ctx, c.kafka_cluster_billing, c.topic_eventos, partition=p, offset=0, max_messages=hasta + 1,
                               timeout_ms=int(ctx.opt("kafka_timeout_ms", 20000)))
            a = [x.id for x in todo]
            b = [x.id for x in sorted(rep, key=lambda x: x.offset) if x.value and x.value.get("cicloid") == self.ciclo_id]
            if a != b:
                diffs[p] = {"original": a, "replay": b}
        after = self._snapshot(ids)
        r.add("E4.4", "Replay por offset (--partition P --offset 0) reproduce los mismos eventos, sin ids repetidos",
              not diffs and not dup_ids, "ids identicos por particion; 0 ids duplicados",
              f"particiones={sorted(parts)} difs={len(diffs)} idsRepetidos={len(dup_ids)}", diferencias=diffs, idsRepetidos=dup_ids)
        r.add("E4.5", "El replay no produce efectos duplicados (estado de DynamoDB sin cambios: ciclo, FACT#, facturas, consecutivo)",
              before == after, "snapshot antes == despues", "iguales" if before == after else "difieren",
              antes=before if before != after else "igual", despues=after if before != after else "igual")

    def _mirror(self, r, mine) -> None:
        ctx, c = self.ctx, self.cfg
        want = {x.id for x in mine}

        def mirrored():
            try:
                recs = mesh.consume(ctx, c.kafka_cluster_dominios, c.topic_eventos_mirror, timeout_ms=int(ctx.opt("kafka_timeout_ms", 20000)))
            except KubeError:
                return None
            got = {x.id for x in recs if x.value and x.value.get("cicloid") == self.ciclo_id}
            self._mirror_got = got
            return got >= want
        self._mirror_got = set()
        try:
            ok, secs = ctx.wait_until(mirrored, float(ctx.opt("mirror_timeout", 90)), 10)
        except KubeError as exc:
            r.add("E4.6", "MirrorMaker 2 replica billing.voltera.eventos en 'dominios'", False, "todos los eventos replicados", str(exc))
            return
        faltan = sorted(want - self._mirror_got)
        r.add("E4.6", "MirrorMaker 2 replica los eventos de billing a dominios (billing.voltera.eventos)", bool(ok), f"{len(want)} eventos",
              f"{len(self._mirror_got & want)} replicados en {secs:.0f} s", faltan=faltan[:10])

    def _contract(self, r, mine) -> None:
        ctx = self.ctx
        try:
            cat = mesh.load_catalog(ctx.opt("asyncapi", mesh.ASYNCAPI_PATH))
        except Exception as exc:  # noqa: BLE001
            r.add("E4.7", "Eventos validan contra mesh/asyncapi.yaml", False, "catalogo cargable", f"{type(exc).__name__}: {exc}")
            return
        errores = {}
        for x in mine:
            e = cat.validate(x.value)
            if e:
                errores[x.id] = {"type": x.value.get("type"), "errores": e}
        r.add("E4.7", "Los eventos validan contra el catalogo AsyncAPI (mesh/asyncapi.yaml)", not errores and bool(mine),
              "0 eventos invalidos", f"{len(mine) - len(errores)}/{len(mine)} validos", invalidos=dict(list(errores.items())[:10]),
              tiposCatalogo=len(cat.by_type))
        if mine:
            bad = copy.deepcopy(mine[0].value)
            bad.pop("cicloid", None)
            detectado = bool(cat.validate(bad))
            r.add("E4.8", "Un evento invalido (sin cicloid) se detecta con el esquema", detectado, "validacion falla", "detectado" if detectado else "NO detectado")
        arts = mesh.fetch_registry_artifacts(ctx)
        if arts is None:
            r.manual("E4.8b", "Esquemas registrados en Apicurio", f"Apicurio no accesible desde el runner ({ctx.cfg.schema_registry_url}). "
                     "El registro de esquemas desde asyncapi.yaml es un paso manual (registro en memoria): publicar y validar contra el registro a mano.")
        else:
            r.add("E4.8b", "Esquemas registrados en Apicurio", len(arts) > 0, ">= 1 artefacto", f"{len(arts)} artefactos", artefactos=arts[:20])
