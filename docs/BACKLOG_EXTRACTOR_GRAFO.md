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

- La carga asíncrona valida MIME y antivirus, procesa PDF (incluido OCR por
  página), DOCX, CSV, XLSX e imágenes PNG/JPEG, y corre en Celery.
- El extractor ReAct y el consolidador opcionales usan Langfuse y un proveedor
  LLM compatible con OpenAI; sus salidas pasan validación determinista de
  contrato, cita, evidencia y localizador.
- El pipeline persiste ejecuciones y afirmaciones idempotentes en Neo4j. La UI
  permite consultar el grafo, abrir fuentes y resolver hallazgos/preguntas con
  auditoría; los datos que alimentan cálculos siguen requiriendo revisión.
- La brecha principal ya no es la fundación del grafo: falta sincronizar con
  artefactos/solver, completar el esquema de dominio de puesta a tierra y cerrar
  la cobertura de OCR/tablas PDF, evaluación de calidad y operación.
- El backlog general registra DOCX, idempotencia y presentación/resolución de
  preguntas como implementados parcialmente o disponibles. Sigue pendiente la
  confirmación humana de parámetros críticos; OCR/tablas de PDF y recuperación
  operativa conservan brechas.

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
| Sistema de puesta a tierra | `GroundingSystem`, `GridConductor`, segmentos, uniones, `RodElectrode`, electrodos, bajantes, cercas, estructuras y conexiones; `PART_OF`, `JOINS`, `BONDED_TO`, `TERMINATES_AT` | Geometría 3D o coordenadas locales, unidad, material/sección cuando exista, profundidad/elevación y conexión. Distinguir elemento diseñado, instalado y observado. |
| Suelo | sondeo, lectura Wenner/Schlumberger, espaciamiento, resistividad aparente, capa/modelo de suelo; `MEASURED_AT`, `FITTED_AS`, `DERIVED_FROM` | Preservar lecturas originales y separarlas de parámetros ajustados; unidades, fecha, arreglo, método, incertidumbre y residuos. |
| Escenario de falla | falla, escenario, corriente, duración, división de corriente, decremento y supuestos; `APPLIES_TO`, `USES_INPUT` | Valores con dimensión/unidad, condición, procedencia y edición normativa. Separar `t_s` de duración térmica `t_c`. |
| Análisis y resultados | `DesignVersion`, `CalculationRun`, resultado de resistencia/GPR/paso/contacto, puntos críticos; `EVALUATES`, `PRODUCES`, `USES_SCENARIO` | Enlazar a entradas exactas, geometría y versión de solver/protocolo, norma/edición, trace e incertidumbre. Resultado derivado no se confunde con dato medido. |
| Fuentes y gobierno | documentos, revisiones, afirmaciones, evidencias, actores y decisiones; `SUPPORTED_BY`, `CONTRADICTS`, `REVIEWED_BY`, `SUPERSEDES` | Conservar historial, estado y auditoría. Ningún valor contradictorio se sobrescribe en silencio. |

### Decisiones de producto y datos que deben cerrarse

1. **Taxonomía y perfiles:** aprobar subtipos y atributos obligatorios con un
   especialista en puesta a tierra. Distinguir objeto físico, dato medido,
   afirmación documental y salida calculada.
2. **Relaciones permitidas:** definir dirección, cardinalidad, compatibilidad de
   extremos y terminales para relaciones como `CONNECTED_TO`, `BONDED_TO`,
   `SUPPLIES`, `MEASURED_AT`, `FITTED_AS`, `EVALUATES` y `PRODUCES`. No aceptar
   tipos de nodo o relación arbitrarios del LLM.
3. **Geometría y coordenadas:** decidir sistema de coordenadas local/global,
   unidades, precisión, datum, profundidad, elevación, segmentos y estrategia
   para geometrías extensas (propiedades, nodos por segmento o referencia a
   artefacto). Evitar que Neo4j sea el único almacén de geometrías pesadas.
4. **Granularidad de evidencia:** página y fragmento en PDF, hoja/fila/celda en
   XLSX/CSV, página/región para OCR; offsets además del localizador legible.
5. **Identidad y duplicados:** reglas de resolución por proyecto, alias y
   conflictos; conservar identificadores y nombres originales.
6. **Revisión:** definir estados de afirmación (`proposed`, `needs_review`,
   `accepted`, `rejected`, `superseded`) y permisos/auditoría para decidirlos.
