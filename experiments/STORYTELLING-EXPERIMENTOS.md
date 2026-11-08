# Voltera · Validación experimental Blockchain — Guion de presentación

**Universidad de los Andes**
**Grupo:** Julian Builes · Mario Montero · Carlos Garavito · Juan Puentes

> Documento guía para presentar los tres experimentos (E1, E2, E3) que validan,
> contra una cadena **local** (Anvil), las garantías centrales de la arquitectura
> blockchain de Voltera. Incluye la narrativa de cada experimento, cómo leer los
> resultados y qué significa cada veredicto.

---

## 1. El problema que estamos validando

Voltera es un mercado P2P de energía donde los usuarios **tokenizan** los kWh que
generan y los **venden** a otros. Tres preguntas deciden si la arquitectura es
confiable, y cada experimento responde una:

| Experimento | Pregunta que responde | Garantía que demuestra |
|---|---|---|
| **E1 — Integridad del Oracle** | ¿Puede entrar energía "falsa" al sistema? | Ninguna lectura inválida llega a emitir tokens |
| **E2 — Integridad del certificado** | ¿Se puede alterar un certificado sin que nadie lo note? | Toda alteración se detecta contra la huella anclada on-chain |
| **E3 — Tokenización sin doble venta** | ¿Puede venderse dos veces la misma energía? | El escrow garantiza exactamente una venta por oferta y conserva los kWh |

La idea de fondo: **lo que importa (la verdad del sistema) vive on-chain y es
inmutable**; lo accesorio (APIs de medidor, clima) puede ser simulado. Cada
experimento ejercita comportamiento **real** y recoge **evidencia on-chain**
(eventos con su `transactionHash`, `blockNumber` y gas) para respaldar el veredicto.

---

## 2. Cómo está montado el experimento (el "set")

```
  Runner (orquesta)
      │
      ├─ arranca Anvil (cadena local, chain-id 11155111)
      ├─ despliega los contratos EnergyToken + MarketEscrow  → deployment.json
      ├─ levanta 5 microservicios reales (ms_oraculo, ms_energia,
      │                                   ms_venta, ms_compra, ms_certificado)
      ├─ inyecta los casos de cada experimento
      ├─ el Lector_Eventos recoge la evidencia on-chain
      └─ escribe el Reporte_Resultados (report.json + report.md) con veredicto PASS/FAIL
```

**Frontera on-chain / off-chain (lo decimos explícitamente en la presentación):**
- **On-chain (real, inmutable):** emisión de tokens (`Emitido`), atomicidad de la
  venta (`Compra`), anclaje de la huella del certificado (`Anclado`).
- **Off-chain (real en lo medido):** la validación del oráculo, la verificación del
  certificado por contenido, la orquestación. Las APIs de medidor/clima son stub.

**Mensaje clave:** no simulamos la blockchain; corremos una cadena real (Anvil) y
los contratos reales de Voltera, solo que en local. La evidencia es reproducible.

---

## 3. E1 — Integridad del Oracle

### La historia
Antes de que se emita un solo token, una lectura de medidor tiene que pasar por el
**oráculo** (`ms_oraculo`). El oráculo es el "portero": decide qué lecturas son
legítimas. Si el portero falla, entra energía falsa al sistema y todo lo demás
pierde sentido. E1 pone a prueba al portero con **400 lecturas**: 200 válidas y 200
inválidas de tres tipos:
- **valor alterado** — la lectura no cuadra con la referencia esperada del medidor,
- **medidor desconocido** — el medidor no está en el padrón,
- **lectura duplicada** — ya se había registrado esa lectura.

### Qué hace el experimento
1. Genera 400 casos con **semilla fija** (reproducible).
2. Inyecta cada lectura a `ms_oraculo`.
3. Las válidas aceptadas disparan el flujo completo: `GeneracionValidada` →
   `ms_energia` → `EnergyToken.emitir` → evento **`Emitido`** on-chain.
4. Las inválidas deben rechazarse **sin** emitir nada.
5. El Lector_Eventos confirma cuántos `Emitido` hubo y de qué lecturas vinieron.

### Cómo leer los resultados
| Criterio | Qué significa | Umbral |
|---|---|---|
| **R2.5** Tasa de rechazo | Todas las inválidas fueron rechazadas, con la categoría correcta | 100% |
| **R2.6** Emisiones por inválidas | Ninguna lectura inválida logró emitir tokens | 0 eventos `Emitido` |
| **R2.8** Latencia p95 | Rapidez del flujo lectura → emisión | ≤ 10 s |

