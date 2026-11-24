# Backlog de producto — Allectricity

Estado: **propuesta acordada** · Fecha: 2026-10-07 · Ids: `PR-NN`

Este backlog ordena el producto alrededor de un único artefacto. El backlog técnico
(`BACKLOG.md`, ids `BL-NN`) sigue vigente para motor, normativa y operación; aquí se
referencia cuando una tarea depende de él.

## 1. Visión

**Para** ingenieros que necesitan diseñar una puesta a tierra o editar una existente,
**Allectricity** convierte sus documentos en un estudio calculado, interpretado y listo para
compartir, **sin llenar datos ni dibujar a mano** cuando se puede evitar. El ingeniero
conversa con un agente que infiere las entradas, configura y corre el solver, e
interpreta el resultado; cada número del estudio se puede rastrear hasta su fuente.

**Promesa en una frase:** sube tus archivos y Allectricity te entrega un estudio completo en
borrador; confirmas lo que falta con un clic y lo compartes.

**Lo que no es:** no certifica ni sustituye al ingeniero que firma; no es un CAD general;
no cubre (por ahora) apantallamiento IEC 62305.

## 2. Modelo del producto

```
Nivel 0  Fuentes     archivos → grafo            onboarding, evidencia y referencias
         ── paso intermedio: interrogación (grafo → entradas, confirmación del usuario)
Nivel 1  Entradas    suelo · parámetros eléctricos · geometría y entorno constructivo
Nivel 2  Resultado   solver + interpretación     pieza central
Nivel 3  Estudio     vista web / PDF compartible, personalizable
                ▲
       el chat itera cualquier nivel · interfaz: chat | artefacto
```

Cada valor del artefacto lleva dos marcas:

- **Origen:** `claim` (extraído del grafo, con evidencia), `document`, `tool` (cálculo o
  ajuste), `user` (confirmado o forzado por el usuario), `assumption` (supuesto).
- **Vigencia:** al día o **desactualizado**. Si cambia el Nivel 1, el Nivel 2 queda
  desactualizado; si cambia el Nivel 2, el Nivel 3 queda desactualizado.

## 3. Decisiones tomadas

| # | Decisión | Consecuencia |
|---|---|---|
| D1 | El artefacto versionado es la **única** fuente de verdad. | El plano, los formularios y los resultados dejan de tener estado propio. |
| D2 | El grafo es ingesta y evidencia, no una pantalla de trabajo. | Sale de la navegación principal; se consulta desde los valores y alimenta las referencias del estudio. |
| D3 | **Mostrar primero, confirmar después.** El agente construye todo y, si falta un dato crítico, usa un supuesto explícito. | El estudio queda en **borrador** con marca de agua «N supuestos sin confirmar» y no se publica como final hasta confirmarlos. Cambia la regla actual de `patches.py` (ver PR-25). |
| D4 | La interfaz es **chat \| artefacto**. | Desaparece la columna de entradas; las entradas son secciones del artefacto. |
| D5 | El usuario puede editar el artefacto directo (incluso forzar un valor). | Cada edición directa aparece como evento en el chat y propaga la vigencia. |
| D6 | El estudio publicado queda fijado a una versión del artefacto. | Si el diseño cambia, el estudio muestra «existe una versión más reciente»; el autor decide republicar. |
| D7 | La marca Allectricity se puede quitar; la trazabilidad técnica no se elimina, se puede mover a un anexo. | El estudio sigue siendo defendible ante revisión. |
| D8 | **Reciclar antes que construir.** | Toda tarea indica qué reutiliza; lo nuevo se justifica. |

## 4. Inventario de reciclaje

Lo que ya existe y el papel que toma en el producto nuevo.