7. **Integración de cálculos:** establecer qué resultados se replican como
   nodos resumidos en Neo4j y cuáles se consultan por ID desde PostgreSQL/trace;
   fijar retención, versionado e invalidación si cambian entradas.

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
| EG-09 | P1 | ◐ | Cobertura documental y OCR de PDF | DOCX y OCR por página para PDF escaneado están implementados con localizadores y reporte de cobertura. Pendiente: OCR de PDF vectorial sin imagen embebida, extracción robusta de tablas de PDF y validación de calidad/errores parciales por página. |
| EG-10 | P1 | ◐ | Resolución de entidades y alias | Vincular menciones como `T1`, `TX-01` y el nombre de placa al mismo equipo solo con reglas/evidencia suficientes. Si hay ambigüedad, proponer candidato y pregunta; no fusionar entidades automáticamente por similitud débil. |
| EG-11 | P1 | ◐ | Consultas de grafo y API de lectura | Exponer consultas de proyecto para mapa de activos/relaciones, detalle de afirmación con evidencia y conflictos, y filtros por estado/documento/tipo. Aplicar autorización por proyecto y límites de profundidad/tamaño. |
| EG-12 | P1 | ⬜ | Evaluación de calidad del LLM | Crear conjunto versionado y revisado de documentos/hallazgos, medir precisión/recobrado por tipo, exactitud de evidencia, relaciones, abstención y resolución de duplicados. Comparar cambios de modelo/prompt y bloquear promoción si degradan umbrales acordados. |
| EG-13 | P1 | ◐ | Observabilidad, coste y fallos | Registrar modelo, versión de prompt/esquema, tokens/coste, duración, reintentos, errores y conteo de hallazgos por estado sin volcar documentos sensibles en logs. Definir límites por archivo/proyecto y ruta de recuperación/reprocesamiento. |
| EG-14 | P2 | ⬜ | Extracción multimodal de planos | Evaluar OCR/visión para tablas, diagramas unifilares y planos; mantener página/región y exigir revisión de relaciones topológicas. No inferir conexión eléctrica solo por proximidad visual sin evidencia/validación. |
| EG-15 | P0 | ◐ | Esquema de dominio de puesta a tierra | Especificar e implementar nodos/relaciones para instalación, topología, componentes de malla, suelo, mediciones, escenarios de falla, versiones de diseño y ejecuciones de cálculo. Cada tipo declara propiedades/unidades requeridas, relaciones válidas y origen (LLM, usuario, importación o solver). Revisión por especialista antes de congelar v1. |
| EG-16 | P0 | ⬜ | Representación geométrica vinculada al diseño | Modelar conductores como segmentos conectados, electrodos/varillas y puntos de unión con coordenadas, elevación/profundidad, sistema de referencia y unidades. Mantener un ID/versionado común con el artefacto geométrico; geometrías pesadas se guardan en el almacén de artefactos y Neo4j conserva referencias y propiedades para consultas. Validar continuidad/conexiones contra el contrato geométrico del diseño. |
| EG-17 | P0 | ⬜ | Trazabilidad de mediciones y modelo de suelo | Ingerir lecturas originales con arreglo, espaciamiento, unidad, fecha, ubicación y evidencia; enlazar el ajuste/modelo estratificado sin reemplazar datos medidos. Guardar método/versión, residuos e incertidumbre del ajuste y permitir comparar modelos. |
| EG-18 | P0 | ⬜ | Escenarios de falla y supuestos de cálculo | Crear nodos versionados de escenarios con corriente, duración, división de corriente, factores y supuestos/unidades, ligados al proyecto y diseño evaluado. Validar dominios y distinguir duración de choque `t_s` de duración térmica `t_c`; cada dato conserva su fuente y aceptación. |
| EG-19 | P0 | ⬜ | Versionado de ejecuciones y resultados | Registrar cada cálculo como `CalculationRun` inmutable ligado a versión exacta de diseño, suelo, escenario, solver/protocolo y norma/edición. Guardar resultados resumidos (R, GPR, paso/contacto y localizaciones críticas) con IDs de trace/artefacto e incertidumbre. Un nuevo cálculo crea una nueva ejecución; no muta resultados anteriores. |
| EG-20 | P1 | ⬜ | Sincronización Neo4j con artefactos de diseño y solver | Definir eventos/adaptadores desde las fuentes estructuradas del backend al grafo, con versionado e idempotencia. Diferenciar sincronización completa, pendiente y fallida; reconciliar y reintentar sin duplicados. No depender de la extracción LLM para datos que ya entrega el diseño, la ingesta geotécnica o el solver. |
| EG-21 | P1 | ⬜ | Validaciones de dominio y consistencia del grafo | Validar unidades/dimensiones, conexiones de segmentos, pertenencia de equipos, compatibilidad escenario/cálculo y referencias a versiones existentes. Detectar desconexiones, datos incompatibles y resultados huérfanos; emitir diagnósticos explicables en vez de reparar silenciosamente el grafo. |
| EG-22 | P1 | ⬜ | Consultas de ingeniería y vistas del grafo | Añadir consultas para seguir el camino de conexión a tierra, hallar componentes desconectados, comparar modelos de suelo/escenarios/versiones, localizar evidencia de entradas y navegar resultados con su trace. Limitar consultas por proyecto y devolver procedencia junto con cada valor. |
| EG-23 | P1 | ◐ | Migración y restricciones Neo4j | Crear migraciones repetibles del esquema, restricciones de unicidad e índices para IDs de proyecto, documento, equipo, versión y ejecución; definir política ante datos antiguos y procedimiento de rollback/reconstrucción. Verificar consultas y rendimiento con un grafo representativo de tamaño acordado. |