**Cómo explicarlo en vivo:** "De 200 lecturas inválidas, **cero** llegaron a crear
tokens. Las 200 válidas sí se emitieron, cada una con su transacción on-chain. Eso
es exactamente lo que queremos: el portero no deja pasar basura, y lo legítimo fluye
rápido (p95 de milisegundos)."

**Veredicto:** PASS solo si rechazo = 100% **y** emisiones por inválidas = 0 **y**
p95 ≤ 10 s. Un FAIL aquí significaría que energía no verificada pudo tokenizarse — un
fallo de seguridad grave.

---

## 4. E2 — Integridad del certificado off-chain

### La historia
Cada compra genera un **certificado PDF**. El PDF es muy pesado para guardarlo en la
cadena, así que se guarda fuera (en IPFS/Pinata) y on-chain solo se ancla su **huella
de contenido (CID)** — como una huella digital. La promesa es: si alguien altera el
PDF después, la huella ya no coincidirá y lo detectamos. E2 pone a prueba esa promesa.

### Qué hace el experimento
1. Genera certificados PDF íntegros y los **sube a Pinata (IPFS real)**, obteniendo
   su CID, que se **ancla on-chain** (`MarketEscrow.anclar` → evento `Anclado`).
2. Produce **50 versiones alteradas** en tres formas (con al menos una de cada una):
   - **byte** — se cambia un solo byte,
   - **metadatos** — se editan los metadatos del PDF,
   - **reemplazo** — se sustituye el archivo completo.
3. Verifica cada caso: recalcula la huella del contenido y la compara con el CID
   anclado → veredicto **ÍNTEGRO / ALTERADO / ERROR**.

### Cómo leer los resultados
| Criterio | Qué significa | Umbral |
|---|---|---|
| **R3.1** Dataset | Se generaron 50 alterados, con ≥1 por forma | 50 (≥1/forma) |
| **R3.6** Tasa de detección | Todas las alteraciones se detectaron como ALTERADO | 100% |
| **R3.8** Falsos positivos | Ningún certificado íntegro se marcó como ALTERADO | 0 |
| **R3.10** Latencia p95 | Rapidez de la verificación | ≤ 3 s |

**Cómo explicarlo en vivo:** "Subimos los certificados reales a IPFS vía Pinata (no
simulado). Luego los alteramos de tres formas distintas y el sistema detectó el
**100%** de las alteraciones, sin ningún falso positivo. La huella anclada en la
cadena es la fuente de verdad: cualquier cambio en el PDF la delata."

**Matiz técnico honesto (por si preguntan):** IPFS/Pinata es direccionable por
contenido — el CID *es* el hash del contenido —, así que una huella nunca puede
"servir" contenido distinto. Por eso la detección se prueba comparando el contenido
candidato (posiblemente alterado) contra el CID anclado. La integración con Pinata es
real en la subida/anclaje; el sistema tiene además un **fallback local** con el mismo
algoritmo de CID por si no hay credenciales o internet.

**Veredicto:** PASS solo si detección = 100% **y** falsos positivos = 0 **y** p95 ≤ 3 s.

---

## 5. E3 — Tokenización sin doble venta

### La historia
El riesgo clásico de un mercado digital: vender **dos veces** lo mismo. Si 100
compradores van por la misma oferta a la vez, ¿qué pasa? La respuesta correcta es:
**uno gana, los otros 99 fallan limpiamente**, y la energía no se duplica. E3 provoca
ese choque a propósito para demostrar que el **escrow** (el contrato `MarketEscrow`)
lo resuelve de forma atómica.

### Qué hace el experimento
1. Por cada oferta: emite los kWh al vendedor (`Emitido`) y publica **1 oferta Activa**.
2. Lanza **N compras concurrentes** sobre esa misma oferta (en la demo usamos 10 o
   100). La cadena las ordena: la primera gana, el resto revierte con
   `OfertaNoDisponible`.
3. Repite sobre **10 ofertas distintas**.
4. El Lector_Eventos cuenta las ventas reales (`Compra`) y suma los kWh.