| Pieza existente | Dónde | Nuevo papel |
|---|---|---|
| Artefacto versionado + diff + restaurar | `artifact_routes.py`, `domain/agent/patches.py` | Fuente de verdad única (D1) |
| Origen por campo (`origin.provenance`, `SOURCE_KINDS`, `CRITICAL`, `unconfirmed_critical`) | `domain/agent/patches.py`, `design_agent.py:137` | Marca de origen de cada valor; lista de pendientes |
| Atributos `feeds_calculation` y conversión de unidades (`parse_quantity`) | `domain/knowledge_graph/taxonomy.py` | Lista fija de datos que la interrogación debe llenar |
| Afirmaciones con evidencia, decisiones y preguntas | `knowledge_graph_routes.py`, `KnowledgeGraphWorkspace.jsx` | Revisión en onboarding, panel de evidencia y referencias del estudio |
| Herramientas del agente (`confirm_inputs`, `stage_from_table`, `fit_soil`, `explode_grid`, `clip_zone`, `request_calculation`) y subagentes (`run_soil_modeler`, `run_grid_designer`, `run_safety_analyst`) | `infrastructure/agents/design_agent.py` | Cadena «infiere todo y construye» |
| Ejecuciones, eventos, stream, memoria, cancelación | `agent_routes.py`, `chat_routes.py` | Hilo del proyecto; eventos de edición directa |
| Tarjeta «Se editó el artefacto» con deshacer | `ArtifactUpdateCard` en `AgentArtifact.jsx` | También para ediciones del usuario |
| Editor de plano con conductores, electrodos y elementos constructivos | `GroundingPlanDrawer.jsx` | Editor de geometría del artefacto (sin `localStorage`) |
| Formularios de mediciones, suelo y parámetros; gráfica de ajuste | `GroundingCalculations.jsx`, `SoilFitChart` | Editores dentro de las secciones del Nivel 1 |
| Vista de malla, resultados, mapa de potencial, 3D | `ArtifactGrid`, `AgentResultsPanel`, `SurfacePotentialMap`, `Surface3D.jsx` | Nivel 2 y bloques del estudio |
| Carga presignada, cuarentena, OCR, rasterizado de PDF | `file_routes.py`, `services/ocr`, `pypdfium2` | Fuentes, logo del estudio, plano de fondo |
| Prompts versionados en Arize Phoenix + cliente LLM | `document_agents.py`, `design_agent.py` | Párrafos con IA del estudio, lectura del plano |
| Evaluación de extracción | `domain/knowledge_graph/evaluation.py`, `processing/extraction_evaluation.py`, `docs/documentos_prueba` | Medir la interrogación antes de mostrarla |
| Celery + MinIO | `worker/tasks.py`, `storage/object_storage.py` | Generación y almacenamiento del PDF |
| Playwright (ya en `devDependencies`) | `app/package.json` | Render HTML → PDF desde la misma vista web |
| `ezdxf` (extra opcional `parsers`) | `dependencies/pyproject.toml` | Importación DXF (más adelante) |

## 5. Hitos

| Hito | Resultado visible | Tareas |
|---|---|---|
| **H1 · Una sola verdad** | Lo que se ve es lo que está guardado; nada se contradice. | PR-01 a PR-06, PR-10 a PR-13 |
| **H2 · Wow** | Subo archivos → Allectricity me interroga → construye todo → resultado interpretado en borrador. | PR-20 a PR-26, PR-30 a PR-32 |
| **H3 · Compartir estudio** | Publico el estudio como página o PDF, con mi logo y mis textos. | PR-50 a PR-57 |
| **H4 · Entorno constructivo** | El agente lee el plano y propone dónde va la malla. | PR-40 a PR-44 |

H1 va primero porque H2 sin una sola verdad reproduce las incoherencias actuales.

## 6. Tareas

### E0 · Una sola verdad (H1)

