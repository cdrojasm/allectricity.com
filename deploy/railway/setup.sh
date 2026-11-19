#!/bin/sh
# Creates the Railway project for the free pilot: services, volumes, public domains and every NON-secret variable.
# Secrets are set separately by the owner with deploy/railway/secrets.sh; code is deployed with deploy.sh.
# Usage (from the repository root, after `railway login`):  sh deploy/railway/setup.sh [project-name] [workspace]
set -eu
cd "$(dirname "$0")/../.."
NAME=${1:-terra-piloto}
WORKSPACE=${2:-}

if [ -n "$WORKSPACE" ]; then railway init -n "$NAME" -w "$WORKSPACE"; else railway init -n "$NAME"; fi
railway add -d postgres
railway add -d redis
for service in api scheduler agent-worker document-worker calculation-worker optimizer-worker mail-worker \
               render-worker frontend potential-engine ocr minio; do
  railway add -s "$service"
done
railway add -s phoenix -i arizephoenix/phoenix:version-21.0.0
railway add -s neo4j -i neo4j:5.26-community
railway add -s clamav -i clamav/clamav-debian:1.4

# Persistent data.
railway service link minio && railway volume add -m /data
railway service link neo4j && railway volume add -m /data
railway service link phoenix && railway volume add -m /data

