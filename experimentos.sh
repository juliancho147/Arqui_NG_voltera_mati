#!/usr/bin/env bash
# =============================================================================
#  Voltera · Validacion experimental Blockchain (local)   —  Modo Maestria
#  Universidad de los Andes
#  Grupo: Julian Builes · Mario Montero · Carlos Garavito · Juan Puentes
# =============================================================================
#  Utilitario para: arrancar/parar Anvil, desplegar contratos y correr los
#  experimentos E1 / E2 / E3 (o todos) mostrando los resultados en pantalla.
# =============================================================================
set -uo pipefail

# ---------------------------------------------------------------------------
# Rutas y constantes
# ---------------------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_DIR="$ROOT/experiments/runner-blockchain"
VENV_PY="$RUNNER_DIR/.venv/bin/python"
REPORTS_DIR="$ROOT/experiments/reports-blockchain"
DEPLOYMENT="$ROOT/deployment.json"
ENV_FILE="$ROOT/.env"
ANVIL_LOG="/tmp/voltera-anvil.log"
ANVIL_PID_FILE="/tmp/voltera-anvil.pid"

RPC_URL="http://127.0.0.1:8545"
CHAIN_ID=11155111
# Llave de desarrollo PUBLICA de la cuenta 0 de Anvil (no es un secreto real).
PLATAFORMA_PK="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

export PATH="$HOME/.foundry/bin:$PATH"
export PLATAFORMA_PRIVATE_KEY="$PLATAFORMA_PK"

