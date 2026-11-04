# Requirements Document

## Introduction

Esta feature cubre la validación experimental de la arquitectura blockchain del caso Voltera (mercado P2P de energía), correspondiente al punto 07 de la Entrega 4, que pesa el 30% de la nota. El objetivo de este MVP es probar lo esencial de blockchain: ejecutar los tres experimentos del cuaderno (E1 Integridad del Oracle, E2 Integridad del certificado off-chain, E3 Tokenización sin doble venta) contra una cadena **local** (Anvil), produciendo evidencia reproducible con criterios cuantitativos de PASS/FAIL para la Entrega 4.

Para que los experimentos corran de extremo a extremo, la feature incluye la creación de los microservicios que faltan y que tocan la cadena (`ms_oraculo`, `ms_energia`, `ms_venta`, `ms_compra`, `ms_certificado`) como servicios reales (procesos/servicios separados). El certificado PDF off-chain se guarda en Pinata (servicio de pinning de IPFS en la nube), que produce el CID por contenido y requiere credenciales y conexión a internet, con un almacén local de contenido direccionable como fallback cuando no haya internet o credenciales. Estos microservicios conservan la lógica real de la responsabilidad que valida cada experimento, pero se permite que sus integraciones externas accesorias (APIs de medidor, clima/temporada) usen stubs con respuestas predefinidas para construirlos más rápido. El principio es: lo que el experimento mide debe ser comportamiento real; lo accesorio puede ser stub. Por ejemplo, `ms_oraculo` puede simular con respuestas predefinidas la consulta a APIs externas, pero la decisión de aceptar o rechazar una lectura debe ser lógica real y determinista, porque eso es exactamente lo que valida E1.

Para recolectar evidencia, la feature incluye la lectura/consulta de los eventos on-chain (`Emitido`, `Compra`, `Anclado`) de los contratos desplegados durante la corrida, sin bus de eventos de dominio, sin checkpoints y sin deduplicación entre reinicios. La evidencia del reporte mantiene clara la frontera on-chain/off-chain e incluye los eventos on-chain observados (con hash de transacción y número de bloque), el gas por operación y las latencias medidas, sin OpenTelemetry, sin Grafana y sin spans distribuidos.

El entorno de ejecución actual tiene Node.js 24, npm, Python 3.14, git y Foundry (forge/anvil/cast 1.9.0) instalados. Este MVP **no** requiere Docker, kind ni kubectl: la Cadena_Local se ejecuta con el binario nativo de Anvil y los experimentos corren sobre los contratos y los microservicios locales. El alcance es funcional, no de carga: valida el comportamiento de la arquitectura, no su capacidad máxima.

## Glossary

