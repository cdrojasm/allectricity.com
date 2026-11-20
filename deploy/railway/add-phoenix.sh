#!/bin/sh
# One-time migration for an existing Railway project: add the authenticated Phoenix service.
# Run from the repository root after `railway link` points at the intended project/environment.
set -eu

railway add -s phoenix -i arizephoenix/phoenix:version-21.0.0
railway service link phoenix
railway volume add -m /data
railway domain -s phoenix -p 6006

set_vars() { service=$1; shift; railway variable set -s "$service" --skip-deploys "$@" >/dev/null; }
put() { printf '%s' "$3" | railway variable set -s "$1" --skip-deploys --stdin "$2" >/dev/null; }
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

set_vars phoenix "PORT=6006" "PHOENIX_PORT=6006" "PHOENIX_HOST=::" \
  "PHOENIX_ENABLE_AUTH=true" "PHOENIX_USE_SECURE_COOKIES=true" \
  "PHOENIX_WORKING_DIR=/data" "RAILWAY_HEALTHCHECK_PATH=/healthz"
put phoenix PHOENIX_SECRET "$(rand 48)"
put phoenix PHOENIX_ADMIN_SECRET "$(rand 48)"

# The API runs units of work too (study writer, plan vision, material assistant).
for service in api agent-worker document-worker; do
  set_vars "$service" "PHOENIX_ENDPOINT=http://phoenix.railway.internal:6006" \
    'PHOENIX_API_KEY=${{phoenix.PHOENIX_ADMIN_SECRET}}' "PHOENIX_PROMPT_TAG=production"
done

railway service redeploy -s phoenix -y
railway service redeploy -s api -y
railway service redeploy -s agent-worker -y
railway service redeploy -s document-worker -y
echo "Phoenix listo. Abre el dominio recién creado; primer ingreso: admin@localhost / admin (cambio obligatorio)."
