# SPAT Design Agent

## React artifact workspace

The frontend is in `app/` (React + Vite), served by Nginx. The frontend
commands build static files into `app/dist`; start the API and Nginx together:

```bash
make frontend-up
```

Open `http://localhost:3001`. Nginx proxies `/api/`, `/docs`, `/openapi.json`
and `/ready` to the API service. The API is available through that Nginx
endpoint; its container port is not published directly on the host. Run
`make frontend-build` to build the static files without starting containers.
Stop only Nginx with `make frontend-down`.

The main page includes a navigation rail, project bar, asset list/graph,
multimodal chat composer, and collapsible mesh, potential, soil, design and
pricing sections. Mesh dimensions, spacing and rods are editable; selecting
a rod adds chat context. Save and restore design versions or export a JSON
snapshot. Layouts adapt to desktop, tablet and mobile screens.

This is a frontend prototype: chat replies and the potential chart are demo
content, and initial files are reference metadata. File selection stages local
attachment metadata in chat; files are not uploaded or parsed. Voice uses the
browser's speech-recognition service where supported (microphone permission
required; the browser may process speech remotely). State lasts for the current
page session; export JSON to keep a snapshot. Engineering validation, backend
persistence, AI responses and CAD/report exports remain integration work.

See [app/README.md](app/README.md) for the frontend structure and integration points.

Scaffold hexagonal para un agente de diseño y validación de sistemas de puesta
a tierra. Conserva las dependencias hacia el interior:

```text
entrypoint/API -> application (use cases + ports) -> domain
                       ^
             infrastructure adapters
```

`POST /api/v1/designs/assess` fue retirado (responde HTTP 410) porque utilizaba
una aproximación de prefactibilidad sin trazabilidad. El flujo vigente crea un
artefacto de diseño en `/api/v1/projects/{project_id}/artefactos-diseno-tierras`
y encola su cálculo trazable en la ruta `.../{artifact_id}/versions/{version}/calculos-potencial`.

### Escenarios eléctricos en artefactos 2.0

Los artefactos `schema_version: "2.0"` describen `networks`, `electrodes` y sus conexiones explícitas. Una conexión puede ser un enlace equipotencial (`kind: "bond"`) o una resistencia concentrada (`kind: "resistor"`, con `resistance_ohm`). Para calcular varios casos sobre esa topología, envía en los parámetros:

```json
{
  "scenarios": [
    {"id": "falla-A", "injections_a": {"malla-norte": 1000, "varilla-1": -250}},
    {"id": "falla-B", "injections_a": {"malla-sur": 800}}
  ]
}
```

Las corrientes son valores firmados por entidad y escenario; deben incluir previamente el reparto de corriente y el factor de decremento que correspondan. El resultado incluye potencial de cada red/electrodo respecto a tierra remota, diferencias firmadas de potencial transferido, corrientes de conexiones, balance de corriente por grupo, y estimaciones de toque y paso sobre el raster accesible. Los máximos conjuntos todavía no usan el refinamiento local de SV-08. Se asume que las geometrías de entidades distintas comparten el mismo origen de coordenadas.

## Ejecutar en local

```bash
make local-config
make local-up
make create-admin
make test
```

La API queda disponible en `http://localhost:3001/docs` a través de Nginx, el
correo local en `http://localhost:3001/mailpit/` y las cargas de archivos pasan
por el mismo Nginx hacia MinIO. Solo Nginx publica un puerto del host; los demás
servicios permanecen en la red interna de Docker. Toda instalación de dependencias y ejecución de pruebas
se realiza dentro de Docker. Los contenedores, redes y volúmenes tienen prefijo
`grounding-design-ai-`. `make local-down` conserva los datos.

El backend incluye JWT HS256, refresh rotativo, revocación, RBAC, usuarios/roles,
clientes M2M, Google ID tokens, presupuesto de tokens y reset por Celery + SMTP.
Los endpoints de diseño ahora requieren Bearer token. Configurar `GOOGLE_CLIENT_ID`
para habilitar Google. El frontend demo todavía no integra estos flujos.
Contratos, permisos y operación: [docs/AUTH.md](docs/AUTH.md).

En despliegue, Celery se divide por responsabilidad: `agent-worker` coordina los
agentes y el LLM, `document-worker` procesa archivos y OCR, `calculation-worker`
ejecuta cálculos contra `solver-api`, `optimizer-worker` atiende en su propia cola
las búsquedas del optimizador (largas, para que no bloqueen los cálculos), `render-worker` reserva Chromium para PDFs
y `mail-worker` atiende el correo transaccional. El API HTTP conserva solo la
frontera transaccional y publica trabajos en las colas correspondientes.

El backlog priorizado y el plan de despliegue portable están en
[docs/BACKLOG.md](docs/BACKLOG.md).

## Carga de archivos

La API crea cargas con `POST /api/v1/files/presign` (Bearer token con
`files:write`). Envía `filename`, `mime_type` y `category` (`documents` o
`designs`). La respuesta incluye un PUT URL válido por 15 minutos; usa ese URL
para subir el contenido directamente a MinIO. El evento `ObjectCreated` del
bucket `quarantine` pone el archivo en la cola de Celery. También se puede
llamar `POST /api/v1/files/{upload_id}/complete` como reintento manual.
Consulta `GET /api/v1/files/{upload_id}` para ver el estado.