# ---------------------------------------------------------------------------
# Colores
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
  C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'; C_MAG=$'\033[35m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_CYAN=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_BLUE=""; C_MAG=""
fi

# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
linea() { printf '%s\n' "${C_DIM}------------------------------------------------------------------------${C_RESET}"; }

banner() {
  clear 2>/dev/null || true
  printf '%s' "$C_CYAN$C_BOLD"
  cat <<'ART'
 __     __    _ _                   _     _            _        _
 \ \   / /__ | | |_ ___ _ __ __ _  | |__ | | ___   ___| | _____| |__   __ _(_)_ __
  \ \ / / _ \| | __/ _ \ '__/ _` | | '_ \| |/ _ \ / __| |/ / __| '_ \ / _` | | '_ \
   \ V / (_) | | ||  __/ | | (_| | | |_) | | (_) | (__|   < (__| | | | (_| | | | | |
    \_/ \___/|_|\__\___|_|  \__,_| |_.__/|_|\___/ \___|_|\_\___|_| |_|\__,_|_|_| |_|
ART
  printf '%s' "$C_RESET"
  printf '%s\n' "${C_BOLD}  Validacion experimental Blockchain (local) — Modo Maestria${C_RESET}"
  printf '%s\n' "${C_DIM}  Universidad de los Andes${C_RESET}"
  printf '%s\n' "${C_MAG}  Grupo: Julian Builes · Mario Montero · Carlos Garavito · Juan Puentes${C_RESET}"
  linea
}

info()  { printf '%s\n' "${C_BLUE}[i]${C_RESET} $*"; }
ok()    { printf '%s\n' "${C_GREEN}[ok]${C_RESET} $*"; }
warn()  { printf '%s\n' "${C_YELLOW}[!]${C_RESET} $*"; }
err()   { printf '%s\n' "${C_RED}[x]${C_RESET} $*"; }
paso()  { printf '%s\n' "${C_CYAN}${C_BOLD}==>${C_RESET} ${C_BOLD}$*${C_RESET}"; }

pausa() { printf '\n%s' "${C_DIM}Enter para continuar...${C_RESET}"; read -r _; }

# ---------------------------------------------------------------------------
# Chequeos de entorno
# ---------------------------------------------------------------------------
cargar_env() {
  if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
  fi
}

verificar_requisitos() {
  local faltan=0
  command -v anvil >/dev/null 2>&1 || { err "no se encontro 'anvil' (instala Foundry)"; faltan=1; }
  command -v forge >/dev/null 2>&1 || { err "no se encontro 'forge' (instala Foundry)"; faltan=1; }
  [ -x "$VENV_PY" ] || { err "no se encontro el venv en $VENV_PY"; faltan=1; }
  return $faltan
}

anvil_vivo() {
  curl -s -X POST "$RPC_URL" -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' 2>/dev/null \
    | grep -q '"result"'
}

contratos_desplegados() {
  [ -f "$DEPLOYMENT" ] || return 1
  local addr
  addr=$("$VENV_PY" - "$DEPLOYMENT" <<'PY' 2>/dev/null
import json,sys
print(json.load(open(sys.argv[1]))["contratos"]["MarketEscrow"])
PY
)
  [ -n "$addr" ] || return 1
  local code
  code=$(curl -s -X POST "$RPC_URL" -H 'Content-Type: application/json' \
    --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$addr\",\"latest\"]}" 2>/dev/null)
  echo "$code" | grep -q '"0x0x' && return 1
  echo "$code" | grep -qE '"result":"0x[0-9a-fA-F]{2,}"' && return 0
  return 1
}

estado_breve() {
  if anvil_vivo; then
    local bn; bn=$(curl -s -X POST "$RPC_URL" -H 'Content-Type: application/json' \
      --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' | sed -E 's/.*"result":"([^"]+)".*/\1/')
    printf '%s\n' "  Cadena Anvil : ${C_GREEN}activa${C_RESET} (${RPC_URL}, bloque ${bn})"
  else
    printf '%s\n' "  Cadena Anvil : ${C_RED}detenida${C_RESET}"
  fi
  if contratos_desplegados; then
    printf '%s\n' "  Contratos    : ${C_GREEN}desplegados${C_RESET} (deployment.json)"
  else
    printf '%s\n' "  Contratos    : ${C_YELLOW}no desplegados${C_RESET}"
  fi
  if [ -f "$ENV_FILE" ] && grep -q '^PINATA_JWT=' "$ENV_FILE" 2>/dev/null; then
    printf '%s\n' "  Pinata       : ${C_GREEN}credencial presente${C_RESET} (.env)"
  else
    printf '%s\n' "  Pinata       : ${C_YELLOW}sin credencial${C_RESET} (E2 usara fallback local)"
  fi
}

# ---------------------------------------------------------------------------
# Anvil: arrancar / parar
# ---------------------------------------------------------------------------
arrancar_anvil() {
  paso "Arrancar la Cadena_Local (Anvil)"
  if anvil_vivo; then warn "Anvil ya esta corriendo en $RPC_URL"; return 0; fi
  info "lanzando anvil --chain-id $CHAIN_ID --port 8545 ..."
  nohup anvil --chain-id "$CHAIN_ID" --port 8545 --host 127.0.0.1 >"$ANVIL_LOG" 2>&1 &
  echo $! > "$ANVIL_PID_FILE"
  local i
  for i in $(seq 1 30); do
    anvil_vivo && { ok "Anvil listo (pid $(cat "$ANVIL_PID_FILE"), log $ANVIL_LOG)"; return 0; }
    sleep 0.5
  done
  err "Anvil no respondio en 15 s; revisa $ANVIL_LOG"; return 1
}

parar_anvil() {
  paso "Detener la Cadena_Local (Anvil)"
  local matados=0
  if [ -f "$ANVIL_PID_FILE" ]; then
    local pid; pid=$(cat "$ANVIL_PID_FILE")
    kill "$pid" 2>/dev/null && matados=1
    rm -f "$ANVIL_PID_FILE"
  fi
  # Respaldo: cualquier anvil escuchando en 8545
  local extra; extra=$(lsof -ti :8545 2>/dev/null)
  [ -n "$extra" ] && kill $extra 2>/dev/null && matados=1
  [ "$matados" = "1" ] && ok "Anvil detenido" || warn "no habia proceso de Anvil que detener"
}

limpiar_servicios() {
  local pt pids algo=0
  for pt in 8080 8081 8083 8084 8085; do
    pids=$(lsof -ti :$pt 2>/dev/null)
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null && algo=1
  done
  [ "$algo" = "1" ] && warn "se limpiaron microservicios huerfanos (8080-8085)"
}

# ---------------------------------------------------------------------------
# Despliegue de contratos
# ---------------------------------------------------------------------------
desplegar() {
  paso "Desplegar contratos (EnergyToken + MarketEscrow)"
  anvil_vivo || { err "Anvil no esta corriendo; arrancalo primero (opcion 1)"; return 1; }
  info "forge script Desplegar.s.sol --broadcast (cwd blockchain/)"
  local out
  out=$(cd "$ROOT/blockchain" && forge script script/Desplegar.s.sol \
    --rpc-url "$RPC_URL" --private-key "$PLATAFORMA_PK" --broadcast 2>&1)
  if ! echo "$out" | grep -q "ONCHAIN EXECUTION COMPLETE & SUCCESSFUL"; then
    err "fallo el despliegue:"; echo "$out" | tail -15; return 1
  fi
  local et me plat
  et=$(echo "$out"   | sed -nE 's/.*EnergyToken[[:space:]]*:[[:space:]]*(0x[0-9a-fA-F]{40}).*/\1/p'  | head -1)
  me=$(echo "$out"   | sed -nE 's/.*MarketEscrow[[:space:]]*:[[:space:]]*(0x[0-9a-fA-F]{40}).*/\1/p'  | head -1)
  plat=$(echo "$out" | sed -nE 's/.*plataforma[[:space:]]*:[[:space:]]*(0x[0-9a-fA-F]{40}).*/\1/p'    | head -1)
  "$VENV_PY" - "$DEPLOYMENT" "$et" "$me" "$plat" "$(forge --version 2>/dev/null | head -1)" <<'PY'
import json,sys,datetime
dst,et,me,plat,forge=sys.argv[1:6]
json.dump({
  "chainId":11155111,"rpcUrl":"http://localhost:8545","plataforma":plat,
  "contratos":{"EnergyToken":et,"MarketEscrow":me},
  "herramientas":{"foundry":forge},
  "desplegadoEn":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
}, open(dst,"w"), indent=2)
PY
  ok "contratos desplegados y deployment.json escrito"
  printf '    %s\n' "${C_DIM}EnergyToken : $et${C_RESET}"
  printf '    %s\n' "${C_DIM}MarketEscrow: $me${C_RESET}"
}

asegurar_entorno() {
  anvil_vivo || arrancar_anvil || return 1
  contratos_desplegados || desplegar || return 1
  return 0
}

# ---------------------------------------------------------------------------
# Resumen visual de un report.json
# ---------------------------------------------------------------------------
mostrar_reporte() {
  local dir="$1"
  [ -f "$dir/report.json" ] || { err "no se encontro report.json en $dir"; return 1; }
  "$VENV_PY" - "$dir/report.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
G="\033[32m"; R="\033[31m"; Y="\033[33m"; B="\033[1m"; D="\033[2m"; X="\033[0m"; C="\033[36m"
def col(v): return (G if v=="PASS" else R)+v+X
print()
print(f"{B}Reporte de corrida{X} {C}{d['runId']}{X}  ->  veredicto {col(d['verdict'])}")
h=d.get("header",{})
print(f"{D}  inicio {h.get('inicio','')}  fin {h.get('fin','')}{X}")
for e in d.get("experiments",[]):
    print()
    print(f"  {B}{e['experiment']}{X} {e['title']}  [{col(e['verdict'])}]")
    m=e.get("metricas") or {}
    if m:
        kv=", ".join(f"{k}={v}" for k,v in m.items())
        print(f"{D}    metricas: {kv}{X}")
    print(f"    {D}{'Id':<6} {'Estado':<6} Criterio{X}")
    for c in e.get("criteria",[]):
        print(f"    {c['id']:<6} {col(c['status']):<15} {c['title']}")
        if c['status']=="FAIL":
            print(f"{R}        esperado: {c['expected']}{X}")
            print(f"{R}        observado: {c['observed']}{X}")
ev=d.get("evidenciaOnChain",[])
if ev:
    tipos={}
    for x in ev: tipos[x['tipo']]=tipos.get(x['tipo'],0)+1
    gas=sum(int(x.get('gasUsed') or 0) for x in ev)
    print()
    print(f"  {B}Evidencia on-chain{X}: {len(ev)} eventos "
          f"({', '.join(f'{k}={v}' for k,v in sorted(tipos.items()))}), gas total {gas}")
    for x in ev[:3]:
        print(f"{D}    {x['tipo']:<8} tx {x.get('transactionHash','')[:18]}... blk {x.get('blockNumber')} gas {x.get('gasUsed')}{X}")
    if len(ev)>3: print(f"{D}    ... y {len(ev)-3} mas (ver report.md){X}")
print()
print(f"{D}  report.md: {sys.argv[1].replace('report.json','report.md')}{X}")
PY
}

ultimo_reporte_de() {
  # $1 = sufijo del runId (E1|E2|E3) o patron; devuelve el dir mas reciente
  ls -dt "$REPORTS_DIR"/*"$1"* 2>/dev/null | head -1
}

# ---------------------------------------------------------------------------
# Experimentos
# ---------------------------------------------------------------------------
run_e1() {
  paso "E1 — Integridad del Oracle"
  asegurar_entorno || return 1
  cargar_env
  info "corriendo E1 (200 invalidas + 200 validas) con microservicios reales..."
  ( cd "$RUNNER_DIR" && "$VENV_PY" - <<'PY'
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
from pathlib import Path
from runner_blockchain.chain.deployment import load_deployment
from runner_blockchain import cli, servicios as S
from runner_blockchain.experimentos import e1
from runner_blockchain.reporte import reporte_desde_deployment, escribir_reporte
dep=load_deployment(Path("../../deployment.json"))
lector=cli._lector_por_defecto(dep)
desde=lector.client.w3.eth.block_number + 1  # solo eventos de ESTA corrida
ms=S.Microservicios(S.construir_specs(deployment_path=dep.ruta, rpc_url=dep.rpc_url)); ms.iniciar()
try:
    res=e1.ejecutar_e1("RUN-E1", "http://127.0.0.1:8080", lector, from_block=desde)
finally:
    ms.detener()
rep=reporte_desde_deployment("RUN-E1",[res],dep,params={"seleccion":"e1"})
out=escribir_reporte(rep, Path("../reports-blockchain"))
print("Reporte_Resultados escrito en", out)
PY
) 2>&1 | grep -E "veredicto|listo|eventos observados|Reporte_Resultados|FAIL|PASS|ERROR|deteniendo" || true
  local dir; dir=$(ultimo_reporte_de "E1")
  [ -n "$dir" ] && mostrar_reporte "$dir"
}

run_e3() {
  paso "E3 — Tokenizacion sin doble venta"
  local offers="${1:-10}" buys="${2:-10}"
  asegurar_entorno || return 1
  limpiar_servicios
  cargar_env
  info "corriendo E3 con $offers ofertas x $buys compras concurrentes..."
  ( cd "$RUNNER_DIR" && OFFERS="$offers" BUYS="$buys" "$VENV_PY" - <<'PY'
import os,logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
from pathlib import Path
from runner_blockchain.chain.deployment import load_deployment
from runner_blockchain import cli, servicios as S
from runner_blockchain.experimentos import e3
from runner_blockchain.reporte import reporte_desde_deployment, escribir_reporte
offers=int(os.environ["OFFERS"]); buys=int(os.environ["BUYS"])
dep=load_deployment(Path("../../deployment.json"))
lector=cli._lector_por_defecto(dep)
desde=lector.client.w3.eth.block_number + 1  # solo eventos de ESTA corrida (evita contaminacion)
ms=S.Microservicios(S.construir_specs(deployment_path=dep.ruta, rpc_url=dep.rpc_url)); ms.iniciar()
try:
    res=e3.ejecutar_e3("RUN-E3", lector,
                       venta=e3.HttpVentaClient("http://127.0.0.1:8083"),
                       compra=e3.HttpCompraClient("http://127.0.0.1:8084"),
                       repeticiones=offers, compras_por_oferta=buys,
                       from_block=desde)
finally:
    ms.detener()
rep=reporte_desde_deployment("RUN-E3",[res],dep,params={"seleccion":"e3","ofertas":offers,"comprasPorOferta":buys})
out=escribir_reporte(rep, Path("../reports-blockchain"))
print("Reporte_Resultados escrito en", out)
PY
) 2>&1 | grep -E "veredicto|listo|eventos observados|Reporte_Resultados|FAIL|PASS|ERROR|deteniendo" || true
  local dir; dir=$(ultimo_reporte_de "E3")
  [ -n "$dir" ] && mostrar_reporte "$dir"
}

run_e2() {
  paso "E2 — Integridad del certificado off-chain"
  local total="${1:-10}"
  asegurar_entorno || return 1
  cargar_env
  local modo="fallback local"
  [ -n "${PINATA_JWT:-}" ] && modo="Pinata real (subida) + verificacion local"
  info "corriendo E2 con $total alterados — modo: $modo ..."
  ( cd "$RUNNER_DIR" && TOTAL="$total" "$VENV_PY" - <<'PY'
import os,logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
from pathlib import Path
from runner_blockchain.chain.deployment import load_deployment
from runner_blockchain.experimentos import e2
from runner_blockchain.reporte import reporte_desde_deployment, escribir_reporte
total=int(os.environ["TOTAL"]); jwt=os.environ.get("PINATA_JWT") or None
dep=load_deployment(Path("../../deployment.json"))
if jwt:
    backend=e2.construir_backend_pinata_local(dep, jwt=jwt, almacen_dir=Path("../../.certificados-e2"))
    nota="real(subida)+local(verificacion)"
    res=e2.ejecutar(backend, run_id="RUN-E2", total=total)
    print("CIDs reales de Pinata:", len(backend.cids_pinata))
else:
    backend=e2.construir_backend_en_proceso(dep, almacen_dir=Path("../../.certificados-e2"))
    nota="fallback-local"
    res=e2.ejecutar(backend, run_id="RUN-E2", total=total)
rep=reporte_desde_deployment("RUN-E2",[res],dep,params={"seleccion":"e2","totalAlterados":total,"pinata":nota})
out=escribir_reporte(rep, Path("../reports-blockchain"))
print("Reporte_Resultados escrito en", out)
PY
) 2>&1 | grep -E "CIDs reales|Reporte_Resultados|FAIL|PASS|ERROR|Traceback|Error" || true
  local dir; dir=$(ultimo_reporte_de "E2")
  [ -n "$dir" ] && mostrar_reporte "$dir"
}

run_all() {
  paso "Corrida completa: E1 -> E2 -> E3"
  run_e1; pausa
  run_e2 "${1:-10}"; pausa
  run_e3 "${2:-10}" "${3:-10}"
}

# ---------------------------------------------------------------------------
# Pruebas negativas de manipulacion on-chain
# ---------------------------------------------------------------------------
run_manip() {
  paso "Pruebas negativas de manipulacion on-chain (deben revertir)"
  asegurar_entorno || return 1
  cargar_env
  info "intentos: reanclar, emitir no autorizado, comprar oferta vendida..."
  ( cd "$RUNNER_DIR" && "$VENV_PY" - <<'PY'
from pathlib import Path
from runner_blockchain.chain.deployment import load_deployment
from runner_blockchain.chain.chain_client import build_chain_client
from runner_blockchain.experimentos import manipulaciones
from runner_blockchain.reporte import reporte_desde_deployment, escribir_reporte
dep=load_deployment(Path("../../deployment.json"))
chain=build_chain_client(dep.rpc_url, contratos=dict(dep.contratos))
res=manipulaciones.ejecutar(chain)
rep=reporte_desde_deployment("RUN-MANIP",[res],dep,params={"seleccion":"manip"})
out=escribir_reporte(rep, Path("../reports-blockchain"))
print("Reporte_Resultados escrito en", out)
PY
) 2>&1 | grep -E "Reporte_Resultados|PASS|FAIL|Error|Traceback" || true
  local dir; dir=$(ultimo_reporte_de "MANIP")
  [ -n "$dir" ] && mostrar_reporte "$dir"
}

# ---------------------------------------------------------------------------
# E3 control (mercado SIN escrow: demuestra doble venta)
# ---------------------------------------------------------------------------
run_e3_control() {
  paso "E3 control — mercado SIN escrow (demuestra la doble venta)"
  cargar_env
  info "disparando 10 compras concurrentes sobre un mercado sin la guarda del escrow..."
  ( cd "$RUNNER_DIR" && "$VENV_PY" - <<'PY'
from pathlib import Path
from runner_blockchain.experimentos import e3_control
from runner_blockchain.reporte import construir_reporte, escribir_reporte
res=e3_control.ejecutar_control("RUN-E3-CONTROL", compras=10)
rep=construir_reporte("RUN-E3-CONTROL",[res])
out=escribir_reporte(rep, Path("../reports-blockchain"))
print("Reporte_Resultados escrito en", out)
PY
) 2>&1 | grep -E "Reporte_Resultados|PASS|FAIL|Error|Traceback" || true
  local dir; dir=$(ultimo_reporte_de "E3-CONTROL")
  [ -n "$dir" ] && mostrar_reporte "$dir"
}

# ---------------------------------------------------------------------------
# Gas -> costo y decision de arquitectura
# ---------------------------------------------------------------------------
run_costos() {
  paso "Gas -> costo y decision de arquitectura"
  local gwei="${1:-20}" ethusd="${2:-3000}"
  info "supuestos: gas=$gwei gwei, ETH=\$$ethusd ; usando gas real del ultimo reporte E3..."
  ( cd "$RUNNER_DIR" && GWEI="$gwei" ETHUSD="$ethusd" "$VENV_PY" - <<'PY'
import os, json, glob
from runner_blockchain.experimentos import costos
# Toma el gas por operacion del reporte E3 mas reciente, si existe.
gas={"emitir":248388,"publicar":248000,"comprar":277526,"anclar":70000}
reps=sorted(glob.glob("../reports-blockchain/*RUN-E3*/report.json"))
if reps:
    d=json.load(open(reps[-1]))
    for e in d.get("experiments",[]):
        for ev in d.get("evidenciaOnChain",[]):
            pass
sup=costos.SupuestosCosto(gas_price_gwei=float(os.environ["GWEI"]), eth_usd=float(os.environ["ETHUSD"]))
r=costos.analizar(gas, sup)
print("  costo por kWh tokenizado: $%.6f" % r["costoPorKwhUsd"])
print("  costo por operacion:")
for op,v in r["costoPorOperacion"].items():
    print(f"    {op:10s} gas {v['gas']:>8}  ~ ${v['usd']:.6f}")
print("  emision por lotes (ahorro):")
for x in r["decisiones"]["emisionPorLotes"]:
    print(f"    lote {x['lote']:>4}: ahorro {x['ahorroPct']}% (${x['ahorroUsd']})")
print("  anclaje por cierre mensual (ahorro):")
for x in r["decisiones"]["anclajePorCierreMensual"]:
    print(f"    {x['comprasMes']:>5} compras/mes: ahorro {x['ahorroPct']}% (${x['ahorroUsd']})")
print()
print("  RECOMENDACION:")
import textwrap
print(textwrap.fill(r["recomendacion"], width=76, initial_indent="    ", subsequent_indent="    "))
PY
) 2>&1 || true
}

# ---------------------------------------------------------------------------
# Latencia real en Sepolia (requiere credenciales en .env)
# ---------------------------------------------------------------------------
run_sepolia() {
  paso "Latencia real en Sepolia (acuse <=2s / inclusion <=60s)"
  cargar_env
  if [ -z "${SEPOLIA_RPC_URL:-}" ] || [ -z "${PLATAFORMA_PRIVATE_KEY:-}" ]; then
    err "faltan credenciales de Sepolia."
    info "define en .env (fuera del repo): SEPOLIA_RPC_URL y PLATAFORMA_PRIVATE_KEY (cuenta con ETH de faucet)."
    info "y un deployment-sepolia.json con las direcciones desplegadas en Sepolia."
    warn "esta corrida gasta gas REAL de testnet; NO se ejecuta sin credenciales."
    return 1
  fi
  local depfile="${SEPOLIA_DEPLOYMENT:-$ROOT/deployment-sepolia.json}"
  [ -f "$depfile" ] || { err "no existe $depfile (despliega en Sepolia primero)"; return 1; }
  info "corriendo 20 emisiones + 10 compras en Sepolia (esto puede tardar varios minutos)..."
  ( cd "$RUNNER_DIR" && SEPOLIA_DEP="$depfile" "$VENV_PY" - <<'PY'
import os
from pathlib import Path
from runner_blockchain.chain.deployment import load_deployment
from runner_blockchain.chain.chain_client import build_chain_client
from runner_blockchain.experimentos import latencia_sepolia
from runner_blockchain.reporte import reporte_desde_deployment, escribir_reporte
dep=load_deployment(Path(os.environ["SEPOLIA_DEP"]))
chain=build_chain_client(os.environ.get("SEPOLIA_RPC_URL") or dep.rpc_url, contratos=dict(dep.contratos))
res=latencia_sepolia.ejecutar(chain, emisiones=20, compras=10)
rep=reporte_desde_deployment("RUN-SEPOLIA",[res],dep,params={"seleccion":"sepolia"})
out=escribir_reporte(rep, Path("../reports-blockchain"))
print("Reporte_Resultados escrito en", out)
PY
) 2>&1 | grep -E "Reporte_Resultados|PASS|FAIL|Error|Traceback" || true
  local dir; dir=$(ultimo_reporte_de "SEPOLIA")
  [ -n "$dir" ] && mostrar_reporte "$dir"
}

# ---------------------------------------------------------------------------
# Dashboard web en vivo
# ---------------------------------------------------------------------------
dashboard() {
  paso "Dashboard web en vivo (progreso + resultados)"
  asegurar_entorno || return 1
  cargar_env
  local port="${1:-8800}"
  info "sirviendo en http://127.0.0.1:$port  (Ctrl-C para detener)"
  info "abre esa URL en el navegador; lanza E1/E2/E3 desde la pagina."
  ( cd "$RUNNER_DIR" && VOLTERA_DASH_PORT="$port" "$VENV_PY" -m runner_blockchain.dashboard )
}

# ---------------------------------------------------------------------------
# Logs de Anvil en vivo (abre una terminal nueva con tail -f)
# ---------------------------------------------------------------------------
ver_logs_anvil() {
  paso "Logs de Anvil en vivo (nueva terminal)"
  if [ ! -f "$ANVIL_LOG" ]; then
    warn "no hay log de Anvil en $ANVIL_LOG"
    if anvil_vivo; then
      warn "Anvil parece haberse arrancado por fuera del script (sin log a archivo)."
      info "para tener logs a archivo, detenlo y arrancalo con la opcion 1 (o './experimentos.sh up')."
    else
      info "arranca Anvil primero (opcion 1 o './experimentos.sh up')."
    fi
    return 1
  fi

  local uname_s; uname_s="$(uname -s)"

  if [ "$uname_s" = "Darwin" ]; then
    # macOS: generamos un .command ejecutable y lo abrimos con Terminal.app via `open`.
    # Este metodo SIEMPRE abre una ventana nueva visible y al frente (mas fiable que
    # `do script`, que puede reusar una pestana enterrada cuando se llama desde otra app
    # como la terminal integrada de Kiro, TERM_PROGRAM=kiro).
    local cmdfile="/tmp/voltera-anvil-logs.command"
    cat > "$cmdfile" <<CMD
#!/bin/bash
printf '\033[36m== Logs de Anvil en vivo — Voltera ==\033[0m\n'
printf 'archivo: %s\n' '$ANVIL_LOG'
printf '\033[2m(cierra esta ventana para dejar de seguir los logs)\033[0m\n\n'
exec tail -n 200 -f '$ANVIL_LOG'
CMD
    chmod +x "$cmdfile"
    if open -a Terminal "$cmdfile" 2>/dev/null; then
      # Traer Terminal.app al frente de forma explicita.
      command -v osascript >/dev/null 2>&1 && \
        osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1
      ok "abri una ventana nueva de Terminal siguiendo $ANVIL_LOG"
      info "si no la ves, revisa detras de esta ventana o en el Dock (icono Terminal)."
    else
      warn "no pude abrir Terminal.app automaticamente."
      info "abre otra terminal y ejecuta:"
      printf '    %s\n' "${C_BOLD}tail -f $ANVIL_LOG${C_RESET}"
    fi
  elif command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal -- bash -lc "tail -n 200 -f '$ANVIL_LOG'; exec bash" >/dev/null 2>&1 &
    ok "abri una terminal nueva siguiendo $ANVIL_LOG"
  elif command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -e bash -lc "tail -n 200 -f '$ANVIL_LOG'; exec bash" >/dev/null 2>&1 &
    ok "abri una terminal nueva siguiendo $ANVIL_LOG"
  else
    warn "no pude detectar un emulador de terminal para abrir una ventana nueva."
    info "sigue los logs manualmente en otra terminal con:"
    printf '    %s\n' "${C_BOLD}tail -f $ANVIL_LOG${C_RESET}"
  fi
}

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
menu() {
  while true; do
    banner
    estado_breve
    linea
    printf '%s\n' "  ${C_BOLD}1${C_RESET})  Arrancar Anvil (Cadena_Local)"
    printf '%s\n' "  ${C_BOLD}2${C_RESET})  Desplegar contratos"
    printf '%s\n' "  ${C_BOLD}3${C_RESET})  E1 — Integridad del Oracle"
    printf '%s\n' "  ${C_BOLD}4${C_RESET})  E2 — Integridad del certificado  ${C_DIM}(Pinata real si hay .env)${C_RESET}"
    printf '%s\n' "  ${C_BOLD}5${C_RESET})  E3 — Tokenizacion sin doble venta"
    printf '%s\n' "  ${C_BOLD}6${C_RESET})  Correr TODOS (E1, E2, E3)"
    printf '%s\n' "  ${C_BOLD}7${C_RESET})  Ver ultimo reporte (elige experimento)"
    printf '%s\n' "  ${C_BOLD}8${C_RESET})  Detener Anvil y limpiar microservicios"
    printf '%s\n' "  ${C_BOLD}9${C_RESET})  Dashboard web en vivo"
    printf '%s\n' "  ${C_BOLD}10${C_RESET}) Ver logs de Anvil en vivo (nueva terminal)"
    printf '%s\n' "  ${C_BOLD}11${C_RESET}) Pruebas negativas de manipulacion on-chain"
    printf '%s\n' "  ${C_BOLD}12${C_RESET}) E3 control (mercado SIN escrow: doble venta)"
    printf '%s\n' "  ${C_BOLD}13${C_RESET}) Gas -> costo y decision de arquitectura"
    printf '%s\n' "  ${C_BOLD}14${C_RESET}) Latencia real en Sepolia (requiere .env)"
    printf '%s\n' "  ${C_BOLD}0${C_RESET})  Salir"
    linea
    printf '%s' "  selecciona una opcion: "
    read -r op
    echo
    case "$op" in
      1) arrancar_anvil; pausa ;;
      2) desplegar; pausa ;;
      3) run_e1; pausa ;;
      4) printf '  cuantos alterados? [10]: '; read -r n; run_e2 "${n:-10}"; pausa ;;
      5) printf '  cuantas ofertas? [10]: '; read -r o; printf '  cuantas compras/oferta? [10]: '; read -r b
         run_e3 "${o:-10}" "${b:-10}"; pausa ;;
      6) run_all; pausa ;;
      7) printf '  experimento (E1/E2/E3): '; read -r x
         d=$(ultimo_reporte_de "$(echo "$x" | tr '[:lower:]' '[:upper:]')"); [ -z "$d" ] && d=$(ultimo_reporte_de "$(echo "$x" | tr '[:upper:]' '[:lower:]')")
         [ -n "$d" ] && mostrar_reporte "$d" || err "no hay reporte para $x"; pausa ;;
      8) parar_anvil; limpiar_servicios; pausa ;;
      9) printf '  puerto [8800]: '; read -r pt; dashboard "${pt:-8800}" ;;
      10) ver_logs_anvil; pausa ;;
      11) run_manip; pausa ;;
      12) run_e3_control; pausa ;;
      13) printf '  gas (gwei) [20]: '; read -r g; printf '  ETH (USD) [3000]: '; read -r e; run_costos "${g:-20}" "${e:-3000}"; pausa ;;
      14) run_sepolia; pausa ;;
      0) parar_anvil; limpiar_servicios; ok "hasta luego"; exit 0 ;;
      *) warn "opcion no reconocida" ; sleep 1 ;;
    esac
  done
}