| Id | Tarea y criterio de aceptación | Recicla | Depende |
|---|---|---|---|
| PR-01 | ✅ **Implementada.** **El plano se guarda en el artefacto.** El editor lee y escribe `geometry` (conductores, varillas, elementos constructivos) y cada guardado crea versión; se elimina `localStorage` (`GroundingPlanDrawer.jsx`, `AgentArtifact.jsx`). La vista previa y el drawer muestran el mismo número de elementos. | `GroundingPlanDrawer`, `POST …/versions`, `geometry.conductors`/`geometry.rods` | PR-40 (obstáculos en el esquema) |
| PR-02 | ✅ **Implementada.** **Sin valores por defecto en datos de entrada.** Los formularios, las lecturas y las capas manuales arrancan vacíos y muestran «falta»; los valores típicos del catálogo solo se ofrecen como opciones y no se aplican automáticamente. Los defaults del esquema backend se conservan para permitir artefactos incrementales y quedan distinguidos como `schema_default` en la procedencia. | `CRITICAL`, `UNCONFIRMED` de `patches.py` | — |
| PR-03 | ✅ **Implementada.** La API y la interfaz indican la vigencia del cálculo y del estudio publicado; una publicación fija su versión y avisa cuando existe una posterior. | `calculos_potencial_tierras` y estudios fijados | PR-50, PR-56 |
| PR-04 | ✅ **Implementada.** La API expone `origin.provenance` de la versión y la interfaz muestra chips de procedencia para Malla, Suelo, Falla y Conductor (`Extraído`, `Documento`, `Confirmado`, `Calculado`, `Supuesto` o `Predeterminado`), con referencia/nota accesible en el detalle del chip. | `persisted_provenance`, `fieldLabels`, `AgentArtifact` | — |
| PR-05 | ◐ **Parcial.** Las respuestas de error en texto plano ya se traducen a mensajes de usuario y Escape cierra el drawer del plano. **2026-11-15, causas encontradas por lectura del código y corregidas:** (1) el panel de resultados (`AgentArtifact`) convertía cualquier respuesta no OK (5xx, token vencido) en «lista vacía» y mostraba «Sin cálculo» con una versión existente; ahora solo un 404 es «no hay» y el resto pasa a estado de error. (2) El espacio del proyecto cargaba archivos, conversaciones y memoria con un `Promise.all`: si fallaba uno (p. ej. memoria), los archivos quedaban en 0 y la conversación sin abrir; ahora cada lista se carga por separado (`allSettled`) y el fallo se informa sin ocultar las demás. **Falta:** reproducir el caso en navegador contra el stack local para cerrarlo de forma verificable y revisar el polling simultáneo de `AgentArtifact` (1,5 s) y `GroundingCalculations` cuando ambos están montados. | `AgentArtifact`, `ProjectChatWorkspace` | — |
| PR-06 | ✅ **Implementada.** Las versiones creadas/restauradas por el usuario desde el plano o formularios publican `artifact.updated` en la conversación activa con diff, deshacer, procedencia `user` y aviso de resultado desactualizado. Las ediciones del agente conservan el mismo contrato. | `ArtifactUpdateCard`, `patches.diff`, mensaje `artifact.updated` | PR-03, PR-04 |

### E1 · Interfaz chat | artefacto (H1)

| Id | Tarea y criterio de aceptación | Recicla | Depende |
|---|---|---|---|
| PR-10 | ✅ **Implementada.** La interfaz queda en dos columnas: chat \| artefacto. Se eliminó la columna de entradas: un único panel de artefacto agrupa sus secciones por nivel (Resumen · Fuentes · Entradas: Mediciones, Suelo, Parámetros eléctricos, Plano · Resultado) con una sola navegación. Los formularios de `GroundingCalculations`, el plano y los paneles de artefacto/resultados se reutilizan sin reescribirse. En escritorio el chat queda fijo mientras se recorre el artefacto; en móvil se alterna con las pestañas Chat / Artefacto. «Ver artefacto» desde una tarjeta del chat abre la sección Resumen. | `ProjectChatWorkspace`, `AgentArtifactPanel`, `AgentResultsPanel`; los formularios de `GroundingCalculations` se mueven a las secciones, no se reescriben | PR-01, PR-02 |
| PR-11 | ✅ **Archivos desde el chat.** Adjuntar en el compositor y soltar archivos sobre el chat usan la carga actual; la sección Fuentes lista archivos y su estado de análisis. | Flujo de carga de `ProjectChatWorkspace`, `MeasurementTemplates` | PR-10 |
| PR-12 | ✅ **Grafo fuera de la navegación principal.** Se accede desde Fuentes («ver lo extraído») y desde los chips de origen. `KnowledgeGraphWorkspace` se conserva como vista avanzada. | `KnowledgeGraphWorkspace` | PR-10 |
| PR-13 | ✅ **Panel de evidencia.** Clic en un origen de valor extraído abre la afirmación con su cita, documento y localizador; las candidatas se resuelven desde el grafo existente. | `GET /claims/{id}`, `GET /documents/{id}/source`, tabla de afirmaciones | PR-04 |