### Cómo leer los resultados
| Criterio | Qué significa | Umbral |
|---|---|---|
| **R4.1** Publicación | Se publicaron todas las ofertas y se dispararon las compras | todas |
| **R4.4** Una venta por oferta | Exactamente 1 evento `Compra` por oferta | 1 / oferta |
| **R4.5** Dobles ventas | No hubo ninguna doble venta | 0 |
| **R4.6** Conservación de kWh | Los kWh tokenizados igualan a los validados | diff = 0 |
| **R4.7** Gas por operación | Se registró el gas real de cada transacción | registrado |

**Cómo explicarlo en vivo:** "Lanzamos 10 ofertas y sobre cada una disparamos muchas
compras **al mismo tiempo**. Resultado: exactamente **una** venta por oferta, **cero**
dobles ventas, y los kWh se conservan al 100%. El contrato garantiza la atomicidad —
no es que confiemos en el orden, es que es imposible vender dos veces."

**Veredicto:** PASS solo si 1 venta/oferta **y** 0 dobles ventas **y** conservación
de kWh exacta.

---

## 6. Cómo presentamos los resultados (lectura del reporte)

Cada corrida produce un `report.md` y un `report.json` con la misma estructura. En
pantalla (vía `experimentos.sh`) mostramos el **resumen coloreado**; en el documento
mostramos las tablas. Para cada experimento señalamos:

1. **El veredicto global** (PASS verde / FAIL rojo) — el titular.
2. **La tabla de criterios** — cada fila es una garantía, con *esperado* vs
   *observado*. Aquí se ve que no es una afirmación, es una medición.
3. **La evidencia on-chain** — lista de eventos reales (`Emitido` / `Compra` /
   `Anclado`) con su `transactionHash`, `blockNumber` y `gasUsed`. Esto es lo que
   convierte la demo en prueba: cualquiera puede reauditar esas transacciones.
4. **La frontera on/off-chain** — recordamos qué parte es inmutable (la garantía) y
   qué parte es orquestación.

**Si algo da FAIL:** el reporte marca exactamente qué métrica se incumplió, con su
valor observado y su umbral. Eso es una fortaleza, no una debilidad: el sistema no
"aprueba por defecto", mide y reporta la causa. (Durante el desarrollo, un FAIL de E3
nos destapó un caso real que corregimos: ofertas que intentaban publicar tokens no
emitidos; el experimento hizo su trabajo.)

---

## 7. Guion sugerido para la demo en vivo (≈5 min)

1. **Abrir el menú** (`./experimentos.sh`) — mostrar el banner del grupo y el estado:
   Anvil activo, contratos desplegados, Pinata con credencial.
2. **E1** (opción 3) — "primero, que no entre energía falsa". Señalar
   rechazo 100% y 0 emisiones por inválidas.
3. **E2** (opción 4) — "segundo, que no se pueda falsificar un certificado". Señalar
   detección 100%, 0 falsos positivos, y los CIDs reales de Pinata.
4. **E3** (opción 5) — "tercero, que no se venda dos veces". Señalar 1 venta por
   oferta, 0 dobles ventas, conservación de kWh.
5. **Cerrar** con la evidencia on-chain: "cada veredicto está respaldado por
   transacciones reales que quedan auditables en la cadena".

**Frase de cierre sugerida:** *"Las tres garantías que sostienen un mercado de energía
tokenizado — procedencia válida, integridad del certificado y unicidad de la venta —
no las afirmamos: las medimos, contra una cadena real, con evidencia reproducible."*

---

## 8. Apéndice — comandos

```bash
# Menú interactivo (modo maestría, con banner del grupo)
./experimentos.sh

# O por subcomando:
./experimentos.sh status        # estado de la cadena / contratos / Pinata
./experimentos.sh up            # arrancar Anvil
./experimentos.sh deploy        # desplegar contratos
./experimentos.sh e1            # E1 (200 inválidas + 200 válidas)
./experimentos.sh e2 50         # E2 con 50 alterados (Pinata real si hay .env)
./experimentos.sh e3 10 100     # E3: 10 ofertas × 100 compras concurrentes
./experimentos.sh all           # E1 → E2 → E3
./experimentos.sh down          # detener Anvil y limpiar microservicios
```

Los reportes quedan en `experiments/reports-blockchain/<fecha>-RUN-*/`
(`report.md` legible + `report.json` para auditoría).
