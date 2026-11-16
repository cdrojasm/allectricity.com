#!/bin/sh
# Uploads the repository to every code service of the linked Railway project and starts the builds.
#   sh deploy/railway/deploy.sh [service ...]     (default: all)
set -eu
cd "$(dirname "$0")/../.."
SERVICES=${*:-"minio potential-engine ocr api scheduler agent-worker document-worker calculation-worker optimizer-worker mail-worker render-worker frontend"}
for service in $SERVICES; do
  echo "== $service"
  railway up -s "$service" --detach
done
# Image services pick up their variables on redeploy.
case " $SERVICES " in *" minio "*) railway service redeploy -s neo4j -y >/dev/null 2>&1 || true ;; esac
echo "Builds iniciados. Estado: railway service status --all   ·   Logs: railway logs -s <servicio>"
