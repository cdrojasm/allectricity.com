# Backlog — extracción documental con LLM y grafo de conocimiento en Neo4j

## Objetivo

Convertir los documentos y diseños de un proyecto en un grafo de puesta a tierra
consultable y trazable. El LLM propone entidades, relaciones y atributos a
partir de evidencia del documento; validadores deterministas comprueban
estructura, citas y tipos; los casos inciertos esperan revisión humana. El
grafo debe describir la instalación y su topología, la malla y sus conexiones,
el suelo, los escenarios de falla y los resultados calculados, además de
responder «qué sabemos, de qué documento/página sale, quién lo confirmó y qué
contradice esa afirmación».

El LLM **no es fuente de verdad ni autoriza parámetros de cálculo**. Cada dato
extraído se modela como una afirmación con procedencia y estado de revisión; no
se sobrescribe silenciosamente con otra extracción.

## Estado de partida

- La carga asíncrona valida MIME y antivirus y corre en Celery. Lee PDF (texto
  nativo, tablas con líneas y OCR de páginas rasterizadas), DOCX, CSV, XLSX e
  imágenes PNG/JPEG, con localizadores. Admite reintento, reconciliación y
  reprocesamiento.
- Un extractor ReAct, que navega el documento por segmentos con herramientas, y
  un consolidador opcional usan Langfuse y un proveedor LLM compatible con
  OpenAI. Sus salidas pasan validación determinista de contrato, cita, evidencia
  y localizador. Cada ejecución registra tokens, coste y límites.
- El pipeline persiste ejecuciones y afirmaciones idempotentes en Neo4j. La UI
  permite consultar el grafo, abrir fuentes y resolver hallazgos y preguntas con
  auditoría. Los datos que alimentan cálculos siguen requiriendo revisión.
- La brecha principal es la **calidad medible de la extracción**: no hay
  conjunto de evaluación, y el extractor usa por defecto un modelo pequeño
  (`gpt-4o-mini`) con toda la taxonomía en una sola pasada.

## Estrategia de extracción (decidida 2026-10-07)

La calidad se gana con medición, buena lectura del documento, tareas enfocadas y
verificación, no con arquitecturas de agentes más complejas. En orden de
prioridad:

1. **Evaluación primero.** Conjunto anotado, métricas por campo y bloqueo de
   regresiones. Ningún cambio de modelo, prompt o arquitectura entra sin medirse.
2. **Lectura de calidad.** Modelos multimodales sobre la imagen de la página
   para tablas, unifilares y planos, en lugar de depender solo de OCR → texto.
3. **Clasificación del documento y esquema por tipo.** Placa, informe de
   sondeo, memoria de cálculo, unifilar, etc. Cada tipo activa solo los
   perfiles de taxonomía que le corresponden.
4. **Descomposición por pregunta, no por fragmento.** Varias pasadas enfocadas
   (inventario de entidades, luego un perfil por pasada) sobre el **documento
   completo** con caché del prompt. El inventario fija los IDs que usan las
   pasadas siguientes. El ReAct por segmentos queda solo para documentos que no
   caben en el contexto.
5. **Verificación en capas.** Determinista (existente), verificador LLM de
   soporte de cita, coherencia de ingeniería y coherencia entre documentos.
6. **Confianza por acuerdo.** Doble extracción independiente de los parámetros
   que alimentan cálculos. Si coinciden, la confianza es alta; si discrepan, van
   directo a revisión. La confianza que declara el propio modelo no se usa para
   decidir.
7. **Revisión humana como ciclo de mejora.** Se prioriza por impacto, y cada
   corrección alimenta el conjunto de evaluación y los ejemplos del prompt.
8. **Identidad de entidades a nivel de proyecto**, sobre el grafo completo y
   con confirmación humana.

Los datos que ya entregan fuentes estructuradas (artefacto de diseño, ingesta de
mediciones, solver) **no se extraen ni se remodelan en el grafo**: se sincronizan
como referencias versionadas y sirven como contraste para la verificación.

## Alcance del grafo profesional de puesta a tierra

El esquema de Neo4j debe representar al menos estas áreas. La extracción del
LLM puede proponer hechos documentales; geometría y resultados de ingeniería
deben entrar también desde sus fuentes estructuradas (diseño, mediciones y
solver), no reconstruirse a partir del lenguaje natural cuando existe un dato
estructurado.

