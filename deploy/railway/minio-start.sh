#!/bin/sh
# Starts MinIO, waits until it answers, applies the same idempotent setup as the local minio-init, keeps serving.
set -eu
minio server /data --address ":${PORT:-9000}" --console-address ":9001" &
server=$!
until mc alias set local "http://127.0.0.1:${PORT:-9000}" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do sleep 1; done
for bucket in quarantine documents designs plantillas; do
  mc mb --ignore-existing "local/$bucket"
  mc anonymous set none "local/$bucket"
done
mc mirror --overwrite --remove /seed/plantillas-medicion local/plantillas
mc event add local/quarantine arn:minio:sqs::PRIMARY:webhook --event put --ignore-existing || \
  echo "minio-start: webhook event not added (check MINIO_NOTIFY_WEBHOOK_* variables)"
echo "minio-start: buckets ready"
wait "$server"