# Public domains: the web app, and MinIO for the browser's presigned uploads/downloads.
railway domain -s frontend -p 8080
railway domain -s minio -p 9000
railway domain -s phoenix -p 6006
FRONTEND=$(railway domain list -s frontend --json | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d if isinstance(d,list) else d.get("domains") or d.get("serviceDomains") or []; print((d[0].get("domain") if isinstance(d[0],dict) else d[0]))')
MINIO_HOST=$(railway domain list -s minio --json | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d if isinstance(d,list) else d.get("domains") or d.get("serviceDomains") or []; print((d[0].get("domain") if isinstance(d[0],dict) else d[0]))')
PHOENIX_HOST=$(railway domain list -s phoenix --json | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d if isinstance(d,list) else d.get("domains") or d.get("serviceDomains") or []; print((d[0].get("domain") if isinstance(d[0],dict) else d[0]))')
echo "frontend: https://$FRONTEND   minio: https://$MINIO_HOST   phoenix: https://$PHOENIX_HOST"

set_vars() { service=$1; shift; railway variable set -s "$service" --skip-deploys "$@" >/dev/null; }

# Values every backend process shares; secrets are references to the api service (set by secrets.sh).
DB='postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}'
backend_common() {
  set_vars "$1" \
    "SPAT_ENVIRONMENT=production" "DATABASE_URL=$DB" 'CELERY_BROKER_URL=${{Redis.REDIS_URL}}' \
    "MINIO_ENDPOINT=minio.railway.internal:9000" "MINIO_SECURE=false" \
    "PHOENIX_ENDPOINT=http://phoenix.railway.internal:6006" 'PHOENIX_API_KEY=${{phoenix.PHOENIX_ADMIN_SECRET}}' \
    "MINIO_PUBLIC_ENDPOINT=$MINIO_HOST" "MINIO_PUBLIC_SECURE=true" \
    'MINIO_ACCESS_KEY=${{minio.MINIO_ROOT_USER}}' 'MINIO_SECRET_KEY=${{minio.MINIO_ROOT_PASSWORD}}' \
    "NEO4J_URI=bolt://neo4j.railway.internal:7687" "NEO4J_USER=neo4j" 'NEO4J_PASSWORD=${{neo4j.GRAPH_PASSWORD}}' \
    "CLAMAV_HOST=clamav.railway.internal" "OCR_SERVICE_URL=http://ocr.railway.internal:8080" \
    "SPAT_POTENTIAL_ENGINE_URL=http://potential-engine.railway.internal:8080" \
    "PUBLIC_APP_URL=https://$FRONTEND" "AUTH_RESET_URL=https://$FRONTEND/reset-password" \
    "AUTH_JWT_ISSUER=spat-api" "AUTH_JWT_AUDIENCE=spat-workspace" \
    "DESIGN_MAX_ITERATIONS=3" "AGENT_REQUIRE_BUDGET=true" "AGENT_MIN_STEP_TOKENS=2000" \
    "MAIL_PROVIDER=resend"
  if [ "$1" != api ]; then
    set_vars "$1" \
      'AUTH_JWT_SECRET=${{api.AUTH_JWT_SECRET}}' 'AUTH_MAIL_ENCRYPTION_KEY=${{api.AUTH_MAIL_ENCRYPTION_KEY}}' \
      'OCR_INTERNAL_API_TOKEN=${{api.OCR_INTERNAL_API_TOKEN}}' 'MINIO_WEBHOOK_AUTH_TOKEN=${{api.MINIO_WEBHOOK_AUTH_TOKEN}}' \
      'STUDY_RENDER_TOKEN=${{api.STUDY_RENDER_TOKEN}}' \
      'LLM_API_KEY=${{api.LLM_API_KEY}}' 'LLM_MODEL=${{api.LLM_MODEL}}' 'LLM_BASE_URL=${{api.LLM_BASE_URL}}' \
      'PHOENIX_PROMPT_TAG=${{api.PHOENIX_PROMPT_TAG}}' \
      'SMTP_HOST=${{api.SMTP_HOST}}' 'SMTP_PORT=${{api.SMTP_PORT}}' 'SMTP_USERNAME=${{api.SMTP_USERNAME}}' \
      'SMTP_PASSWORD=${{api.SMTP_PASSWORD}}' 'SMTP_FROM=${{api.SMTP_FROM}}' 'SMTP_STARTTLS=${{api.SMTP_STARTTLS}}' \
      'RESEND_API_KEY=${{api.RESEND_API_KEY}}' 'MAIL_FROM=${{api.MAIL_FROM}}'
  fi
}

API_DF=deploy/local/docker/Dockerfile.api
WORKER_DF=deploy/local/docker/Dockerfile.worker
backend_common api
set_vars api "RAILWAY_DOCKERFILE_PATH=$API_DF" "SPAT_ROLE=api" "RUN_MIGRATIONS=true" "BIND_HOST=::" "PORT=8000" \
  "PHOENIX_PROMPT_TAG=production" \
  "RAILWAY_HEALTHCHECK_PATH=/ready"
backend_common scheduler
set_vars scheduler "RAILWAY_DOCKERFILE_PATH=$API_DF" "SPAT_ROLE=scheduler"
for worker in agent document calculation optimizer mail render; do
  backend_common "$worker-worker"
  set_vars "$worker-worker" "RAILWAY_DOCKERFILE_PATH=$WORKER_DF" "WORKER_TARGET=$worker-worker"
done

set_vars frontend "RAILWAY_DOCKERFILE_PATH=deploy/railway/Dockerfile.frontend" "PORT=8080" \
  "API_UPSTREAM=api.railway.internal:8000"
set_vars phoenix "PORT=6006" "PHOENIX_PORT=6006" "PHOENIX_HOST=::" \
  "PHOENIX_ENABLE_AUTH=true" "PHOENIX_USE_SECURE_COOKIES=true" \
  "PHOENIX_WORKING_DIR=/data" "RAILWAY_HEALTHCHECK_PATH=/healthz"
set_vars potential-engine "RAILWAY_DOCKERFILE_PATH=deploy/local/docker/Dockerfile.potential-engine" \
  "BIND_HOST=::" "PORT=8080"
set_vars ocr "RAILWAY_DOCKERFILE_PATH=deploy/local/docker/Dockerfile.ocr" "BIND_HOST=::" "PORT=8080" \
  'OCR_INTERNAL_API_TOKEN=${{api.OCR_INTERNAL_API_TOKEN}}'
set_vars minio "RAILWAY_DOCKERFILE_PATH=deploy/railway/Dockerfile.minio" "PORT=9000" \
  "MINIO_API_CORS_ALLOW_ORIGIN=https://$FRONTEND" \
  "MINIO_NOTIFY_WEBHOOK_ENABLE_PRIMARY=on" \
  "MINIO_NOTIFY_WEBHOOK_ENDPOINT_PRIMARY=http://api.railway.internal:8000/api/v1/files/events/minio" \
  'MINIO_NOTIFY_WEBHOOK_AUTH_TOKEN_PRIMARY=${{api.MINIO_WEBHOOK_AUTH_TOKEN}}' \
  "MINIO_NOTIFY_WEBHOOK_QUEUE_DIR_PRIMARY=/data/.minio-events"

echo "Listo. Siguiente paso (lo corre el dueño de las credenciales): sh deploy/railway/secrets.sh"