| Área | Nodos y relaciones a modelar | Requisitos de datos |
|---|---|---|
| Proyecto e instalación | `Project`, `Site`, `Substation`, zonas y equipos; `CONTAINS`, `LOCATED_AT` | Identificadores estables, ubicación, revisión y límites del proyecto. |
| Topología eléctrica | barras, transformadores, alimentadores, circuitos, interruptores, fuentes y puntos de conexión; `CONNECTED_TO`, `SUPPLIES`, `PROTECTED_BY` | Dirección/terminales cuando aplique, estado operativo y fuente. Una relación inferida requiere evidencia o confirmación. |
| Sistema de puesta a tierra | `GroundingSystem`, `GridConductor`, `RodElectrode`, bajantes, cercas, estructuras y conexiones; `PART_OF`, `JOINS`, `BONDED_TO`, `TERMINATES_AT` | Material/sección, profundidad y conexión según el documento. La geometría detallada vive en el artefacto de diseño; el grafo guarda la referencia a su versión. Distinguir elemento diseñado, instalado y observado. |
| Suelo | sondeo, lectura Wenner/Schlumberger, espaciamiento, resistividad aparente, capa/modelo de suelo; `MEASURED_AT`, `FITTED_AS`, `DERIVED_FROM` | Preservar lecturas originales y separarlas de parámetros ajustados; unidades, fecha, arreglo, método, incertidumbre y residuos. |
| Escenario de falla | falla, escenario, corriente, duración, división de corriente, decremento y supuestos; `APPLIES_TO`, `USES_INPUT` | Valores con dimensión/unidad, condición, procedencia y edición normativa. Separar `t_s` de duración térmica `t_c`. |
| Análisis y resultados | `DesignVersion`, `CalculationRun`, resultado resumido; `EVALUATES`, `PRODUCES`, `USES_SCENARIO` | Nodos de referencia sincronizados desde PostgreSQL (EG-20) con su ID de cálculo y trace; el detalle se consulta en la fuente. Un resultado derivado no se confunde con un dato medido ni con uno reportado por un documento. |
| Fuentes y gobierno | documentos, revisiones, afirmaciones, evidencias, actores y decisiones; `SUPPORTED_BY`, `CONTRADICTS`, `REVIEWED_BY`, `SUPERSEDES` | Conservar historial, estado y auditoría. Ningún valor contradictorio se sobrescribe en silencio. |

### Decisiones de producto y datos

1. **Taxonomía por perfiles:** núcleo común (instalación y jerarquía espacial,
   conectividad con bornes, tipo frente a instancia) más perfiles por dominio,
   empezando por puesta a tierra. Cada perfil declara sus atributos
   obligatorios por tipo, que alimentan el cierre de huecos. El especialista
   debe aprobar los subtipos y atributos. *Pendiente.*
2. **Relaciones permitidas:** dirección, cardinalidad y extremos por perfil. No
   se aceptan tipos de nodo o relación arbitrarios del LLM. *Vigente.*
3. **Geometría:** *decidido.* Vive en el artefacto de diseño con su sistema de
   coordenadas; Neo4j solo guarda referencias versionadas y propiedades
   consultables, nunca segmentos.
4. **Granularidad de evidencia:** página y fragmento en PDF, hoja/fila/celda en
   XLSX/CSV, página/región en OCR y visión, más offsets. *Vigente.*
5. **Identidad y duplicados:** se resuelven a nivel de proyecto con reglas, el
   LLM con evidencia y confirmación humana. Se conservan los nombres originales.
   *Vigente.*
6. **Revisión:** estados `proposed`, `needs_review`, `accepted`, `rejected` y
   `superseded`, priorizados por impacto en cálculos. *Vigente.*
7. **Resultados de cálculo:** *decidido.* Se quedan en PostgreSQL y en el
   trace; el grafo replica solo nodos resumidos con su ID, sincronizados por
   EG-20.

## Épicas y tareas

