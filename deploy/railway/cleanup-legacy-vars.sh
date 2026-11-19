#!/bin/sh
# Removes variables the code no longer reads (OpenAI/LLM_*, Langfuse, SMTP once mail goes through Resend).
# Run it ONCE, after deploying the code that reads OPENROUTER_* (the previous code still needs LLM_*):
#   sh deploy/railway/cleanup-legacy-vars.sh
# Each delete may trigger a redeploy of that service; Railway keeps only the latest one.
set -eu
cd "$(dirname "$0")/../.."
SERVICES="api scheduler agent-worker document-worker calculation-worker optimizer-worker mail-worker render-worker"
LEGACY="LLM_API_KEY LLM_MODEL LLM_BASE_URL LANGFUSE_BASE_URL LANGFUSE_PROMPT_LABEL LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY"
SMTP="SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM SMTP_STARTTLS"

# Only names (and MAIL_PROVIDER, which is not a secret) are read back.
names() { railway variable list -s "$1" --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(' '.join(d) if isinstance(d, dict) else '')"; }
provider=$(railway variable list -s api --json | python3 -c "import json,sys; print(json.load(sys.stdin).get('MAIL_PROVIDER',''))")
targets=$LEGACY
if [ "$provider" = resend ]; then targets="$targets $SMTP"; else echo "MAIL_PROVIDER no es resend en api: se conservan SMTP_*"; fi

for service in $SERVICES; do
  present=" $(names "$service") "
  removed=""
  for key in $targets; do
    case "$present" in *" $key "*) railway variable delete -s "$service" "$key" >/dev/null && removed="$removed $key" ;; esac
  done
  echo "$service:${removed:- nada que borrar}"
done
