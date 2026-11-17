#!/bin/sh
# Sets the secrets of the Railway project. Run it YOURSELF (the owner of the credentials), after setup.sh:
#   sh deploy/railway/secrets.sh [path/to/.env]
# - Internal secrets (JWT, mail encryption, MinIO, Neo4j, service tokens) are generated here and never printed.
# - Third-party keys (LLM, Langfuse, SMTP) are copied from the given .env (default: ./.env); missing ones are
#   reported so you can set them with `railway variable set -s api KEY=...`.
# Values travel through stdin, so they do not appear in the process list or in the shell history.
set -eu
cd "$(dirname "$0")/../.."
ENV_FILE=${1:-.env}

put() { printf '%s' "$3" | railway variable set -s "$1" --skip-deploys --stdin "$2" >/dev/null; }
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
from_env() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 | sed 's/^"//; s/"$//' || true; }

put api AUTH_JWT_SECRET "$(rand 48)"
put api AUTH_MAIL_ENCRYPTION_KEY "$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
put api OCR_INTERNAL_API_TOKEN "$(rand 32)"
put api MINIO_WEBHOOK_AUTH_TOKEN "$(rand 32)"
put api STUDY_RENDER_TOKEN "$(rand 32)"
put minio MINIO_ROOT_USER "terra$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
put minio MINIO_ROOT_PASSWORD "$(rand 32)"
# The neo4j image turns every NEO4J_* variable into a server setting (NEO4J_PASSWORD → "PASSWORD", which makes
# it refuse to start), so the password lives in GRAPH_PASSWORD and NEO4J_AUTH references it.
put neo4j GRAPH_PASSWORD "$(rand 24)"
railway variable set -s neo4j --skip-deploys 'NEO4J_AUTH=neo4j/${{GRAPH_PASSWORD}}' >/dev/null

# A variable exported in this shell wins over the .env file (e.g. SMTP_* of a real provider).
value_of() { eval "exported=\${$1:-}"; [ -n "$exported" ] && printf '%s' "$exported" || from_env "$1"; }
missing=""
for key in LLM_API_KEY LLM_MODEL LLM_BASE_URL LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_BASE_URL \
           RESEND_API_KEY MAIL_FROM; do
  value=$(value_of "$key")
  if [ -n "$value" ]; then put api "$key" "$value"; else missing="$missing $key"; fi
done
# The local stack mails to Mailpit: never copy a local SMTP host to production.
smtp_host=$(value_of SMTP_HOST)
case "$smtp_host" in
  ""|mailpit|localhost|127.0.0.1) [ -n "$(value_of RESEND_API_KEY)" ] || missing="$missing RESEND_API_KEY" ;;
  *) for key in SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM; do
       value=$(value_of "$key"); [ -n "$value" ] && put api "$key" "$value" || missing="$missing $key"
     done ;;
esac
put api LANGFUSE_PROMPT_LABEL "${LANGFUSE_PROMPT_LABEL:-production}"
put api SMTP_STARTTLS "true"

echo "Secretos internos generados y claves copiadas desde $ENV_FILE."
[ -z "$missing" ] || echo "Sin valor en $ENV_FILE (defínelos con railway variable set -s api KEY=...):$missing"