| ID | Prioridad | Estado | Tarea | Criterio de aceptación |
|---|---|---|---|---|
| EG-01 | P0 | ✅ | Contrato de extracción versionado | JSON Schema estricto para entidades, relaciones, atributos, evidencia, confianza explicada, incertidumbres y versión del esquema. Rechaza campos extra, tipos desconocidos, relaciones no permitidas y citas sin localizador. Incluye ejemplos válidos e inválidos. |
| EG-02 | P0 | ✅ | Modelo de afirmaciones y procedencia | Definir en Neo4j `ExtractionRun`, `Finding`/`Claim`, `Evidence`, y sus vínculos con `Document`, entidades y relaciones. Cada afirmación registra ejecución, agente/modelo, prompt y versión, timestamp, método, estado de revisión y evidencia. Decidir si los nodos de dominio existentes se conservan o migran. |
| EG-03 | P0 | ✅ | Extracción estructurada con LLM | Extender el extractor actual para emitir entidades, relaciones y atributos según EG-01, con evidencia exacta por cada dato. El LLM usa herramientas acotadas de lectura/búsqueda y nunca escribe directamente en Neo4j. No completa hechos ausentes. Hallazgos sin cita verificable se descartan o quedan en error explícito. |
| EG-04 | P0 | ✅ | Localizadores por formato | Mantener origen estructurado durante parseo: número de página PDF, nombre de hoja y fila/celda XLSX/CSV, y página/región OCR. Una cita debe poder llevar al usuario al pasaje original. No aplanar todo a texto sin metadatos. |
| EG-05 | P0 | ✅ | Validación determinista y límites de confianza | Validar esquema, existencia y unicidad de IDs, cita/localizador, rangos/unidades conocidos y compatibilidad de extremos de relaciones. Separar confianza del proveedor LLM de calidad de OCR. Parámetros que alimentan cálculos nunca quedan aceptados por score automático. |
| EG-06 | P0 | ✅ | Consolidador contra el grafo del proyecto | Contrastar candidatos con afirmaciones vigentes y previas, identificar duplicados, valores contradictorios y referencias sin resolver; producir decisión/revisión y preguntas enlazadas a IDs de hallazgo. Tratar el grafo existente como evidencia, no necesariamente como verdad aceptada. |
| EG-07 | P0 | ✅ | Persistencia idempotente en Neo4j | Usar claves estables por proyecto/documento/ejecución/hallazgo/evidencia y restricciones de unicidad. Reintentar una carga sin duplicar nodos o aristas; guardar nueva versión cuando cambien parser, prompt o modelo. Hacer atómica la persistencia de una ejecución y su resultado. |
| EG-08 | P0 | ✅ | Revisión humana de hallazgos | API y UI para listar preguntas, abrir la evidencia en el documento, aceptar/rechazar/corregir afirmaciones y registrar usuario, fecha y motivo. Correcciones guardan el valor revisado y no borran el texto propuesto ni su evidencia. |
| EG-09 | P1 | ✅ | Cobertura documental y OCR de PDF | DOCX, PDF con texto nativo y OCR por página implementados con localizadores. Las páginas sin texto se rasterizan con PDFium (escaneos y PDF vectoriales sin imagen embebida) antes del OCR; las tablas con líneas se extraen con pdfplumber por página/tabla/fila/celda sin duplicar el texto; la cobertura registra páginas fallidas, vacías, con tablas, calidad OCR por página y páginas de OCR dudoso. Tablas sin líneas y planos complejos quedan para EG-14. |
| EG-13 | P1 | ✅ | Observabilidad, coste y fallos | Cada ejecución registra modelo, versiones de prompt/esquema/parser, tokens por agente, coste estimado (`LLM_PRICE_*_USD_PER_MTOK`), duración, errores y conteos por estado; los logs solo llevan conteos. Límites `DOCUMENT_LLM_MAX_TOKENS_PER_FILE` y `DOCUMENT_LLM_MAX_TOKENS_PER_PROJECT`: al agotarse el del proyecto se extrae solo con reglas y queda registrado. Recuperación: reintentos automáticos, reconciliación periódica, reintento manual y `POST .../knowledge-graph/documents/{id}/reprocess`. |
| EG-12 | P0 | ⬜ | Evaluación de calidad del LLM | **Primer paso de la estrategia.** Conjunto versionado y revisado, empezando por `docs/documentos_prueba/`. Mide precisión y recobrado por tipo y atributo, exactitud de evidencia, relaciones, abstención y duplicados, además de coste y latencia por documento. Compara modelos y prompts, fija la línea base actual y bloquea la promoción si se degradan los umbrales acordados. |
| EG-24 | P0 | ⬜ | Correcciones de la taxonomía v1 | La unidad distingue los prefijos m y M (`mV` ≠ `MV`, `mΩ` ≠ `MΩ`). Se publica `TAXONOMY_VERSION` y se incluye en el ID de ejecución, para que cambiar la taxonomía cree ejecuciones nuevas al reprocesar. |
| EG-25 | P0 | ⬜ | Selección de modelo por paso | Configurar el modelo por paso (clasificación, inventario, pasadas, verificación) y elegirlo con EG-12. El modelo pequeño actual queda solo donde las métricas lo justifiquen. |
| EG-15 | P0 | ◐ | Taxonomía v2: núcleo y perfiles | Núcleo común (jerarquía espacial con los aspectos función/producto/ubicación, conectividad con bornes y fases, tipo frente a instancia) y perfil de puesta a tierra. El perfil cubre: esquema de conexión a tierra, aterrizamiento del neutro, cables de guarda y pantallas, estructuras metálicas, equipos a aterrizar con su ubicación respecto a la malla, elementos que transfieren potencial, mediciones de resistencia de malla y parámetros de tensiones tolerables y térmicos. Cada perfil declara atributos obligatorios por tipo. Requiere revisión del especialista antes de congelar; v1 está implementada. |
| EG-26 | P0 | ⬜ | Clasificación de documentos y esquema por tipo | Clasificar cada documento (y, si es mixto, sus secciones) en tipos acordados. Cada tipo activa perfiles y campos esperados. La clasificación se guarda en la ejecución y se evalúa con EG-12. |
| EG-27 | P0 | ⬜ | Pasadas enfocadas sobre el documento completo | Sustituye al ReAct por segmentos en documentos que caben en el contexto. Primero una pasada de inventario (entidades, jerarquía espacial y alias), que fija IDs; luego una pasada por perfil activo que referencia esos IDs; al final, una pasada de relaciones entre perfiles. Usa caché del prompt y el mismo contrato y validación. Reparte el límite de tokens del archivo entre pasadas, y el ID de ejecución incluye la versión del pipeline y de todos los prompts. Debe superar a la línea base de EG-12. |
| EG-28 | P1 | ⬜ | Cierre de huecos dirigido | Comparar las entidades extraídas con los atributos obligatorios de su perfil (EG-15) y lanzar búsquedas acotadas por hueco («profundidad de enterramiento de G1»). Máximo 2 vueltas o hasta agotar el presupuesto; si un dato no aparece, se registra como ausente y no se inventa. |
| EG-14 | P1 | ⬜ | Lectura multimodal de tablas, unifilares y planos | Enviar la imagen de la página a un modelo con visión cuando haya tablas sin líneas, unifilares o planos, conservando página y región. Las relaciones topológicas leídas de un dibujo siempre requieren revisión, y no se infiere una conexión eléctrica solo por proximidad visual. Se compara con OCR → texto en EG-12. |
| EG-29 | P1 | ⬜ | Verificador de soporte de cita | Un paso LLM independiente confirma que la cita sostiene exactamente el valor, la unidad, el sujeto y la relación propuestos. Lo que no está soportado pasa a `needs_review` con el motivo, y nunca se borra en silencio. |
| EG-30 | P1 | ⬜ | Doble extracción con acuerdo para parámetros de cálculo | Los atributos con `feeds_calculation` se extraen dos veces de forma independiente (otro modelo u otra formulación). El acuerdo, tras normalizar a SI, se registra como evidencia de confianza; el desacuerdo crea una pregunta con ambos valores y citas. La aceptación sigue siendo humana. |
| EG-21 | P1 | ⬜ | Verificación de coherencia de ingeniería | Diagnósticos explicables, sin reparar nada en silencio: dimensiones y rangos; `t_c ≥ t_s`; S_f entre 0 y 1; resistencia reportada compatible con área y resistividad (Sverak); corriente de falla coherente con la potencia y la impedancia del transformador; valores del documento frente a fuentes estructuradas sincronizadas (EG-20). Cada diagnóstico se adjunta a las afirmaciones afectadas. |
| EG-31 | P1 | ⬜ | Ciclo de mejora desde la revisión humana | Priorizar la cola de revisión por impacto (primero lo que alimenta cálculos, luego los conflictos). Las correcciones y rechazos, con su evidencia, se exportan como casos candidatos para EG-12 y como ejemplos para los prompts, tras curarlos. |
| EG-10 | P1 | ◐ | Identidad de entidades a nivel de proyecto | Hoy se detectan posibles alias y se pregunta. Falta resolver sobre el grafo completo del proyecto (reglas, LLM con evidencia y confirmación humana) y permitir **confirmar la fusión** conservando nombres originales y procedencia. Nunca se fusiona por similitud débil. |
| EG-20 | P1 | ⬜ | Sincronización con fuentes estructuradas | Eventos idempotentes desde artefactos de diseño, mediciones de suelo y cálculos hacia nodos de referencia versionados (`DesignVersion`, `SoilSurvey`/`SoilModel`, `FaultScenario`, `CalculationRun`) con su ID de origen, sin copiar geometrías ni resultados detallados. Estados: sincronizado, pendiente y fallido, con reintento. Habilita EG-21 y la regla de que un cálculo solo usa parámetros documentales aceptados. Absorbe lo útil de EG-16 a EG-19. |
| EG-11 | P1 | ◐ | API de lectura para revisión | Ya hay mapa, afirmaciones con evidencia, preguntas, ejecuciones y filtros, con autorización por proyecto. Falta una vista de conflictos y diagnósticos (EG-21), la cola priorizada (EG-31) y límites de tamaño en el mapa. |
| EG-23 | P1 | ◐ | Migración y reconstrucción Neo4j | Las restricciones e índices ya existen. Falta un procedimiento de reconstrucción del grafo por reprocesamiento cuando cambien la taxonomía o el pipeline (EG-24, EG-15), con la política sobre afirmaciones ya decididas, y una prueba de rendimiento con un proyecto representativo. |

