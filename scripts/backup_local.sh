#!/bin/sh
# Local backup of the three data stores and a non-destructive restore check.
#   scripts/backup_local.sh backup            → backups/<UTC stamp>/ with postgres.dump, minio-data.tgz, neo4j-data.tgz
#   scripts/backup_local.sh verify [dir]      → restores postgres.dump into a temporary database, compares the table
#                                               row counts with the live database and drops it; checks the archives.
# PostgreSQL is dumped consistently (pg_dump). MinIO and Neo4j are copied from their volumes while running:
# good for a local stack; Neo4j Community has no online backup, and the graph can be rebuilt by reprocessing
# the documents. Production backups are described in docs/RUNBOOK.md.
set -eu

PG=grounding-design-ai-postgres
HELPER_IMAGE=grounding-design-ai-agent-worker   # already built locally; only used for its tar
cd "$(dirname "$0")/.."

backup() {
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  dir="backups/$stamp"
  mkdir -p "$dir"
  docker exec "$PG" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$dir/postgres.dump"
  for store in minio neo4j; do
    docker run --rm --user 0 --entrypoint tar -v "grounding-design-ai-$store-data:/data:ro" -v "$PWD/$dir:/backup" \
      "$HELPER_IMAGE" -czf "/backup/$store-data.tgz" -C /data .
  done
  (cd "$dir" && shasum -a 256 postgres.dump minio-data.tgz neo4j-data.tgz > SHA256SUMS)
  echo "Respaldo listo: $dir"
  ls -lh "$dir"
}

counts_sql="select string_agg(t.relname || '=' || t.n, ',' order by t.relname) from (
  select c.relname, (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %I', c.relname), false, true, '')))[1]::text as n
  from pg_class c join pg_namespace s on s.oid = c.relnamespace where s.nspname = 'public' and c.relkind = 'r') t;"

verify() {
  dir=${1:-$(ls -d backups/*/ 2>/dev/null | sort | tail -1)}
  dir=${dir%/}
  [ -n "$dir" ] && [ -f "$dir/postgres.dump" ] || { echo "No hay respaldo para verificar"; exit 1; }
  (cd "$dir" && shasum -a 256 -c SHA256SUMS)
  for archive in minio-data.tgz neo4j-data.tgz; do tar -tzf "$dir/$archive" > /dev/null; done
  scratch="restore_check_$(date +%s)"
  docker exec "$PG" sh -c "createdb -U \"\$POSTGRES_USER\" $scratch"
  trap 'docker exec "$PG" sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists '"$scratch"'" >/dev/null' EXIT
  docker exec -i "$PG" sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $scratch --no-owner --exit-on-error" < "$dir/postgres.dump"
  live=$(docker exec "$PG" sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"$counts_sql\"")
  restored=$(docker exec "$PG" sh -c "psql -U \"\$POSTGRES_USER\" -d $scratch -Atc \"$counts_sql\"")
  tables=$(echo "$restored" | tr ',' '\n' | grep -c .)
  if [ "$live" = "$restored" ]; then
    echo "Restauración verificada: $tables tablas con el mismo número de filas que la base viva ($dir)."
  else
    echo "La restauración difiere de la base viva (si hubo escrituras después del respaldo es esperable):"
    echo "$live" | tr ',' '\n' > /tmp/backup-live.$$; echo "$restored" | tr ',' '\n' > /tmp/backup-restored.$$
    diff /tmp/backup-live.$$ /tmp/backup-restored.$$ || true; rm -f /tmp/backup-live.$$ /tmp/backup-restored.$$
    exit 2
  fi
}

case "${1:-}" in
  backup) backup ;;
  verify) verify "${2:-}" ;;
  *) echo "Uso: $0 backup | verify [backups/<stamp>]"; exit 1 ;;
esac