**Leyenda:** ✅ completo; ◐ parcial; ⬜ pendiente. Estados actualizados el 2026-10-05
tras implementar la fundación, la extracción fiable y la persistencia (ver abajo).

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

Pendiente dentro de las tareas parciales: OCR de PDF vectorial
sin imagen embebida y extracción de tablas de PDF (EG-09); fusión confirmada de alias
(EG-10); consultas de ingeniería (EG-11/EG-22); coste y límites por proyecto (EG-13);
validación de la taxonomía con especialista (EG-15); rollback y pruebas de rendimiento
(EG-23).

## Orden recomendado de entrega

1. **Fundación:** EG-01, EG-02 y EG-04. Acordar el contrato y procedencia antes
   de ampliar lo que el LLM escribe.
2. **Extracción fiable:** EG-03, EG-05 y EG-06. Expandir el flujo actual a
   relaciones y hacer que toda propuesta sea comprobable y revisable.
3. **Neo4j listo para operación:** EG-07 y EG-08. Garantizar reintentos,
   auditoría y revisión de una persona de extremo a extremo.
4. **Modelo profesional:** EG-15 a EG-19, coordinados con los contratos de
   artefacto, suelo y solver. Resolver primero IDs, unidades y versionado.
5. **Integración y producto:** EG-09 a EG-11 y EG-20 a EG-23.
6. **Escala y mejora continua:** EG-12 a EG-14.

## Ejemplo de salida del extractor

Para el texto «El transformador T1, 13,8 kV, alimenta el tablero TD-2» el LLM
debería proponer algo equivalente a esto, citando el pasaje y el localizador:

```json
{
  "schema_version": "1.0",
  "entities": [
    {"id": "e1", "type": "Transformer", "name": "T1"},
    {"id": "e2", "type": "ElectricalParameter", "name": "tension", "value": "13.8", "unit": "kV"},
    {"id": "e3", "type": "ElectricalPanel", "name": "TD-2"}
  ],
  "relations": [
    {"id": "r1", "type": "SUPPLIES", "source_id": "e1", "target_id": "e3"},
    {"id": "r2", "type": "HAS_PARAMETER", "source_id": "e1", "target_id": "e2"}
  ],
  "evidence": [
    {"finding_ids": ["e1", "e2", "e3", "r1", "r2"],
     "quote": "El transformador T1, 13,8 kV, alimenta el tablero TD-2",
     "locator": {"page": 4}}
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

Subir un PDF escaneado o digital o DOCX, obtener
hallazgos tipados con relación y referencia navegable a la fuente, persistirlos
en Neo4j de manera idempotente, ver duplicados/conflictos, resolverlos desde la
interfaz con auditoría y consultar después el grafo por proyecto. Además, los
componentes, geometría, mediciones, modelos de suelo, escenarios y ejecuciones
de cálculo deben enlazarse con sus versiones exactas y procedencia. El grafo
debe detectar datos huérfanos o incompatibles sin corregirlos en silencio. Los
parámetros extraídos que consumen cálculos requieren aceptación humana explícita;
las salidas del solver se registran como resultados derivados inmutables.