### Descartadas (2026-10-07)

No contribuyen a la estrategia de extracción o se reemplazan por otra tarea:

| ID | Tarea | Motivo |
|---|---|---|
| EG-16 | Geometría de la malla como segmentos en Neo4j | La geometría ya tiene su fuente de verdad en el artefacto de diseño (decisión 3). Duplicarla en el grafo añade sincronización sin mejorar la extracción. La referencia versionada queda en EG-20. |
| EG-17 | Mediciones y modelo de suelo modelados en el grafo | Las lecturas y ajustes ya se ingieren y se guardan de forma estructurada. Solo se sincroniza su referencia (EG-20) para contrastar los valores de los documentos (EG-21). |
| EG-18 | Escenarios de falla como nodos versionados propios | Los datos documentales de falla ya son atributos con procedencia; el escenario usado en un cálculo llega por EG-20. |
| EG-19 | `CalculationRun` y resultados completos en Neo4j | Los cálculos son inmutables y trazables en PostgreSQL (decisión 7). El grafo solo necesita el nodo de referencia de EG-20. |
| EG-22 | Consultas de ingeniería (camino a tierra, comparar modelos y escenarios) | Es una funcionalidad de producto sobre datos del diseño, no de la extracción. Si se retoma, debe consultar las fuentes estructuradas. |
| — | Extracción jerárquica con sub-agentes por fragmento | Encadena errores y pierde el contexto entre secciones. La reemplazan las pasadas enfocadas sobre el documento completo (EG-27). Solo se reconsidera si EG-12 muestra que hace falta navegar colecciones que no caben en el contexto. |

