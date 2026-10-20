# Despliegue de SPAT en Railway

`docker-compose.yml` es el manifiesto de importación del despliegue actual. Railway no ejecuta Compose como un único proceso: al importarlo, cada entrada se convierte en un servicio con red privada automática.

Las tareas Celery están separadas por colas: `agent`, `documents`, `calculations`, `mail` y `render`. Cada worker escucha únicamente su cola, por lo que una extracción documental pesada no bloquea al agente ni a los cálculos.

## Orden recomendado

1. Importa `docker-compose.yml` en un proyecto vacío o crea los servicios equivalentes desde el repositorio.
2. Para producción, sustituye `postgres` y `redis` por los plugins administrados de Railway y conecta `DATABASE_URL` y `CELERY_BROKER_URL` mediante variables de referencia.
3. Añade volúmenes a Postgres, Neo4j y MinIO si mantienes esas imágenes; el manifiesto ya declara los cuatro volúmenes necesarios.
4. Genera dominio público únicamente para `frontend`. Configura el healthcheck de `api` como `/ready` y el de `potential-engine`/`ocr` como `/health`.
5. Carga `railway.env.example` como base y reemplaza todos los valores marcados `replace-*` por secretos reales.

## Imágenes reducidas

- `api`: runtime Python transaccional sin GCC, sin el binario C++ embebido, sin Chromium y sin dependencias LLM/documentales.
- `agent-worker`, `document-worker`, `calculation-worker`, `mail-worker`: imágenes Celery con colas y dependencias separadas.
- `render-worker`: runtime Python con Chromium, porque es el único proceso que renderiza PDFs.
- `potential-engine`: imagen propia con solo el binario C++ compilado, el entrypoint `solver_api` y Python slim. Expone `/v1/calculate` y `/v1/projects/{project_id}/calculate`; cada request ejecuta un proyecto completo y aislado.
- `frontend`: build Node multietapa y runtime Nginx con los estáticos compilados.

El motor mantiene el protocolo de cálculo existente por stdin/stdout internamente; API y worker lo consumen por `POST /v1/calculate`. En local se usa la misma topología para detectar temprano diferencias con Railway.

## Configuración Railway

Los `depends_on` sirven como documentación de dependencias para la importación; Railway no los aplica como Compose. La aplicación debe tolerar el arranque desordenado y reintentar conexiones. La configuración de cada servicio debe apuntar a su Dockerfile con `RAILWAY_DOCKERFILE_PATH` o `dockerfilePath`, y el servicio `api` debe exponer el puerto que Railway entregue en `$PORT`.