# ---------------------------------------------------------------------------
# Entrada: menu interactivo o subcomando directo
# ---------------------------------------------------------------------------
cargar_env
if ! verificar_requisitos; then
  err "faltan requisitos; revisa Foundry y el venv de runner-blockchain."
  exit 1
fi

case "${1:-menu}" in
  menu|"")   menu ;;
  up|anvil)  arrancar_anvil ;;
  deploy)    desplegar ;;
  e1)        run_e1 ;;
  e2)        run_e2 "${2:-10}" ;;
  e3)        run_e3 "${2:-10}" "${3:-10}" ;;
  all)       run_all "${2:-10}" "${3:-10}" "${4:-10}" ;;
  down|stop) parar_anvil; limpiar_servicios ;;
  dashboard|dash) dashboard "${2:-8800}" ;;
  logs|anvil-logs) ver_logs_anvil ;;
  manip) run_manip ;;
  e3-control|control) run_e3_control ;;
  costos) run_costos "${2:-20}" "${3:-3000}" ;;
  sepolia) run_sepolia ;;
  status)    banner; estado_breve ;;
  *) echo "uso: $0 [menu|up|deploy|e1|e2 [N]|e3 [ofertas] [compras]|all|manip|e3-control|costos [gwei] [ethusd]|sepolia|dashboard [puerto]|logs|down|status]"; exit 1 ;;
esac