**Leyenda:** ✅ completo; ◐ parcial; ⬜ pendiente. Las tareas pendientes están en orden
de prioridad. Estados actualizados el 2026-10-07; EG-24 a EG-31 se crearon con la
estrategia de extracción. Los códigos son estables y no se reutilizan.

## Implementación v1 (2026-10-05)

| Pieza | Ubicación |
|---|---|
| Taxonomía v1 (tipos, relaciones con extremos válidos, atributos con dimensión/rango y marca de entrada de cálculo) | `backend/src/domain/knowledge_graph/taxonomy.py` |
| Contrato de extracción 1.1 (JSON Schema estricto; 1.0 sigue aceptado) | `backend/src/domain/knowledge_graph/contract.py`; ejemplos en `tests/fixtures/extraction_contract/` |
| Afirmaciones, estados, decisiones humanas | `backend/src/domain/knowledge_graph/claims.py` |
| Validación contra la fuente | `backend/src/domain/knowledge_graph/validation.py` |
| Consolidación determinista (duplicados, conflictos, alias) | `backend/src/domain/knowledge_graph/consolidation.py` |
| Parseo con localizadores (PDF/OCR, CSV, XLSX, DOCX, imagen) | `backend/src/infrastructure/processing/document_sources.py` |
| Reglas y agentes LLM en el contrato | `processing/rule_extraction.py`, `processing/document_agents.py`, `prompts/langfuse/` |
| Orquestación del pipeline | `processing/knowledge_extraction.py` (invocado desde `spat.scan_file_upload`) |
| Neo4j: migraciones, escritura atómica, lecturas | `backend/src/infrastructure/persistence/knowledge_graph_store.py` |
| Revisión humana y API | `application/use_cases/knowledge_review.py`, `entrypoint/api/knowledge_graph_routes.py` (`/api/v1/projects/{id}/knowledge-graph/...`) |
| UI de visualización, revisión y depuración (mapa de entidades, afirmaciones, preguntas, ejecuciones con errores/rechazos/tokens y JSON crudo; `GET .../summary`) | `app/src/components/KnowledgeGraphWorkspace.jsx` (vista «Grafo de conocimiento» del proyecto) |