- **Entorno_Experimental**: El conjunto de componentes locales (cadena, microservicios, lector de eventos, runner) que ejecuta y mide los experimentos en la máquina del usuario, sin AWS ni Docker.
- **Cadena_Local**: Nodo Ethereum de desarrollo Anvil, con chain-id 11155111 (Sepolia), accesible por JSON-RPC en `http://localhost:8545`, donde se despliegan los contratos `EnergyToken` y `MarketEscrow`.
- **EnergyToken**: Contrato ERC-1155 existente que tokeniza kWh por id (fuente + época), guarda el precio por kWh y emite el evento `Emitido`.
- **MarketEscrow**: Contrato existente que publica ofertas, ejecuta compras en escrow, cancela y ancla el CID del certificado; emite los eventos `OfertaPublicada`, `Compra`, `OfertaCancelada` y `Anclado`.
- **Runner_Experimentos**: Programa que orquesta cada experimento (inyección de casos, ejecución, recolección de métricas) y genera el reporte de resultados.
- **ms_oraculo**: Microservicio que valida cada lectura de medidor contra su fuente y descarta las lecturas inválidas antes de que originen una emisión de tokens. Puede usar datos externos simulados/stub (medidor, clima/temporada), pero su lógica de aceptación/rechazo es real y determinista.
- **ms_energia**: Microservicio que, a partir de una generación validada, emite tokens llamando a `EnergyToken.emitir`.
- **ms_venta**: Microservicio que publica y gestiona ofertas de energía tokenizada llamando a `MarketEscrow.publicar` y `MarketEscrow.cancelar`.
- **ms_compra**: Microservicio que ejecuta la compra de una oferta llamando a `MarketEscrow.comprar`.
- **ms_certificado**: Microservicio que genera el certificado PDF de una compra, lo guarda en Pinata (IPFS) obteniendo el CID, lo ancla on-chain mediante `MarketEscrow.anclar` y verifica la integridad recuperando el contenido por su CID desde Pinata/IPFS; usa un almacén local de contenido direccionable equivalente solo como fallback cuando no haya internet o credenciales de Pinata.
- **Pinata**: Servicio de pinning de IPFS en la nube (https://app.pinata.cloud/) usado por ms_certificado para guardar y recuperar el certificado PDF off-chain; produce un CID por contenido y requiere credenciales (API key o JWT) y acceso a internet.
- **Lector_Eventos**: Componente que lee/consulta los eventos on-chain (`Emitido`, `Compra`, `Anclado`) de los contratos desplegados durante la corrida y los asocia a la corrida como evidencia, sin publicarlos a un bus de dominio ni persistir checkpoints.
- **Lectura_Invalida**: Lectura de medidor que cae en una de tres categorías: valor alterado, medidor desconocido, o lectura duplicada.
- **Certificado_Alterado**: Archivo PDF modificado respecto del original en una de tres formas: cambio de un byte, cambio de metadatos, o reemplazo completo del archivo.
- **CID**: Content Identifier de IPFS que identifica un archivo por su contenido y se usa como huella de integridad del certificado PDF, producido al subir/fijar el contenido en Pinata (o, en fallback, en un almacén local de contenido direccionable equivalente).
- **Reporte_Resultados**: Documento o archivo estructurado que registra, por experimento, el veredicto PASS/FAIL, las métricas medidas, los parámetros de la corrida y la evidencia de eventos on-chain observados, gas por operación y latencias.
- **Latencia_p95**: Percentil 95 de la distribución de latencias medidas en un experimento.

## Requirements

### Requirement 1: Preparar la cadena local y desplegar los contratos

**User Story:** Como integrante del equipo, quiero levantar una cadena local y desplegar los contratos de forma reproducible, para poder ejecutar los experimentos sin depender de AWS ni de una red pública.

#### Acceptance Criteria

1. WHEN el usuario inicia el Entorno_Experimental, THE Entorno_Experimental SHALL arrancar la Cadena_Local Anvil con chain-id 11155111 escuchando en `http://localhost:8545` y confirmar que responde a una consulta JSON-RPC de estado en un plazo máximo de 30 segundos.
2. IF la Cadena_Local no responde a la consulta JSON-RPC de estado dentro de los 30 segundos, o el puerto 8545 ya está en uso, THEN THE Entorno_Experimental SHALL detener el arranque sin desplegar contratos y registrar un error que indique la causa (tiempo de espera agotado o puerto ocupado).
3. WHEN la Cadena_Local responde a la consulta JSON-RPC de estado, THE Entorno_Experimental SHALL desplegar los contratos EnergyToken y MarketEscrow y registrar en un archivo de despliegue legible por el Runner_Experimentos las direcciones de ambos contratos y el chain-id 11155111.
4. WHEN los contratos se despliegan, THE Entorno_Experimental SHALL ejecutar `EnergyToken.configurarMercado` con la dirección de MarketEscrow antes de habilitar los experimentos.
5. THE Entorno_Experimental SHALL ejecutar la Cadena_Local y el despliegue de contratos usando el binario nativo de Foundry (forge/anvil/cast 1.9.0) disponible en la máquina, sin requerir Docker.
6. IF el despliegue de un contrato falla, THEN THE Entorno_Experimental SHALL detener el arranque, dejar los experimentos sin habilitar y registrar un error que indique el nombre del contrato afectado y el motivo de la falla.
7. THE Entorno_Experimental SHALL documentar las herramientas requeridas por el MVP (Foundry forge/anvil/cast 1.9.0, Node.js 24, Python 3.14) e indicar explícitamente que Docker no es requerido para ejecutar este MVP.

### Requirement 2: Experimento E1 — Integridad del Oracle

**User Story:** Como arquitecto, quiero inyectar lecturas inválidas mezcladas con válidas y verificar que ninguna llega a emitir tokens, para validar que `ms_oraculo` protege la integridad de la tokenización.

#### Acceptance Criteria

1. WHEN se ejecuta el experimento E1, THE Runner_Experimentos SHALL inyectar exactamente 200 instancias de Lectura_Invalida que cubran las tres categorías (valor alterado, medidor desconocido, lectura duplicada) con al menos 50 instancias por categoría, mezcladas con exactamente 200 lecturas válidas.
2. WHERE ms_oraculo consulta datos externos (medidor, clima/temporada) mediante respuestas simuladas/stub predefinidas, THE ms_oraculo SHALL aplicar una lógica de aceptación o rechazo de la lectura que sea real y determinista, de modo que la misma entrada produzca siempre el mismo veredicto de aceptación o rechazo.
3. WHEN ms_oraculo recibe una Lectura_Invalida, THE ms_oraculo SHALL rechazar la Lectura_Invalida sin emitir tokens y registrar en el Reporte_Resultados el identificador y la categoría del motivo de rechazo.
4. WHEN ms_oraculo recibe una lectura válida, THE ms_oraculo SHALL aceptarla y el flujo SHALL completar la emisión produciendo los eventos `GeneracionValidada` y `Emitido`.
5. WHEN finaliza el experimento E1, THE Runner_Experimentos SHALL verificar que las 200 instancias de Lectura_Invalida fueron rechazadas, correspondiente a una tasa de rechazo del 100%.
6. WHEN finaliza el experimento E1, THE Runner_Experimentos SHALL verificar que se emitieron 0 tokens originados por lecturas inválidas, consultando los eventos `Emitido` de EnergyToken.
7. WHEN una lectura válida completa el flujo, THE Runner_Experimentos SHALL medir en milisegundos la latencia desde el evento `LecturaRegistrada` hasta el evento `GeneracionValidada`.
8. WHEN finaliza el experimento E1, THE Runner_Experimentos SHALL calcular la Latencia_p95 sobre las 200 lecturas válidas y verificar que es menor o igual a 10 segundos.
9. IF la Cadena_Local o ms_oraculo no responden durante 30 segundos mientras se ejecuta E1, THEN THE Runner_Experimentos SHALL abortar el experimento E1 y registrar el veredicto FAIL con el motivo de indisponibilidad.
10. WHEN finaliza el experimento E1, THE Runner_Experimentos SHALL asignar PASS únicamente si la tasa de rechazo es 100%, el conteo de tokens emitidos por lecturas inválidas es 0 y la Latencia_p95 es menor o igual a 10 segundos, y FAIL en cualquier otro caso, registrando en el Reporte_Resultados la tasa de rechazo, el conteo de tokens emitidos por lecturas inválidas y la Latencia_p95 medida.

### Requirement 3: Experimento E2 — Integridad del certificado off-chain

**User Story:** Como arquitecto, quiero alterar certificados PDF y verificarlos contra el CID anclado on-chain, para validar que el anclaje off-chain detecta toda manipulación sin falsos positivos.

#### Acceptance Criteria

1. WHEN se ejecuta el experimento E2, THE Runner_Experimentos SHALL producir exactamente 50 instancias de Certificado_Alterado distribuidas en las tres formas de alteración con al menos una instancia por forma (cambio de un byte, cambio de metadatos, reemplazo completo), partiendo de certificados PDF íntegros previamente anclados on-chain.
2. WHERE ms_certificado guarda y recupera el contenido del certificado, THE ms_certificado SHALL usar Pinata como servicio de pinning de IPFS para guardar y recuperar el contenido del certificado, obteniendo un CID determinado por el contenido.
3. IF no hay conexión a internet o credenciales de Pinata disponibles, THEN THE ms_certificado SHALL usar un almacén local de contenido direccionable equivalente que produzca un CID determinado por el contenido como fallback.
4. THE Entorno_Experimental SHALL proveer las credenciales de Pinata (API key o JWT) por configuración o variable de entorno, sin escribirlas en el repositorio ni en el Reporte_Resultados.
5. WHEN ms_certificado verifica un Certificado_Alterado contra el CID anclado on-chain, THE ms_certificado SHALL devolver un resultado de verificación con veredicto igual a ALTERADO.
6. WHEN finaliza el experimento E2, THE Runner_Experimentos SHALL verificar que las 50 instancias de Certificado_Alterado obtuvieron veredicto ALTERADO, correspondiente a una tasa de detección del 100%.
7. WHEN ms_certificado verifica un certificado PDF íntegro contra su CID anclado, THE ms_certificado SHALL devolver un resultado de verificación con veredicto igual a ÍNTEGRO.
8. WHEN finaliza el experimento E2, THE Runner_Experimentos SHALL verificar que el conteo de certificados íntegros con veredicto ALTERADO (falsos positivos) es 0.
9. WHEN ms_certificado verifica un certificado, THE Runner_Experimentos SHALL medir la latencia de la operación de verificación desde la recepción de la solicitud de verificación hasta la emisión del veredicto.
10. WHEN finaliza el experimento E2, THE Runner_Experimentos SHALL verificar que la Latencia_p95 de verificación es menor o igual a 3 segundos.
11. IF al verificar un certificado el CID anclado no existe para esa compra, THEN THE ms_certificado SHALL devolver un resultado de verificación con indicación de error de verificación, sin contabilizar el certificado como ÍNTEGRO ni como falso positivo.
12. IF al verificar un certificado el contenido no puede recuperarse desde Pinata/IPFS o Pinata no responde, THEN THE ms_certificado SHALL devolver un resultado de verificación con indicación de error de verificación, sin contabilizar el certificado como ÍNTEGRO ni como falso positivo.
13. WHEN finaliza el experimento E2, THE Runner_Experimentos SHALL registrar en el Reporte_Resultados el veredicto PASS o FAIL del experimento E2 junto con la tasa de detección, el conteo de falsos positivos y la Latencia_p95 de verificación.

### Requirement 4: Experimento E3 — Tokenización sin doble venta

**User Story:** Como arquitecto, quiero lanzar compras concurrentes sobre la misma oferta y repetir el escenario, para validar que el escrow garantiza exactamente una venta por oferta y conserva los kWh.

#### Acceptance Criteria

1. WHEN se ejecuta el experimento E3, THE Runner_Experimentos SHALL lanzar exactamente 100 compras concurrentes sobre una misma oferta en estado Activa y repetir el escenario exactamente 10 veces, cada repetición sobre una oferta distinta no utilizada en repeticiones previas.
2. WHEN concurren entre 2 y 100 compras sobre una misma oferta en estado Activa, THE MarketEscrow SHALL confirmar exactamente 1 compra, transicionar la oferta al estado Vendida y revertir las compras restantes de esa oferta.
3. IF una compra se ejecuta sobre una oferta que no está en estado Activa, THEN THE MarketEscrow SHALL revertir la operación sin modificar el estado de la oferta ni los balances de kWh, y producir un error indicando que la oferta no está disponible para compra.
4. WHEN finaliza cada repetición del experimento E3, THE Runner_Experimentos SHALL verificar que se registró exactamente 1 evento `Compra` por oferta y contabilizar como doble venta toda oferta con 2 o más eventos `Compra` registrados.
5. WHEN finaliza el experimento E3, THE Runner_Experimentos SHALL verificar que el conteo total de dobles ventas es igual a 0 a lo largo de las 10 repeticiones.
6. WHEN finaliza el experimento E3, THE Runner_Experimentos SHALL verificar que la cantidad total de kWh tokenizados es exactamente igual a la cantidad total de kWh validados, correspondiente a una conservación del 100% con diferencia absoluta igual a 0 kWh.
7. WHEN se ejecuta cada operación on-chain del experimento E3, THE Runner_Experimentos SHALL registrar el gas consumido por cada operación individual, expresado en unidades de gas.
8. WHEN finaliza el experimento E3, THE Runner_Experimentos SHALL asignar PASS únicamente si el conteo de ventas exitosas es igual a 1 por oferta en las 10 repeticiones, el conteo total de dobles ventas es igual a 0 y la conservación de kWh es del 100%, y FAIL en cualquier otro caso.
9. WHEN se registra el veredicto del experimento E3 en el Reporte_Resultados, THE Runner_Experimentos SHALL incluir el conteo de ventas exitosas por oferta, el conteo total de dobles ventas, el resultado de conservación de kWh en porcentaje y el gas consumido por operación.

### Requirement 5: Microservicios que tocan la cadena

**User Story:** Como desarrollador, quiero implementar los microservicios que faltan y que interactúan con la cadena, para que los experimentos corran de extremo a extremo respetando la frontera on-chain/off-chain.

#### Acceptance Criteria

1. WHEN ms_oraculo valida una lectura de medidor correcta, THE ms_oraculo SHALL publicar el evento `GeneracionValidada` con el identificador de la lectura validada.
2. WHEN ms_energia recibe una generación validada, THE ms_energia SHALL llamar a `EnergyToken.emitir` con la dirección del participante, el id, los kWh, el precio por kWh y el identificador de la lectura, exactamente una vez por identificador de lectura.
3. WHEN ms_venta publica una oferta, THE ms_venta SHALL llamar a `MarketEscrow.publicar` con la dirección del vendedor, el id del token y la cantidad de kWh.
4. WHEN ms_compra ejecuta una compra de una oferta en estado Activa, THE ms_compra SHALL llamar a `MarketEscrow.comprar` con el identificador de la oferta y la dirección del comprador.
5. WHEN ms_certificado procesa una compra confirmada, THE ms_certificado SHALL generar el certificado PDF y guardarlo en Pinata (IPFS) antes de anclar su CID mediante `MarketEscrow.anclar`.
6. WHEN ms_certificado completa el guardado del certificado PDF en Pinata (IPFS), THE ms_certificado SHALL anclar el CID obtenido de ese guardado llamando a `MarketEscrow.anclar` con el identificador de la compra confirmada y dicho CID.
7. THE ms_oraculo, ms_energia, ms_venta, ms_compra y ms_certificado SHALL ser los únicos microservicios que llaman a las funciones de escritura de EnergyToken y MarketEscrow, conservando la lógica real de la responsabilidad que valida su experimento.
8. WHERE un microservicio integra una API externa accesoria (medidor o clima/temporada) que no es el comportamiento medido por el experimento, THE microservicio SHALL poder sustituir esa integración por un stub con respuestas predefinidas, quedando Pinata excluido de esta sustitución por ser el almacenamiento off-chain real que valida E2, salvo el fallback a almacén local cuando no haya internet o credenciales.
9. WHEN un microservicio llama a una función de escritura de EnergyToken o MarketEscrow, THE microservicio SHALL firmar la transacción con la llave de la plataforma del modelo custodial y esperar la confirmación on-chain de la transacción por un máximo de 30 segundos.
10. IF una llamada a una función de escritura de un contrato se revierte o no se confirma dentro de los 30 segundos, THEN el microservicio emisor SHALL registrar el error de la transacción con el identificador de la operación afectada, no reintentar la operación de forma automática y dejar el estado off-chain de esa operación sin marcar como completada.
11. IF el guardado del certificado PDF en Pinata falla, THEN ms_certificado SHALL no llamar a `MarketEscrow.anclar` para esa compra y registrar el error indicando la compra afectada.

### Requirement 6: Recolección de evidencia de eventos on-chain

**User Story:** Como integrante del equipo, quiero leer los eventos que emiten los contratos durante la corrida, para recolectar evidencia de lo que ocurrió en la cadena y asociarla al reporte.

#### Acceptance Criteria

1. WHEN se ejecuta un experimento, THE Lector_Eventos SHALL leer los eventos `Emitido` de EnergyToken y `Compra` y `Anclado` de MarketEscrow en las direcciones registradas en el archivo de despliegue.
2. WHEN el Lector_Eventos lee un evento on-chain de la corrida, THE Lector_Eventos SHALL asociar ese evento al identificador de la corrida y registrar su hash de transacción y su número de bloque.
3. WHEN finaliza la corrida de un experimento, THE Lector_Eventos SHALL entregar al Runner_Experimentos la lista de eventos `Emitido`, `Compra` y `Anclado` observados durante la corrida con su hash de transacción y número de bloque.
4. IF la Cadena_Local no responde a la consulta de eventos durante 30 segundos, THEN THE Lector_Eventos SHALL registrar un error de lectura de eventos indicando la indisponibilidad de la Cadena_Local.

### Requirement 7: Reproducibilidad y reporte de evidencia

**User Story:** Como integrante del equipo, quiero que cada corrida produzca un reporte reproducible con parámetros, veredictos y evidencia on-chain, para entregar evidencia defendible del punto 07.

#### Acceptance Criteria

1. WHEN finaliza una corrida de los experimentos, THE Runner_Experimentos SHALL generar un Reporte_Resultados que incluya, por cada experimento ejecutado (E1, E2, E3), el veredicto PASS o FAIL y el listado de métricas medidas de ese experimento con su valor.
2. WHEN se genera el Reporte_Resultados, THE Runner_Experimentos SHALL registrar los parámetros de la corrida: un identificador único de corrida, la marca temporal de inicio y de fin, las cantidades de casos inyectados, el número de repeticiones, las direcciones de los contratos desplegados y las versiones de las herramientas utilizadas (Foundry/Anvil).
3. WHEN se genera el Reporte_Resultados, THE Runner_Experimentos SHALL incluir como evidencia los eventos on-chain observados (`Emitido`, `Compra`, `Anclado`) con su hash de transacción y número de bloque, el gas consumido por operación y las latencias medidas, manteniendo clara la frontera on-chain/off-chain.
4. WHEN se vuelve a ejecutar una corrida con los mismos parámetros registrados en el criterio 2, THE Runner_Experimentos SHALL producir el mismo veredicto PASS o FAIL para cada experimento que en la corrida previa.
5. IF un experimento no cumple su criterio cuantitativo, THEN THE Runner_Experimentos SHALL marcar ese experimento como FAIL en el Reporte_Resultados y registrar la métrica que incumplió el criterio junto con su valor medido y el umbral esperado.
6. WHEN el usuario solicita una corrida, THE Runner_Experimentos SHALL permitir ejecutar cada experimento (E1, E2, E3) de forma individual o los tres en una sola corrida, registrando en el Reporte_Resultados el veredicto PASS o FAIL por cada experimento ejecutado.
7. IF el usuario solicita ejecutar un experimento no reconocido (distinto de E1, E2 o E3), THEN THE Runner_Experimentos SHALL rechazar la corrida sin ejecutar ningún experimento y registrar un error que indique la selección inválida.
