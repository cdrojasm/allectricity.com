# Caso de uso — Agente de diseño de puesta a tierra (Terra)

Estado: **especificación para implementar** · Fecha: 2026-10-06 · Backlog: `AG-NN` (ver §12)

## 1. Objetivo

Ayudar al usuario a construir, de forma **total o parcial**, el sistema de puesta a
tierra de un proyecto. El agente trabaja sobre el **artefacto de diseño de tierras**
(`artefacto_diseno_tierras`) a partir de la conversación del proyecto, los archivos
cargados y el grafo de conocimiento, y usa los cálculos trazables existentes
(ajuste de suelo, dimensionamiento térmico, motor de potencial, criterios de seguridad).

El agente **propone y ejecuta trabajo de ingeniería; no certifica**. Ninguna salida
es memoria de cálculo aprobada (ver principio del `BACKLOG.md`). Un criterio de
cumplimiento solo puede marcarse `compliant` con un cálculo trazable que lo respalde,
y siempre queda sujeto a revisión de un profesional competente.

### Ejemplos de solicitudes

| Alcance | Ejemplo | Qué hace el agente |
|---|---|---|
| Total | «Diséñame la malla de la subestación con los documentos que subí» | Recoge datos → modela suelo → propone malla y conductor → calcula → itera hasta cumplir o agotar presupuesto → reporta |
| Parcial | «Ajusta el suelo con las mediciones Wenner del Excel» | Solo modelado de suelo; crea versión nueva |
| Parcial | «¿Por qué no cumple la tensión de contacto?» | Lee el último cálculo y explica; no modifica nada |
| Parcial | «Agrega 8 varillas en el perímetro y recalcula» | Edita geometría, crea versión, encola cálculo, interpreta |
| Consulta | «¿Qué datos faltan para calcular?» | Revisa el artefacto y el grafo, lista faltantes y pregunta |

## 2. Actores y precondiciones

- **Usuario** autenticado, dueño del proyecto (o rol privilegiado), con `designs:write`
  para que el agente modifique artefactos; con solo `designs:read` el agente trabaja
  en modo consulta. El agente **actúa con los permisos del usuario que lo activó**,
  nunca con más.