Decisiones tomadas (provisionales hasta revisión del especialista, EG-15):

- **Contrato 1.1:** cada hallazgo lleva su propia `evidence` (cita + localizador); la
  evidencia compartida de 1.0 sigue admitida. En pruebas con OpenAI, ningún modelo
  enlazaba bien la evidencia compartida a los atributos y la versión 1.1 eliminó esos
  rechazos. Un hallazgo mal formado se descarta solo, con código `schema`; el extractor
  recibe los errores de validación contra la fuente y puede corregir hasta 3 envíos.

- **Modelo:** `(Document)-[:HAS_RUN]->(ExtractionRun)-[:PRODUCED]->(Claim)-[:SUPPORTED_BY]->(Evidence)`.
  Una afirmación es de entidad, atributo o relación y apunta a `Entity` (`ABOUT`,
  `SOURCE`, `TARGET`). Los nodos heredados `ElectricalAsset`/`ElectricalParameter`
  se conservan en solo lectura; el pipeline ya no los escribe.
- **Los parámetros son atributos** de una entidad (`rated_voltage` de `T1`), no
  entidades sueltas; así un conflicto es «misma entidad, mismo atributo, otro valor».
- **Estados:** `proposed`, `needs_review`, `accepted`, `rejected`, `superseded`. Nada
  nace `accepted`. Todo lo propuesto por el LLM, todo parámetro de cálculo, toda
  relación y todo lo afectado por OCR dudoso nace `needs_review`; las reglas sin dudas,
  `proposed`.
- **Relaciones aceptadas** se materializan como arista tipada entre entidades
  (`(T1)-[:SUPPLIES {claim_id}]->(TD-2)`) solo tras una decisión humana, y se retiran
  si luego se rechazan.
- **Conflictos:** aceptar un valor que contradice otro ya aceptado devuelve 409 hasta que
  la persona indique explícitamente cuál reemplaza (`supersede_claim_ids`).
- **Identidad:** `entity_key` = proyecto + tipo + nombre normalizado (mayúsculas y
  espacios). `T-01` y `T1` no se fusionan: se marca posible alias y se pregunta.
- **Idempotencia:** `run_id` = hash de upload, contenido, versión de parser, reglas,
  contrato, prompts y modelo. Reintentar no duplica; cambiar prompt/modelo/parser crea
  una ejecución nueva que reemplaza solo las afirmaciones abiertas de la anterior.
- **Localizadores:** `segment` + página (PDF), página y región (OCR por línea), fila y
  celda (CSV), hoja/fila/celda (XLSX), párrafo o tabla/fila/celda (DOCX), además de
  offsets sobre el texto.