### E2 · Interrogación y construcción (H2)

| Id | Tarea y criterio de aceptación | Recicla | Depende |
|---|---|---|---|
| PR-20 | ✅ **Implementada.** Módulo de dominio puro que traduce afirmaciones de atributos `feeds_calculation` a rutas del artefacto (`fault_current` → `fault.current_a`, `shock_duration` → `fault.clearing_time_s`, `surface_layer_*` → `fault.surface_*`, `grid_length`/`grid_width` → `geometry.*`, etc.) en unidades SI. Devuelve por ruta: valor, afirmación de origen, candidatas y estado (`encontrado`, `conflicto`, `falta`). Con pruebas. | `taxonomy.py` (`AttributeSpec`, `parse_quantity`) | — |
| PR-21 | ✅ **Implementada.** Si hay varias candidatas para una ruta, se aplica una regla explícita (afirmación aceptada, tipo de documento preferente y fecha de fuente) y si no alcanza, se convierte en pregunta. | `consolidation.py`, preguntas del grafo | PR-20 |
| PR-22 | ✅ **Implementada.** Las lecturas `ResistivityReading` (espaciamiento, resistividad aparente, arreglo) pasan a `soil_measurements` con localizadores, sin completar faltantes con defaults, y quedan listas para el ajuste existente. | `stage_from_table`, `fit_soil`, `n_layer_soil.py` | PR-20 |
| PR-23 | ✅ **Implementada.** Tras la ingesta, el sistema publica en el chat: «Encontré N de M datos», con lo encontrado (con fuente), los conflictos y lo que falta; el payload incluye los IDs para confirmación en bloque. | `pending_confirmations`, `confirm_inputs`, `POST /claims/decisions` | PR-20, PR-21 |
| PR-24 | ✅ **Implementada.** El orquestador recibe el mapeo completo de entradas y la resolución de conflictos, y la instrucción de encadenar mapeo → ajuste de suelo → propuesta de malla → aplicar → cálculo, con eventos de progreso visibles. Se eliminó el contexto fijo de 12 afirmaciones. | Orquestador y subagentes de `design_agent.py`, `request_calculation` | PR-20, PR-22, PR-25 |
| PR-25 | ✅ **Implementada.** En modo borrador, un dato crítico puede tomar un supuesto explícito con nota visible; la versión y su tarjeta llevan marca «N supuestos sin confirmar». Sin el marcador de borrador se mantiene la regla que bloquea supuestos críticos. | `patches.py`, `unconfirmed_critical`, `AgentArtifact` | — |
| PR-26 | ✅ **Implementada como evaluación inicial.** Conjunto versionado, gold validado contra taxonomía, puntuación de rutas/evidencia/abstención/duplicados/invariantes, CLI, líneas base y bloqueo por umbrales. Queda pendiente acordar el gold y umbrales con especialista antes de demos. | `evaluation.py`, `extraction_evaluation.py` | PR-20 |

### E3 · Resultado central (H2)