- **Proyecto** existente con una conversación (`conversations`).
- Proveedor LLM y Langfuse configurados (mismo patrón que `document_agents.py`:
  `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, prompts por nombre/label). Si no lo están,
  el agente responde con un mensaje explícito y no simula trabajo.
- **Presupuesto** de tokens activo del usuario (`budget`). Sin presupuesto, el run no arranca.

## 3. Flujo principal

```
Usuario ──POST /conversations/{id}/messages──► API
                                               │ crea chat_message(user, pending)
                                               │ crea agent_run(queued)          (misma transacción)
                                               └► Celery spat.agent_run_step(run_id)
Worker: Orquestador
  1. Carga estado (artefacto + conversación + memoria del run)
  2. Clasifica intención y alcance → plan de pasos          ──► evento plan.created
  3. Por cada paso: delega a un subagente                   ──► step.started / subagent.*
       subagente usa herramientas (lectura libre, escritura vía propuestas)
  4. Aplica cambios validados al borrador y hace commit de versión ──► artifact.version_created
  5. Si necesita cálculo: encola y SUSPENDE el run           ──► run.waiting_calculation
       al terminar spat.calculate_artifact_potential → reanuda el run
  6. Si necesita dato del usuario: pregunta y SUSPENDE        ──► question.asked / run.waiting_user
       el siguiente mensaje del usuario reanuda el run
  7. Respuesta final como chat_message(agent)                ──► run.completed
Frontend: polling de eventos y mensajes con cursor
```

### Flujos alternos

| Id | Situación | Comportamiento |
|---|---|---|
| FA-1 | Faltan datos críticos (Ik, t_s, capa superficial, resistividad) | El agente pregunta (`ask_user`), queda `waiting_user` y no encola cálculos. Nunca propone un valor típico para un dato crítico; para datos no críticos sí, marcado como supuesto (§13, decisión 4). |
| FA-2 | El usuario escribe mientras el run trabaja | El mensaje se guarda y se encola en el *inbox* del run; el orquestador lo lee en el siguiente punto de control (entre pasos) y puede replanificar. No se crea un segundo run. |
| FA-3 | El usuario cancela | `POST /agent-runs/{id}/cancel`: estado `cancelling`; el paso en curso termina, no se hace commit de nada pendiente, se cancela el cálculo encolado del run y queda `cancelled`. Las versiones ya creadas se conservan (son inmutables). |
| FA-4 | Otro actor creó una versión del artefacto durante el run | El commit falla por concurrencia optimista (`base_version`). El orquestador relee, rehace el diff sobre la nueva versión o pregunta si hay conflicto en los mismos campos. |
| FA-5 | El cálculo falla o el modelo de suelo está fuera del alcance del motor | Evento `step.failed` con el error del motor; el agente explica y propone alternativa (p. ej. reducir capas). |
| FA-6 | Se agota presupuesto, rondas o cálculos permitidos | Termina en `completed` con estado parcial explícito («hice X, faltó Y») o `failed` si no hubo progreso útil. |
| FA-7 | El diseño no converge a cumplir | Tras N iteraciones (configurable, por defecto 3) se detiene, reporta el mejor candidato y qué restricción domina. |
| FA-8 | Error de infraestructura (LLM caído, timeout) | Reintento con backoff en el paso; tras agotar reintentos, `failed` con mensaje al usuario. El run es reanudable manualmente (`POST /agent-runs/{id}/resume`). |

## 4. Modos de autonomía (ayuda total o parcial)

El usuario elige el modo por conversación (por defecto **asistido**); se puede cambiar
en el mensaje («hazlo tú», «solo proponme»).

| Modo | Escritura del artefacto | Cálculos | Uso típico |
|---|---|---|---|
| `consulta` | No escribe | Lee resultados existentes | Explicar, revisar, listar faltantes |
| `asistido` | Aplica los cambios pedidos de inmediato (versión nueva) y avisa con la tarjeta «Se editó el artefacto», que permite deshacer | Solo cuando el usuario los pide | Por defecto |
| `autonomo` | Igual que asistido, y además itera por su cuenta (cálculo, ajuste) dentro de los límites | Encola libremente dentro de los límites | Diseño completo de punta a punta |

En **todos** los modos: los datos críticos de entrada requieren confirmación humana
(alineado con BL-15), cada cambio crea versión nueva (nunca sobrescribe) y el agente
no marca cumplimiento sin cálculo trazable.

## 5. Estado

El agente tiene tres estados separados con dueño y ciclo de vida distintos.

### 5.1 Estado del artefacto (fuente de verdad del diseño)

- Es el snapshot versionado existente (`GroundingArtifactRequest`: `geometry`,
  `soil_layers`, `soil_measurements`, `fault`, `conductor`, `compliance`). El agente
  **no crea otro modelo de diseño**.
- Durante un run, el agente trabaja sobre un **borrador** en memoria del run
  (`agent_runs.draft_snapshot`) basado en `base_version`. Las herramientas de edición
  modifican el borrador; `commit_version` lo valida con el mismo esquema Pydantic que
  la API y crea la versión `last_version + 1` si `base_version` sigue siendo la última.
- Cada versión creada por el agente guarda `created_by = usuario`, y en una columna
  nueva `origin = {"kind": "agent", "run_id": ..., "summary": ...}` para trazabilidad.
- Los resultados de cálculo siguen en `calculos_potencial_tierras`, ligados a la versión.

### 5.2 Estado de la conversación

- Mensajes en `chat_messages` (usuario, agente, notificación) — existente.
- **Memoria de la conversación** (`agent_conversation_state`, una fila por conversación):
  `artifact_id` activo (uno solo por conversación, ver §13), modo de autonomía, resumen rodante de la conversación,
  supuestos aceptados por el usuario (con mensaje de origen), preguntas abiertas y
  decisiones tomadas. Se actualiza al final de cada run. Permite que un run nuevo no
  tenga que releer los 5000 mensajes.
- Contexto enviado al LLM: resumen + últimos K mensajes (K=20 por defecto) + estado del
  artefacto + preguntas abiertas.

### 5.3 Estado del run (ejecución)

Máquina de estados de `agent_runs.status`:

```
queued → running ⇄ waiting_calculation
            ⇅
        waiting_user
running → completed | failed
cualquier no terminal → cancelling → cancelled
```

Campos: `id`, `conversation_id`, `trigger_message_id`, `project_id`, `artifact_id`,
`base_version`, `mode`, `status`, `plan` (JSON: pasos con estado), `current_step`,
`draft_snapshot`, `pending_calculation_id`, `pending_question`, `inbox` (ids de mensajes
recibidos durante el run), `usage` (tokens, rondas, cálculos), `error`,
`created_by`, `created_at`, `updated_at`, `finished_at`.

Regla: **máximo un run no terminal por conversación** (índice único parcial o
verificación en transacción). Un mensaje nuevo con run activo va al inbox (FA-2) o
reanuda un `waiting_user`.

**Reanudable por diseño:** el run no bloquea un worker mientras espera. Cada paso es
una tarea Celery corta (`spat.agent_run_step`) que persiste el estado antes de salir.
Esperar un cálculo (hasta 10 min) o al usuario solo deja el run suspendido en BD;
`calculate_artifact_potential` y `create_message` encolan `agent_run_step` al terminar.

## 6. Notificaciones asíncronas y polling

### 6.1 Eventos

Tabla `agent_events` (append-only):

| Campo | Descripción |
|---|---|
| `id` | UUID |
| `run_id`, `conversation_id` | Pertenencia |
| `seq` | Entero monotónico **por conversación** (cursor de polling) |
| `type` | Ver catálogo |
| `level` | `info` · `progress` · `warning` · `error` · `success` |
| `title` | Texto corto para el usuario, en español (≤ 200) |
| `detail` | Texto opcional |
| `payload` | JSON (ids de versión, cálculo, pregunta, progreso 0–1, subagente…) |
| `created_at` | Epoch |

Catálogo de `type`:

`run.started`, `plan.created`, `plan.updated`, `step.started`, `step.completed`,
`step.failed`, `subagent.started`, `subagent.completed`, `tool.called` (solo
herramientas relevantes para el usuario, sin argumentos sensibles),
`artifact.proposal_ready`, `artifact.version_created`, `calculation.queued`, `message.received`,
`calculation.completed`, `calculation.failed`, `question.asked`, `run.waiting_user`,
`run.waiting_calculation`, `run.resumed`, `run.completed`, `run.failed`, `run.cancelled`.

Los hitos (`plan.created`, `artifact.version_created`, `calculation.completed`,
`question.asked`, `run.*` terminal) se **reflejan además** como `chat_messages` con
`source = 'notification'`, que el frontend ya distingue. Los eventos de progreso fino
solo viven en `agent_events` para no inundar la conversación.

Los eventos nunca incluyen razonamiento interno del LLM, prompts ni secretos; solo
qué hace, con qué datos del proyecto y su resultado.

### 6.2 Contrato de polling

```
GET /api/v1/conversations/{conversation_id}/agent-events?after={seq}&limit=100
200 {
  "events": [ ... ordenados por seq ... ],
  "next_after": 42,
  "active_run": { "id", "status", "current_step", "plan", "pending_question" } | null,
  "poll_after_ms": 1500
}
```

- `after` ausente → últimos `limit` eventos (para hidratar la vista).
- El cliente deduplica por `seq`; reintentos son idempotentes.
- `poll_after_ms`: 1500 con run en `running`; 5000 en `waiting_calculation`; sin
  polling en `waiting_user` o sin run activo (el siguiente mensaje lo reactiva).
- Autorización igual que `chat_routes.owned_project`.
- Se complementa el endpoint de mensajes con `GET .../messages/since?after={message_id}`
  para no recargar los 50 últimos en cada tick (hoy `messages/first` cada 1,5 s).

### 6.3 SSE para la respuesta lista

El progreso fino va por polling; la **respuesta lista** (mensaje final del agente o una
pregunta) también se puede recibir por Server-Sent Events, para mostrarla al instante
sin esperar al siguiente tick:

```
GET /api/v1/conversations/{conversation_id}/agent-stream?run_id={opcional}&wait={1..300}
Last-Event-ID: {id del último mensaje recibido}   (opcional)

event: message.ready      id: {message_id}    data: {mensaje del agente}
event: run.idle                               data: {"run_id", "status"}   → cierra
event: timeout                                data: {"run_id", "status"}   → cierra; el cliente reconecta
: ping                                        (cada 15 s)
```

- Sin `run_id` sigue el run activo o, si no hay, el último.
- Cierra cuando el run termina o queda en `waiting_user`; un mensaje nuevo del usuario
  abre otro stream.
- El navegador debe leerlo con `fetch` + `ReadableStream`: `EventSource` no permite
  enviar el token bearer.
- Hoy el servidor consulta la BD cada segundo por conexión abierta; si el número de
  conexiones crece se cambia a Redis pub/sub sin cambiar el contrato.

### 6.4 Otros endpoints


| Método | Ruta | Acción |
|---|---|---|
| `GET` | `/api/v1/conversations/{id}/messages/since?after={message_id}` | Mensajes nuevos para polling incremental |
| `GET` | `/api/v1/agent-runs/{run_id}` | Estado completo del run |
| `POST` | `/api/v1/agent-runs/{run_id}/cancel` | Cancelar (FA-3) |
| `POST` | `/api/v1/agent-runs/{run_id}/resume` | Reanudar tras `failed` reanudable (FA-8) |
| `POST` | `/api/v1/agent-runs/{run_id}/proposals/{proposal_id}/approve` · `/reject` | Modo asistido |
| `GET`/`PUT` | `/api/v1/conversations/{id}/agent-state` | Ver/cambiar artefacto activo y modo |

## 7. Subagentes

Arquitectura **orquestador + especialistas**. Cada subagente es un bucle ReAct acotado
(reutiliza `_run_tool_agent`) con su propio prompt Langfuse, su propio subconjunto de
herramientas y una herramienta final que devuelve un resultado estructurado.
**Los subagentes no escriben el artefacto:** devuelven propuestas (parches tipados +
justificación + evidencia); solo el orquestador las aplica al borrador.

| # | Subagente | Responsabilidad | Herramientas | Salida | Fase |
|---|---|---|---|---|---|
| 0 | **Orquestador** | Interpreta intención y alcance, elige modo, arma y ajusta el plan, delega, aplica propuestas, gestiona preguntas, hace commit y redacta la respuesta | Todas las de estado del run, `ask_user`, `notify`, edición del borrador, `commit_version`, invocar subagentes | Plan, versiones, respuesta final | MVP |
| 1 | **Recolector de datos de entrada** | Reúne los parámetros de diseño desde la conversación, el grafo (afirmaciones aceptadas) y los archivos; detecta faltantes, contradicciones y valores sin confirmar | `get_artifact`, `search_knowledge_claims`, `get_claim`, `list_project_files`, `read_document_segment`, `list_open_questions` | Parches a `fault`, `soil_measurements`, datos del sitio; lista de faltantes y preguntas; cada valor con su fuente | MVP |
| 2 | **Modelador de suelo** | Ajusta mediciones Wenner/Schlumberger, elige número de capas (compara RMS y uncertainty entre 2..N), justifica la elección | `fit_soil_measurements`, `get_artifact` | Parche a `soil_layers` con RMS, incertidumbre, advertencias | MVP |
| 3 | **Diseñador de malla y conductor** | Propone/ajusta geometría (dimensiones, retícula, profundidad, varillas) y conductor (material, sección, unión, t_c) con dimensionamiento térmico | `get_artifact`, `thermal_size_conductor`, `estimate_grid_quick` (estimación cerrada IEEE 80 para prefiltrar, etiquetada como no trazable), `get_calculation` | Parches a `geometry` y `conductor` con justificación | MVP |
| 4 | **Analista de seguridad** | Lanza el cálculo trazable, interpreta R, GPR, contacto y paso frente a tolerables, identifica la restricción dominante y recomienda la siguiente acción | `request_potential_calculation`, `get_calculation`, `list_calculations` | Diagnóstico estructurado: cumple/no cumple por criterio, márgenes, recomendación | MVP |
| 5 | **Revisor normativo** | Actualiza la sección `compliance` con evidencia (id de cálculo, versión, valores) y notas; marca `pending`/`non_compliant`; `compliant` solo con cálculo trazable que lo respalde | `get_artifact`, `get_calculation`, `update_compliance_criterion` | Parches a `compliance` | MVP (sin RAG); con citas cuando exista BL-22 |
| 6 | **Optimizador** | Genera alternativas (retícula, varillas, gravilla) bajo restricciones y presenta frontera costo/margen | Las del 3 y 4 + BOM | Alternativas comparadas; el usuario elige cuál se vuelve versión | Fase 2 (depende de BL-20) |
| 7 | **Redactor de memoria** | Genera el resumen técnico/memoria con entradas, ecuaciones, fuentes, versiones de norma | Lectura de artefacto y cálculos | Documento | Fase 2 (depende de BL-21) |

Bucle de diseño (modo autónomo, solicitud total):
`1 Recolector → 2 Suelo → 3 Diseñador → 4 Seguridad → (no cumple y quedan iteraciones) → 3 → 4 … → 5 Revisor → respuesta`.

Decisión de diseño: se usan especialistas porque cada uno necesita un prompt, un
contexto y unas herramientas distintas, y así se acota lo que el LLM puede tocar. El
orquestador **no** llama al motor ni hace aritmética de ingeniería; toda cifra sale de
una herramienta determinista.

## 8. Herramientas sobre el artefacto

Todas las herramientas se implementan como funciones deterministas en el backend,
autorizadas con el actor del run, y registran `tool.called` cuando son relevantes.

### Lectura

| Herramienta | Descripción |
|---|---|
| `get_artifact(version?)` | Snapshot del borrador (por defecto) o de una versión |
| `list_artifact_versions()` | Versiones con origen (usuario/agente) y resumen |
| `diff_versions(a, b)` | Diferencias por campo |
| `get_missing_inputs()` | Validación determinista: qué falta o está fuera de rango para calcular |
| `list_calculations(version?)` / `get_calculation(id)` | Resultados y trace |
| `list_project_files()` / `read_document_segment()` / `search_document()` | Reutiliza las de `document_agents.py` |
| `search_knowledge_claims(attribute?, entity?)` / `get_claim(id)` | Grafo; distingue `accepted` de `proposed` |

### Escritura sobre el borrador (solo orquestador)

| Herramienta | Descripción |
|---|---|
| `apply_patch(ops, reason, sources)` | Parche sobre rutas permitidas (`/geometry/*`, `/soil_layers`, `/soil_measurements`, `/fault/*`, `/conductor/*`, `/compliance/*`, `/name`). Valida tipos y rangos con el esquema; rechaza rutas no permitidas. Cada op guarda motivo y fuente (mensaje, claim, cálculo o «supuesto aceptado») |
| `validate_draft()` | Valida con `GroundingArtifactRequest` y reglas de coherencia (p. ej. radio↔sección) |
| `propose_changes(summary)` | Modo asistido: congela el diff actual como propuesta y suspende hasta aprobación |
| `commit_version(summary)` | Crea versión nueva con concurrencia optimista sobre `base_version` |
| `discard_draft()` | Vuelve a `base_version` |

### Cálculo (deterministas existentes)

| Herramienta | Envuelve |
|---|---|
| `fit_soil_measurements(array, measurements, layer_count)` | `fit_two_layer` / `fit_n_layer` |
| `thermal_size_conductor(...)` | `conductor_thermal.calculate_thermal_size` |
| `request_potential_calculation(version, parameters)` | Mismo flujo que el endpoint; suspende el run hasta terminar |
| `update_compliance_criterion(standard, criterion, status, evidence, notes)` | Parche validado; `compliant` exige `evidence.calculation_id` existente y cuyo criterio lo respalde |

### Conversación y control

| Herramienta | Descripción |
|---|---|
| `ask_user(question, options?, field?)` | Crea pregunta, evento y mensaje; suspende en `waiting_user` |
| `notify(title, detail?, progress?)` | Evento de progreso |
| `record_assumption(field, value, accepted_in_message)` | Guarda supuesto en la memoria de conversación |
| `delegate(subagent, task, context)` | Solo orquestador |

## 9. Reglas y requisitos no funcionales

1. **No alucinar datos de ingeniería:** todo número del artefacto tiene fuente
   trazable (mensaje del usuario, claim aceptado, resultado de herramienta o supuesto
   aceptado). Los parches sin fuente se rechazan.
2. **Datos críticos** (`fault.current_a`, `fault.clearing_time_s`, capa superficial,
   resistividades del suelo) nunca toman valores típicos; si vienen de documentos o
   claims `proposed` requieren confirmación del usuario antes del commit. Los no
   críticos admiten valores típicos como supuesto (§13, decisión 4).
3. **Inmutabilidad:** el agente nunca borra versiones ni edita una existente.
4. **Límites por run** (configurables por entorno): rondas LLM por subagente (10),
   pasos por run (20), cálculos de potencial (5), iteraciones de diseño (3), tokens
   (descontados de `budget.used_tokens`), duración total (30 min de trabajo activo).
5. **Idempotencia:** `agent_run_step` es seguro ante reentrega (`task_acks_late=True`):
   cada paso tiene id y estado; un paso ya completado no se repite; los commits
   usan `base_version`; los eventos se insertan con id determinista por paso.
6. **Observabilidad:** cada run es una traza Langfuse con spans por subagente y
   herramienta; `run_id` en logs; nombre y versión de cada prompt guardados en el run.
7. **Seguridad:** prompt injection desde documentos — el contenido de archivos y
   claims se pasa como datos delimitados, nunca como instrucciones; las herramientas
   validan permisos y rutas en backend sin confiar en el LLM.
8. **Idioma:** respuestas, eventos y preguntas en español; unidades SI.
9. **Disponibilidad:** sin LLM configurado el chat sigue funcionando con un mensaje
   explícito de agente no disponible (comportamiento actual del placeholder).

## 10. Ubicación en la arquitectura

```
backend/src/domain/agent/
    run.py            # AgentRun, RunStatus, transiciones válidas
    events.py         # AgentEvent, catálogo de tipos
    patches.py        # rutas permitidas, ArtifactPatch, reglas de fuente/criticidad
backend/src/application/ports/
    agent.py          # LLMAgentRuntime, AgentRunRepository, AgentEventSink,
                      # ArtifactRepository, CalculationGateway
backend/src/application/use_cases/
    grounding_design_agent.py   # orquestación: paso a paso, reanudación, límites
backend/src/infrastructure/agents/
    runtime.py        # cliente OpenAI-compatible + Langfuse (extraer de document_agents)
    tools.py          # implementación de herramientas §8
    subagents.py      # definición de subagentes: prompt, herramientas, salida
backend/src/infrastructure/entrypoint/api/agent_routes.py
backend/src/infrastructure/entrypoint/worker/tasks.py   # spat.agent_run_step; resolve_chat_message crea el run
backend/migrations/versions/0010_agent_runs.py           # agent_runs, agent_events, agent_conversation_state,
                                                         # origin en artefacto_diseno_tierras
prompts/langfuse/agent-orchestrator.md, agent-input-collector.md, agent-soil-modeler.md,
                 agent-grid-designer.md, agent-safety-analyst.md, agent-compliance-reviewer.md
app/src/components/ProjectChatWorkspace.jsx               # timeline de eventos, preguntas, propuestas
```

El patrón actual de `artifact_routes.py` (lógica en la ruta) se evita para el agente:
la orquestación vive en el caso de uso y las rutas solo autorizan y delegan.

## 11. Criterios de aceptación (verificables con LLM falso guionizado)

1. Enviar un mensaje crea, en la misma transacción, el `chat_message` y un `agent_run`
   `queued`; el polling devuelve `run.started` en menos de 3 s con el worker activo.
2. Con un segundo mensaje durante un run activo no se crea otro run; el mensaje
   aparece en `inbox` y el orquestador lo procesa en el siguiente punto de control.
3. El polling con `after=N` devuelve solo eventos con `seq > N`, en orden, sin huecos
   ni duplicados ante reintentos de la tarea.
4. Un run que encola un cálculo libera el worker (`waiting_calculation`) y se reanuda
   automáticamente al completarse el cálculo; si el cálculo falla, emite
   `calculation.failed` y el agente lo explica.
5. En modo asistido ninguna versión se crea sin aprobación; en modo autónomo cada
   commit genera `artifact.version_created` con `origin.run_id`.
6. Un parche sin fuente, fuera de rutas permitidas o inválido para el esquema se
   rechaza y el LLM recibe el error; el artefacto no cambia.
7. Un dato crítico tomado de un claim `proposed` dispara `ask_user` antes del commit;
   un dato crítico con procedencia `schema_default` cuenta como faltante y bloquea el
   cálculo; un parche que pone un valor típico en un campo crítico se rechaza.
8. `update_compliance_criterion(status="compliant")` sin cálculo trazable que lo
   respalde se rechaza.
9. Si otra versión se crea durante el run, `commit_version` falla por concurrencia y
   el agente reintenta sobre la nueva base sin perder cambios ajenos.
10. Cancelar detiene el run, cancela su cálculo pendiente y conserva versiones ya creadas.
11. Al agotar límites el run termina con resumen de lo hecho y lo pendiente.
12. Caso de punta a punta (fixture con mediciones Wenner, Ik, t_s y área): en modo
    autónomo produce una versión con suelo ajustado, malla, conductor dimensionado,
    cálculo completado y `compliance` actualizado con evidencia.

## 12. Backlog de implementación

| Id | Prioridad | Tarea | Criterio | Dependencias |
|---|---|---|---|---|
| AG-01 | P0 · ✅ | Dominio del run y eventos | Máquina de estados con transiciones válidas y pruebas; catálogo de eventos | — |
| AG-02 | P0 · ✅ | Migración 0010 y repositorios | Tablas `agent_runs`, `agent_events` (seq por conversación), `agent_conversation_state`, `origin` (con `provenance` por campo) en artefactos; prueba en SQLite y PostgreSQL | AG-01 |
| AG-03 | P0 · ✅ (falta `resume` y propuestas, van con AG-06/AG-08) | API de polling, SSE y control | Endpoints §6.2–6.4 con autorización; `messages/since`; criterios 1–3 | AG-02 |
| AG-04 | P0 · ◐ (runtime compartido y modelo por subagente; falta descontar `budget`) | Runtime LLM compartido | Extraer cliente/prompt/bucle ReAct de `document_agents.py` a `agents/runtime.py` sin romper la ingesta; modelo por subagente (§14) con respaldo en `LLM_MODEL`; contabilidad de tokens contra `budget` | — |
| AG-05 | P0 · ◐ (borrador, procedencia, validación, propuesta y versión; faltan herramientas de cálculo, documentos y grafo) | Herramientas del artefacto | §8 lectura, borrador, validación, procedencia por campo y regla de datos críticos, commit con concurrencia optimista; criterios 6–9 | AG-02 |
| AG-06 | P0 · ◐ (pasos reanudables, espera de usuario, cancelación; falta espera de cálculo y plan) | Orquestador reanudable | `spat.agent_run_step`, inbox, suspensión por cálculo y por pregunta, cancelación, límites; criterios 2, 4, 10, 11 | AG-03, AG-04, AG-05 |
| AG-07 | P0 · ◐ (orquestador, diseñador de malla y modelador de suelo; faltan recolector, seguridad y normativo) | Subagentes MVP 1–5 | Prompts Langfuse sincronizados (`sync_langfuse_prompts.py`), herramientas por subagente, salida estructurada; criterio 12 con LLM falso | AG-06 |
| AG-08 | P1 · ✅ | Modo asistido | Propuestas con diff, aprobar/rechazar; criterio 5 | AG-06 |
| AG-09 | P1 · ◐ (progreso en el chat, tarjeta de propuesta, vista de la malla; falta timeline completo y SSE en el cliente) | Frontend | Timeline de eventos del run, plan con pasos, preguntas con opciones, tarjetas de propuesta con diff, enlace a la versión creada, cancelar | AG-03, AG-08 |
| AG-10 | P1 | Confirmación de datos críticos | Integrar con la bandeja de BL-15; criterio 7 | AG-07, BL-15 |
| AG-11 | P1 | Evaluación | Conjunto de 15–20 conversaciones guionizadas con resultado esperado; métricas: tasa de cumplimiento alcanzado, parches rechazados, preguntas innecesarias, tokens por run; corre en CI con LLM falso y a demanda con el real | AG-07 |
| AG-12 | P2 | Optimizador (subagente 6) | Alternativas comparadas | BL-20 |
| AG-13 | P2 | Redactor de memoria (subagente 7) | Memoria con trazas | BL-21 |
| AG-14 | P2 | Revisor normativo con citas | Citas por sección/página | BL-22 |

## 13. Decisiones

### Tomadas (2026-10-06)

1. **Modo por defecto: `asistido`.** El usuario puede pasar a `autonomo` o `consulta`
   por conversación.
2. **Un artefacto activo por conversación.** `agent_conversation_state.artifact_id` se
   fija al primer run: si el proyecto no tiene artefacto, el agente propone crear uno;
   si tiene varios, pregunta cuál usar. Cambiarlo es una acción explícita del usuario
   (`PUT /agent-state`), nunca del agente.
3. **Modelos OpenAI de bajo costo**, configurables por subagente (ver §14).

4. **Valores típicos: solo para parámetros no críticos.** Un valor típico es un valor de
   referencia que no sale de los datos del proyecto sino de la práctica habitual o de
   los ejemplos de la norma.
   - **Críticos — exigen dato del proyecto:** `fault.current_a` (Ik), `fault.clearing_time_s`
     (t_s), resistividad del suelo (mediciones o `soil_layers`), resistividad y espesor de
     la capa superficial (`fault.surface_resistivity_ohm_m`, `fault.surface_thickness_m`).
     El agente nunca propone un valor típico para ellos: los toma de un mensaje del
     usuario, de un claim aceptado o de un documento confirmado por el usuario; si no
     existen, pregunta (`ask_user`) y no encola cálculos.
   - **No críticos — se permite valor típico como supuesto:** geometría inicial
     (profundidad 0,5 m, retícula, varillas de 2,4 m), conductor inicial (cobre 2/0 AWG,
     unión, temperatura máxima, ambiente), `t_c = t_s`, peso corporal 50 kg (criterio
     conservador de IEEE 80), X/R típico por nivel de tensión. Se proponen marcados como
     «supuesto», con su justificación, y quedan en la memoria de conversación con el
     mensaje en que el usuario los aceptó. En modo asistido la aceptación es la
     aprobación de la propuesta.
   - **Procedencia por campo:** como el esquema del artefacto rellena varios campos
     críticos con valores por defecto (p. ej. capa superficial 3000 Ω·m y 0,1 m), el
     agente no puede distinguir un dato real de un valor por defecto mirando el snapshot.
     Por eso cada versión guarda `origin.provenance`: mapa ruta → `{kind: user | claim |
     document | tool | assumption | schema_default, ref}`. `get_missing_inputs()`
     trata un campo crítico con `schema_default` (o sin procedencia, en versiones
     anteriores al agente) como faltante y obliga a confirmarlo.

5. **Aplicar y avisar (2026-10-06).** En modo asistido el agente crea la versión sin pedir
   aprobación. Cada cambio publica un mensaje `notification` con `payload.kind =
   "artifact.updated"` (artifact_id, version, previous_version, cambios, faltantes para el
   cálculo): es la bandera con la que el cliente recarga el artefacto y muestra la tarjeta
   «Se editó el artefacto», con **Deshacer** (`POST .../versions/{v}/restaurar`, que crea una
   versión nueva con el snapshot anterior) y **Ver artefacto**.
6. **Geometría primero (2026-10-06).** El artefacto puede guardarse sin suelo ni datos de
   falla; los datos críticos siguen sin aceptar valores típicos, y el cálculo de potencial
   responde 409 con la lista de faltantes mientras no estén.
7. **Retícula y varillas (2026-10-06).** Retícula regular con separación por eje
   (`conductor_spacing_x_m`, `conductor_spacing_y_m`) o conductores trazados
   (`geometry.conductors`); varillas por perímetro (`rods_count`), por patrón o en posiciones
   explícitas (`geometry.rods`), siempre tocando un conductor. El diseñador edita zonas con
   operaciones deterministas (`explode_grid`, `clip_zone`) en lugar de calcular coordenadas.

8. **Modelador de suelo y tabla de materiales (2026-10-06).** El subagente lee sondeos
   Wenner/Schlumberger pegados en el chat (cada número se verifica contra el texto del
   mensaje) o desde un CSV/XLSX del proyecto (el código extrae las columnas que el agente
   indica), convierte R a ρa si hace falta, ajusta 2–4 capas con `fit_sounding` y guarda
   `soil_measurements` y `soil_layers` (procedencia `tool`, con el RMS). La tabla
   `domain/spat/soil_materials.py` (IEC 60364-5-54 Anexo B e IEEE 80-2013 Tabla 8, rangos
   orientativos) se expone en `GET /api/v1/materiales-suelo` y alimenta la pestaña Modelo de
   suelo; un valor de la tabla solo entra al diseño si el usuario lo confirma. El artefacto
   también puede existir sin malla (el cálculo la exige).

### Abiertas

1. **SSE/WebSocket a futuro:** el contrato de eventos con `seq` permite añadir
   streaming sin cambiar el modelo; por ahora solo polling, según el requerimiento.

## 14. Modelos LLM

Proveedor OpenAI (cliente OpenAI-compatible existente). Se privilegia costo: el
trabajo numérico lo hacen las herramientas deterministas, así que el LLM solo
interpreta, decide la siguiente herramienta y redacta.

| Subagente | Modelo | Variable de entorno | Motivo |
|---|---|---|---|
| Orquestador | `gpt-5-mini` | `AGENT_ORCHESTRATOR_MODEL` | Planificación y uso de herramientas en varios pasos; redacta la respuesta |
| Recolector de datos | `gpt-5-mini` | `AGENT_INPUT_COLLECTOR_MODEL` | Lee documentos y cruza fuentes; un error aquí contamina todo el diseño |
| Modelador de suelo | `gpt-5-nano` | `AGENT_SOIL_MODELER_MODEL` | Llama al ajuste y compara RMS/incertidumbre; poco razonamiento |
| Diseñador de malla y conductor | `gpt-5-mini` | `AGENT_GRID_DESIGNER_MODEL` | Decide qué ajustar según la restricción dominante |
| Analista de seguridad | `gpt-5-nano` | `AGENT_SAFETY_ANALYST_MODEL` | Interpreta un resultado ya estructurado (cumple/no cumple, márgenes) |
| Revisor normativo | `gpt-5-nano` | `AGENT_COMPLIANCE_REVIEWER_MODEL` | Copia evidencia a criterios con reglas deterministas detrás |
| Resumen de memoria de conversación | `gpt-5-nano` | `AGENT_SUMMARY_MODEL` | Resumen rodante al cierre del run |

- Cada variable cae en `LLM_MODEL` si no está definida (hoy `gpt-4o-mini`), así el
  agente funciona sin configuración extra.
- Si un subagente en `nano` falla de forma recurrente en la evaluación (AG-11), se
  sube solo ese a `mini`; la decisión se toma con métricas, no a priori.
- El modelo y la versión del prompt de cada llamada quedan en el run y en Langfuse.
- Verificar disponibilidad y precio vigentes en OpenAI al implementar AG-04.
