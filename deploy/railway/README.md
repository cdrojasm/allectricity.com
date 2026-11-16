# Despliegue de SPAT en Railway

`docker-compose.yml` es el manifiesto de importación del despliegue actual. Railway no ejecuta Compose como un único proceso: al importarlo, cada entrada se convierte en un servicio con red privada automática.

Las tareas Celery están separadas por colas: `agent`, `documents`, `calculations`, `mail` y `render`. Cada worker escucha únicamente su cola, por lo que una extracción documental pesada no bloquea al agente ni a los cálculos.

## Despliegue con el CLI (piloto)

Desde la raíz del repositorio, con `railway login` hecho:

1. `sh deploy/railway/setup.sh [nombre]`: crea el proyecto, Postgres y Redis administrados, los servicios, los
   volúmenes de MinIO y Neo4j, los dominios públicos (frontend y MinIO) y todas las variables que no son
   secretas. Los procesos backend referencian los secretos del servicio `api` (`${{api.X}}`).
2. `sh deploy/railway/secrets.sh [.env]`: **lo corre el dueño de las credenciales.** Genera los secretos
   internos sin mostrarlos y copia LLM, Langfuse y SMTP desde el `.env` indicado.
3. `sh deploy/railway/deploy.sh [servicio ...]`: sube el código y lanza los builds.
4. Crear el primer `super_admin`: `railway ssh -s api python -m src.infrastructure.entrypoint.bootstrap_admin`
   (pide correo y contraseña; lo hace el dueño).

Cada imagen elige su proceso por variables, sin comandos de arranque en el panel: `WORKER_TARGET` (etapa del
worker), `SPAT_ROLE` (`api`, `scheduler` o `migrate`; el API aplica migraciones al arrancar con
`RUN_MIGRATIONS=true`), `BIND_HOST=::` para la red privada y `PORT`. MinIO crea sus buckets y el webhook al
arrancar (`minio-start.sh`), y el frontend genera su configuración de nginx con el DNS privado de Railway.

## Imágenes reducidas

- `api`: runtime Python transaccional sin GCC, sin el binario C++ embebido, sin Chromium y sin dependencias LLM/documentales.
- `agent-worker`, `document-worker`, `calculation-worker`, `optimizer-worker`, `mail-worker`: imágenes Celery con colas y dependencias separadas.
- `render-worker`: runtime Python con Chromium, porque es el único proceso que renderiza PDFs.
- `potential-engine`: imagen propia con solo el binario C++ compilado, el entrypoint `solver_api` y Python slim. Expone `/v1/calculate` y `/v1/projects/{project_id}/calculate`; cada request ejecuta un proyecto completo y aislado.
- `frontend`: build Node multietapa y runtime Nginx con los estáticos compilados.

El motor mantiene el protocolo de cálculo existente por stdin/stdout internamente; API y worker lo consumen por `POST /v1/calculate`. En local se usa la misma topología para detectar temprano diferencias con Railway.

## Configuración Railway

Los `depends_on` sirven como documentación de dependencias para la importación; Railway no los aplica como Compose. La aplicación debe tolerar el arranque desordenado y reintentar conexiones. La configuración de cada servicio debe apuntar a su Dockerfile con `RAILWAY_DOCKERFILE_PATH` o `dockerfilePath`, y el servicio `api` debe exponer el puerto que Railway entregue en `$PORT`.