| Id | Tarea y criterio de aceptación | Recicla | Depende |
|---|---|---|---|
| PR-30 | ✅ **Resultado como sección principal.** Muestra cumplimiento de contacto, paso y sección térmica, mapa de potencial y 3D, prioriza la versión vigente, conserva aviso de vigencia para resultados históricos y permite «Recalcular» desde el panel con seguimiento hasta completar. | `AgentResultsPanel`, `SurfacePotentialMap`, `Surface3D` | PR-03, PR-10 |
| PR-31 | ✅ **Interpretación estructurada.** El agente conserva el veredicto determinista y el analista explica cumplimiento, restricción dominante y motivo; Resultados lo muestra y cada recomendación es un botón que envía la acción al chat («agrega varillas en el perímetro y recalcula»). | `run_safety_analyst`, `calculation_summary.py`, `AgentResultsPanel` | PR-30 |
| PR-32 | ✅ **El agente configura el solver.** El modelador de suelo elige el número de capas; Resultados permite ajustar discretización, segmentación, raster e incertidumbre. La justificación se registra en los parámetros/traza del cálculo y el backend valida los límites del motor antes de encolar. | `request_calculation`, `PotentialCalculationRequest`, `potential_engine_validation.py`, `AgentResultsPanel` | BL-09 |
| PR-33 | ◐ **Iteración automática** hasta cumplir o agotar N intentos (FA-7 de `AGENTE_DISENO_SPAT.md`). En modo autónomo, cada intento ajusta la geometría mediante el diseñador, crea una versión nueva, recalcula y conserva el mejor candidato; el límite es configurable (`DESIGN_MAX_ITERATIONS`, por defecto 3). Falta integrar alternativas de costo/BOM de BL-20 para optimizar bajo restricciones económicas. | Orquestador | PR-31, BL-20 |

### E4 · Entorno constructivo (H4)

| Id | Tarea y criterio de aceptación | Recicla | Depende |
|---|---|---|---|
| PR-40 | ✅ **Implementada.** Elementos constructivos rectangulares persistidos en `geometry.structures`; el editor y backend rechazan conductores/varillas dentro o atravesando obstáculos y estructuras fuera del perímetro. | «Elemento constructivo» del drawer, `clip_zone`, `grid_geometry.py` | BL-19 (geometría v2) |
| PR-41 | ✅ **Implementada.** Imágenes y páginas PDF se asocian a una versión; el backend rasteriza la página PDF elegida a PNG con límites de DPI/tamaño y el editor calibra visualmente con dos puntos/cotas, guarda la escala, página, dimensiones y offsets, y restaura correctamente el fondo al abrir la versión. | Carga presignada, `pypdfium2`, `GroundingPlanDrawer` | PR-01 |
| PR-42 | ◐ **Parcial avanzada.** El adaptador multimodal acepta imágenes y páginas PDF, valida y acota las detecciones, y la interfaz muestra una tarjeta de revisión con advertencias, lista de obstáculos y confirmación explícita. Al aceptar, se incorporan como elementos constructivos editables y se guardan mediante la versión normal del artefacto. Falta la evaluación sobre un conjunto de planos reales y métricas de precisión. | Cliente LLM, `clip_zone`, PR-40 | PR-40, PR-41 |
| PR-43 | ◐ **Parcial avanzada.** Al solicitar el análisis de una nueva fuente de plano, el backend compara automáticamente la propuesta contra la versión vigente, reporta obstáculos añadidos, eliminados, modificados y conflictos con la malla, y publica una alerta estructurada `plan.revision` en el chat sin mutar el artefacto. Falta dispararlo directamente desde el evento de disponibilidad de cada carga y ofrecer acciones de aceptar/rechazar desde la tarjeta del chat. | PR-06 (alertas), PR-42 | PR-42 |
| PR-44 | ✅ **Implementada.** DXF ASCII con LINE, LWPOLYLINE, POLYLINE y CIRCLE se convierte en una propuesta acotada por entidades/capas; el editor permite revisarla antes de guardarla como versión. | `ezdxf` (extra `parsers`) | BL-18 |

### E5 · Compartir estudio (H3)