Los objetos esperan en el bucket privado `quarantine`. El worker valida el MIME
detectado en los bytes y pasa el contenido por ClamAV. Luego extrae texto de
PDF, CSV y XLSX; para PNG/JPEG consulta por HTTP el servicio OCR `ocr:8080`,
desplegado en un contenedor separado con Tesseract e inglés/español. Detecta
menciones iniciales de equipos, circuitos y parámetros eléctricos, y guarda
un grafo por proyecto en Neo4j: proyecto, documentos, activos eléctricos y
parámetros. Cada mención conserva el fragmento y la posición de origen; los
nodos repetidos se consolidan dentro del proyecto y mantienen evidencia por
documento. Las menciones provenientes de OCR conservan su indicador de revisión.
Al terminar, copia el archivo limpio a `documents` o `designs`. Esta extracción
usa reglas y OCR general, así que requiere revisión técnica; OCR de PDF
escaneados e interpretación de símbolos CAD quedan pendientes. En local, MinIO
se sirve a través de Nginx en `http://localhost:3001`; la consola de MinIO y
Neo4j quedan disponibles solo dentro de la red Docker. Los servicios se
comunican usando sus nombres DNS de Compose (`minio`, `neo4j`, `api`, etc.).
Configura `MINIO_WEBHOOK_AUTH_TOKEN`, `NEO4J_USER` y `NEO4J_PASSWORD` en `.env`. Ajusta
`MINIO_*` y `CLAMAV_*` en otros entornos. El límite local de carga es 20 MiB
(`UPLOAD_MAX_BYTES`).

### Plantillas de medición de resistividad

Las plantillas de campo (Wenner, Schlumberger, tres puntos y polo–dipolo, en XLSX
con instrucciones y fórmula de ρa, y en CSV separado por `;`) viven en el bucket
privado `plantillas` de MinIO (`MINIO_TEMPLATES_BUCKET`). `minio-init` las siembra
desde `resources/minio/plantillas-medicion/` con `mc mirror`, incluido el
`catalogo.json` que la API lee. `GET /api/v1/plantillas-medicion` lista el catálogo
y `GET /api/v1/plantillas-medicion/{id}/{xlsx|csv}` devuelve una URL firmada de 5
minutos; solo se firman archivos del catálogo. En la UI aparecen en la pestaña
**Mediciones** del proyecto. Para cambiarlas, edita
`scripts/generate_measurement_templates.py` y ejecuta `make templates`.

El servicio OCR expone `GET /health` y `POST /v1/ocr` (JSON con `image_base64` y
`language`). El worker lo consume mediante `OCR_SERVICE_URL`; en local apunta a
`http://ocr:8080`. Esta interfaz permite sustituir el contenedor por un adaptador
a un servicio administrado como AWS Textract sin acoplar Celery a su SDK.
El servicio calcula confianza media y proporción de palabras dudosas a partir
de Tesseract; recomienda revisión si la media es menor a 60%, más del 20% de las
palabras queda bajo 45%, o no reconoce palabras. Los umbrales se configuran con
`OCR_MIN_MEAN_CONFIDENCE`, `OCR_MAX_LOW_CONFIDENCE_RATIO` y
`OCR_LOW_WORD_CONFIDENCE`. La recomendación aparece en los archivos del proyecto.
Es una señal heurística, no una garantía de exactitud.

### Agentes documentales y prompts versionados

El worker de Celery puede ejecutar un extractor ReAct con herramientas de
búsqueda/lectura de líneas y un consolidador que compara los hallazgos, marca
conflictos y formula preguntas. Sus propuestas se validan contra citas literales
de la fuente y permanecen sujetas a revisión; el constructor las persiste en el
grafo junto con las preguntas y las versiones exactas de los prompts.

Los prompts de ejecución se leen desde una instancia autoalojada de Arize Phoenix
usando la etiqueta configurada en `PHOENIX_PROMPT_TAG` (por defecto `production`).
Cada versión del prompt también define `model_name`: ese es el modelo usado por el
agente que carga esa versión. Para cambiarlo, edita el modelo en Phoenix, guarda una
nueva versión y asigna `production`; se aplica después de la caché de hasta cinco minutos.
El cliente LLM sigue usando el proveedor y endpoint configurados en la aplicación.
Los archivos bajo `prompts/phoenix/` son semillas: configura `PHOENIX_ENDPOINT`
y, si la instancia lo requiere, `PHOENIX_API_KEY` en `.env`; ejecuta
`make sync-prompts` para crear nuevas versiones bajo la etiqueta `staging` y
promuévelas a `production` en Phoenix cuando estén revisadas. Sin acceso a Phoenix,
los agentes usan las semillas del repositorio como respaldo. Luego
configura `LLM_API_KEY` y `LLM_MODEL` (opcional: `LLM_BASE_URL` para una API
compatible); con `DOCUMENT_AGENTS_ENABLED=auto` se activarán cuando estén el
endpoint de Phoenix y las credenciales del proveedor LLM. Se pueden fijar
versiones individuales con `DOCUMENT_EXTRACTOR_PROMPT_VERSION` y
`DOCUMENT_CONSOLIDATOR_PROMPT_VERSION`. Usa `DOCUMENT_AGENTS_ENABLED=false`
para desactivarlos o `true` para exigirlos. Sin credenciales, Celery conserva la
ruta determinista de reglas y OCR.