Pendiente dentro de las tareas parciales: fusión confirmada de alias (EG-10);
vista de conflictos y cola priorizada (EG-11); taxonomía v2 y revisión del
especialista (EG-15); reconstrucción y rendimiento (EG-23).

## Orden recomendado de entrega

Completado: fundación (EG-01, EG-02, EG-04), extracción fiable (EG-03, EG-05,
EG-06), operación (EG-07, EG-08, EG-09, EG-13).

1. **Medir:** EG-12 y EG-24. Línea base de la extracción actual con la
   taxonomía corregida.
2. **Palancas baratas:** EG-25 (modelo por paso) y EG-26 (clasificación).
   Medir cada una contra la línea base.
3. **Extracción enfocada:** EG-15 (taxonomía v2 con el especialista) y EG-27
   (pasadas sobre el documento completo), seguidas de EG-28.
4. **Verificación:** EG-29, EG-30 y EG-21, esta última con EG-20 como fuente
   de contraste.
5. **Lectura multimodal:** EG-14, cuando EG-12 muestre que las tablas y planos
   concentran errores.
6. **Ciclo y producto:** EG-31, EG-10, EG-11 y EG-23.

## Ejemplo de salida del extractor

Para el texto «El transformador T1, 13,8 kV, alimenta el tablero TD-2» el LLM
debería proponer esto (contrato 1.1, `tests/fixtures/extraction_contract/valid_inline_evidence_1_1.json`).
La tensión es un atributo de T1, no una entidad, y cada hallazgo lleva su propia
cita y localizador:

```json
{
  "schema_version": "1.1",
  "entities": [
    {"id": "transformer.T1", "type": "Transformer", "name": "T1",
     "confidence": {"level": "high", "reason": "Etiqueta explícita"},
     "evidence": [{"quote": "El transformador T1, 13,8 kV, alimenta el tablero TD-2",
                   "locator": {"page": 4}}]},
    {"id": "panel.TD-2", "type": "ElectricalPanel", "name": "TD-2",
     "confidence": {"level": "high", "reason": "Etiqueta explícita"},
     "evidence": [{"quote": "alimenta el tablero TD-2", "locator": {"page": 4}}]}
  ],
  "attributes": [
    {"id": "T1:rated_voltage", "subject_id": "transformer.T1", "name": "rated_voltage",
     "value": "13,8", "unit": "kV",
     "confidence": {"level": "high", "reason": "Valor junto al equipo"},
     "evidence": [{"quote": "El transformador T1, 13,8 kV", "locator": {"page": 4}}]}
  ],
  "relations": [
    {"id": "T1-supplies-TD-2", "type": "SUPPLIES", "source_id": "transformer.T1",
     "target_id": "panel.TD-2", "confidence": {"level": "medium", "reason": "«alimenta»"},
     "evidence": [{"quote": "El transformador T1, 13,8 kV, alimenta el tablero TD-2",
                   "locator": {"page": 4}}]}
  ],
  "uncertainties": []
}
```

El backend valida la cita y el esquema, enlaza la evidencia al documento y
guarda los hallazgos como propuestas en Neo4j. Si otro documento dice que T1
es de 13,2 kV, conserva ambas afirmaciones y evidencia, crea el conflicto y
lo envía a revisión. Solo una decisión humana cambia el estado de una
afirmación a `accepted`; el sistema nunca reemplaza el valor previo en silencio.

## Criterio de terminado del caso de uso

Subir un PDF escaneado o digital, un DOCX o una hoja de cálculo y obtener
hallazgos tipados con relaciones y referencia navegable a la fuente. Los
hallazgos se persisten en Neo4j de forma idempotente, los duplicados y
conflictos se ven y se resuelven desde la interfaz con auditoría, y después se
consulta el grafo por proyecto.

La calidad de la extracción se mide en EG-12 por tipo de documento, con
umbrales acordados que bloquean regresiones. Los parámetros que alimentan
cálculos llevan verificación de cita, acuerdo de doble extracción y diagnósticos
de coherencia de ingeniería, y siempre requieren aceptación humana explícita.
Los datos del diseño, las mediciones y el solver llegan al grafo como
referencias versionadas desde sus fuentes estructuradas, nunca reconstruidos
por el LLM. Las salidas del solver se registran como resultados derivados
inmutables.