| Id | Tarea y criterio de aceptación | Recicla | Depende |
|---|---|---|---|
| PR-50 | ✅ **Implementada.** Modelo persistido de estudio fijado a artefacto/versión, configuración de secciones, marca, trazabilidad, acceso, expiración y migración Alembic. | Patrón de versiones del artefacto | PR-03 |
| PR-51 | ✅ **Implementada.** Página de solo lectura con URL estable (`/e/{slug}`) que compone bloques del artefacto y conserva el aviso de versión más reciente. | Artefacto versionado y resultados | PR-50 |
| PR-52 | ✅ **Implementada.** Editor de secciones activas, textos, logo, marca Allectricity y acceso desde «Compartir estudio»; configuración guardada y vista pública actualizada. | Configuración persistida y carga presignada | PR-51 |
| PR-53 | ✅ **Implementada.** La vista pública lista referencias automáticas por ruta desde `origin.provenance`, incluyendo referencia, nota y tipo de origen. | `origin.provenance`, afirmaciones y localizadores del grafo | PR-04, PR-50 |
| PR-54 | ✅ **Implementada.** Público, solo con enlace, contraseña, revocación y expiración, con gestión desde el editor y validación en el endpoint público. | Capa de seguridad actual | PR-51 |
| PR-55 | ✅ **Implementada.** La vista conserva impresión local y el backend encola render Chromium/Playwright, almacena el PDF en MinIO y expone una URL firmada. | Celery, MinIO, Playwright | PR-51 |
| PR-56 | ✅ **Implementada.** La publicación fija la versión, avisa de versiones nuevas y «Republicar nueva versión» crea otro slug; la anterior permanece intacta. | PR-03 | PR-50 |
| PR-57 | ✅ **Implementada.** Supuestos críticos impiden publicar como final; los borradores llevan marca de agua visible. | PR-25 | PR-25, PR-51 |
| PR-58 | **Dominio propio del cliente** (`estudios.miempresa.com`). Candidato a plan de pago; después de H3. ⏸ **En espera comercial (15 nov):** se decide después de H3. | — | PR-51 |

## Iniciativa: catálogo reutilizable, BOM y cotizaciones

Solicitado el 23 nov 2026. El catálogo debe separar referencias generales del usuario (reutilizables en todos sus proyectos) de referencias particulares de un proyecto. El formulario debe admitir cualquier material, equipo o servicio y presentar unidad, contactos accionables, imágenes y plazos con el origen de cada dato. La búsqueda libre debe conservar la lista de referencias halladas para revisión.

- **BOM / BOMElement:** representar cantidades requeridas por instalación y permitir excedentes explícitos por elemento (porcentaje o cantidad adicional), conservando cantidad base, regla aplicada y total calculado para revisión. **Hecho (2026-11-23):** los excedentes por porcentaje y cantidad adicional se guardan por proyecto, diseño y versión en `bom_adjustments`; la tabla muestra base y cantidad de compra sin cambiar el artefacto geométrico. La publicación del estudio también muestra ambos valores. Migración `0030_bom_adjustments`.
- **Quotation / QuotationElement:** cotización numerada, estado y vigencia; derivar partidas de BOM, costo, margen/rentabilidad, descuentos, impuestos y tipo, transporte por partida o global, condiciones y datos de contacto/pago del usuario. Guardar decisiones de presentación de campos (por ejemplo, mostrar forma de pago o impuestos). **Hecho (2026-11-23, primera versión):** API persistida por proyecto con numeración, estados, vigencia e historial inmutable; calcula costo base, margen, descuentos, impuestos y transporte sin mezclar moneda ni completar precios. Partidas sin precio bloquean marcar como enviada. La UI crea borradores desde el catálogo aprobado y permite agregar partidas/precios con fuente.
- **Grupos de cotización:** entidad `QuotationGroup` para agrupar partidas como «Subestación» (transformador, cables, etc.) dentro de la cotización de un proyecto. **Hecho (2026-11-23):** grupos y partidas son parte del snapshot versionado de cotización, y se pueden editar desde la UI.
- **Editor de cotización:** ofrecer una tabla estructurada y un editor narrativo con bloques de texto, tablas y descripciones, similar al editor de informes. **Parcial:** partidas, condiciones y bloques de texto/tablas editables; vista imprimible/PDF desde el navegador implementada. Falta exportación PDF de servidor y revisión visual integral.
- **Plantillas y agentes:** permitir plantillas reutilizables de cotización e informe de puesta a tierra; habilitar un agente cotizador y un agente de informes que compongan estos elementos sin inventar precios, fuentes ni datos técnicos. **Parcial:** plantillas personales de cotización persistidas (`0032_quotation_templates`) guardan grupos y redacción, y al aplicarse dejan precios y fuentes en blanco para revisión. El agente cotizador existente agrega recomendaciones sin precio a un borrador; falta plantilla reutilizable de informe y conectar el agente de informes a datos versionados del borrador.
- **Plantilla de servicios:** modelar precio global por un entregable único (p. ej. comisionamiento de equipo) o tarifa por unidad medible (p. ej. excavación por m³ o instalación por hora). Registrar cantidad, unidad, alcance/criterio de aceptación y duración; separar duración del trabajo de tiempo de espera o disponibilidad. **Hecho (2026-11-23):** `service_details` versionado junto con cada cotización registra `pricing_type` (`fixed`/`measured`), alcance, criterio de aceptación, duración de trabajo y espera/disponibilidad por separado. La API exige esos datos para servicios y valida que precio fijo use la unidad `servicio` y el medido declare otra unidad; el formulario los captura sin mezclarlos con notas. Migración `0028_service_catalog_details`.

