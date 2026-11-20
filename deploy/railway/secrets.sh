#!/bin/sh
# Sets the secrets of the Railway project. Run it YOURSELF (the owner of the credentials), after setup.sh:
#   sh deploy/railway/secrets.sh [path/to/.env]
# Safe to run again at any time:
# - Internal secrets (JWT, mail encryption, MinIO, Neo4j, Phoenix, service tokens) are generated ONLY when the
#   variable does not exist yet, so a re-run never logs users out or locks a service out of its data.
# - Third-party keys (OpenRouter, Resend, Mercado Pago) are copied from the given .env (default: ./.env) on every
#   run; empty ones are skipped and reported.
# - Backend services get references to the api's keys they need (they hold no copy of the secret).
# Values travel through stdin, so they do not appear in the process list or in the shell history.
set -eu
cd "$(dirname "$0")/../.."
ENV_FILE=${1:-.env}
BACKEND="scheduler agent-worker document-worker calculation-worker optimizer-worker mail-worker render-worker"

put() { printf '%s' "$3" | railway variable set -s "$1" --skip-deploys --stdin "$2" >/dev/null; }
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
from_env() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 | sed 's/^"//; s/"$//' || true; }
# Only variable NAMES are read back; values never leave Railway. If the listing fails the script stops:
# treating "could not read" as "missing" would regenerate (and rotate) a secret that already exists.
names_of() {
  railway variable list -s "$1" --json \
    | python3 -c "import json,sys; d=json.load(sys.stdin); assert isinstance(d, dict); print(' '.join(d))"
}
has() {
  if ! present=$(names_of "$1"); then
    echo "No pude leer las variables de '$1' en Railway; me detengo sin generar nada." >&2
    exit 1
  fi
  case " $present " in *" $2 "*) return 0 ;; *) return 1 ;; esac
}
created=""
put_once() { if has "$1" "$2"; then :; else put "$1" "$2" "$3"; created="$created $1.$2"; fi; }

put_once api AUTH_JWT_SECRET "$(rand 48)"
put_once api AUTH_MAIL_ENCRYPTION_KEY "$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
put_once api OCR_INTERNAL_API_TOKEN "$(rand 32)"
put_once api MINIO_WEBHOOK_AUTH_TOKEN "$(rand 32)"
put_once api STUDY_RENDER_TOKEN "$(rand 32)"
put_once minio MINIO_ROOT_USER "terra$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
put_once minio MINIO_ROOT_PASSWORD "$(rand 32)"
# The neo4j image turns every NEO4J_* variable into a server setting (NEO4J_PASSWORD → "PASSWORD", which makes
# it refuse to start), so the password lives in GRAPH_PASSWORD and NEO4J_AUTH references it.
put_once neo4j GRAPH_PASSWORD "$(rand 24)"
has neo4j NEO4J_AUTH || railway variable set -s neo4j --skip-deploys 'NEO4J_AUTH=neo4j/${{GRAPH_PASSWORD}}' >/dev/null
phoenix_before=$created
put_once phoenix PHOENIX_SECRET "$(rand 48)"
put_once phoenix PHOENIX_ADMIN_SECRET "$(rand 48)"
[ "$created" = "$phoenix_before" ] || railway service redeploy -s phoenix -y >/dev/null

# A variable exported in this shell wins over the .env file.
value_of() { eval "exported=\${$1:-}"; [ -n "$exported" ] && printf '%s' "$exported" || from_env "$1"; }
missing=""
for key in OPENROUTER_API_KEY OPENROUTER_MODEL \
           RESEND_API_KEY MAIL_FROM \
           MP_MODE MP_TEST_ACCESS_TOKEN MP_TEST_PUBLIC_KEY MP_TEST_WEBHOOK_SECRET \
           MP_PROD_ACCESS_TOKEN MP_PROD_PUBLIC_KEY MP_PROD_WEBHOOK_SECRET \
           MP_PLAN_NAMES MP_PLAN_IDS MP_TEST_PLAN_IDS MP_PROD_PLAN_IDS MP_PLAN_PRICES_USD MP_PLAN_MONTHLY_TOKENS; do
  value=$(value_of "$key")
  if [ -n "$value" ]; then put api "$key" "$value"; else missing="$missing $key"; fi
done
# Mail goes through Resend (Railway blocks outbound SMTP below Pro). SMTP is copied only from a real host
# explicitly exported in this shell or in the .env; a local Mailpit host is never copied to production.
smtp_host=$(value_of SMTP_HOST)
case "$smtp_host" in
  ""|mailpit|localhost|127.0.0.1) ;;
  *) for key in SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM; do
       value=$(value_of "$key"); [ -n "$value" ] && put api "$key" "$value" || missing="$missing $key"
     done
     put api SMTP_STARTTLS "true" ;;
esac
put api PHOENIX_PROMPT_TAG "production"

# References for the backend services (projects created before these keys existed need them too).
for service in $BACKEND; do
  railway variable set -s "$service" --skip-deploys \
    'OPENROUTER_API_KEY=${{api.OPENROUTER_API_KEY}}' 'OPENROUTER_MODEL=${{api.OPENROUTER_MODEL}}' \
    'MP_TEST_ACCESS_TOKEN=${{api.MP_TEST_ACCESS_TOKEN}}' 'MP_PROD_ACCESS_TOKEN=${{api.MP_PROD_ACCESS_TOKEN}}' \
    >/dev/null
done

echo "Claves externas copiadas desde $ENV_FILE. Secretos internos ya existentes: intactos."
[ -z "$created" ] || echo "Secretos internos creados ahora (no existían):$created"
[ -z "$missing" ] || echo "Sin valor en $ENV_FILE (no se subieron):$missing"
echo "Los cambios quedan en espera (--skip-deploys): se aplican en el próximo deploy."