**Resto de la iniciativa, todavía pendiente:** conectar el agente de informes con los datos versionados y generar informes sin inventar. La cotización crea partidas desde el BOM disponible y fija diseño/versión; también agrega las referencias aprobadas del catálogo. Los precios quedan vacíos hasta aportar una fuente.

**Actualización (2026-11-23):** catálogo personal reutilizable disponible mediante alcance «Mi catálogo reutilizable», con opción de copiar referencias a un proyecto como candidatas; contactos, imagen y disponibilidad se persisten en campos estructurados y guardan procedencia/fecha de consulta (`0029_catalog_provenance`). BOM con excedentes por versión en `0030_bom_adjustments`. Cotizaciones agrupadas/versionadas y cálculos comerciales iniciales en `0031_quotations`; partidas iniciales desde catálogo aprobado y BOM fijado a una versión; plantillas personales que reutilizan grupos y textos, pero eliminan precios y fuentes al aplicarse, en `0032_quotation_templates`; vista imprimible/guardar PDF del navegador y bloques narrativos editables en texto y tabla. **Pendiente:** prueba integral con base migrada y agente de informes conectado a datos versionados sin inventar.

Imágenes y plazos de servicio/despacho pueden capturarse cuando la fuente los publique, conservando URL y fecha de consulta; si la búsqueda no los encuentra, quedan sin confirmar para completar por contacto con el proveedor.

## 7. Qué se congela

No se borra; no recibe trabajo hasta cerrar H2:

- Vista 3D (más allá de mantenerla funcionando) y voz (BL-25).
- Mejoras del motor que no pide PR-32: BL-09 (revisión independiente aparte), BL-10, BL-24.
- IEC 62305 (BL-23), clientes M2M y roles por proyecto (BL-05) salvo lo que exija PR-54.
- Extracción nueva en el grafo fuera de los atributos `feeds_calculation` y planos.

## 8. Qué se elimina o se mueve

| Hoy | Pasa a |
|---|---|
| Plano en `localStorage` | `geometry` del artefacto (PR-01) |
| Valores por defecto en formularios | Campos vacíos con estado «falta» (PR-02) |
| Columna izquierda (Archivos, Mediciones, Modelo suelo, Parámetros) | Secciones del artefacto y Fuentes (PR-10, PR-11) |
| Grafo como pestaña principal | Onboarding, evidencia y referencias (PR-12, PR-13, PR-53) |
| Panel Resultados suelto | Sección Resultado (PR-30) |
| Contexto de 12 afirmaciones para el agente | Resultado del mapeo (PR-24) |
