# Runbook de operación — Terra

Qué hacer para mantener el servicio y recuperarlo. Cada bloque dice si está **probado** (con fecha) o si es
**procedimiento sin probar** en el entorno indicado.

## 1. Estado del sistema

| Qué mirar | Dónde | Notas |
|---|---|---|
| Vida y base inicializada | `GET /health`, `GET /ready` | Healthchecks de Railway/Compose. |
| Componentes (PostgreSQL, MinIO, Redis, workers, ClamAV, OCR, motor) | `GET /api/v1/system/health`, tarjeta «Estado del sistema» | Requiere sesión. |
| Colas, trabajos en espera y en ejecución, alertas | `GET /api/v1/system/queues`, `GET /api/v1/system/metrics` (Prometheus) | Umbrales `QUEUE_DEPTH_WARN` (20) y `QUEUE_WAIT_WARN_S` (600 s). Un trabajo «en ejecución» más viejo que el límite del worker = worker muerto o estado huérfano. |
| Logs de un worker | `docker logs grounding-design-ai-<servicio>` (local) o logs del servicio en Railway | Los workers están separados por cola: `agent`, `documents`, `calculations`, `optimizer`, `mail`, `render`. |

## 2. Respaldos

### Local — probado (2026-11-16)

```bash
make backup-local     # backups/<UTC>/postgres.dump, minio-data.tgz, neo4j-data.tgz, SHA256SUMS
make backup-verify    # checksums, archivos legibles y restauración de PostgreSQL en una base temporal
make backup-verify BACKUP=backups/20261116T171912Z   # un respaldo concreto
```

`backup-verify` no toca la base viva: restaura el volcado en `restore_check_<n>`, compara el número de filas de
cada tabla con la base viva y la borra. Resultado del 2026-11-16: 37 tablas idénticas. `backups/` está en
`.gitignore`; los respaldos contienen datos de clientes y no deben subirse al repositorio.

PostgreSQL se vuelca de forma consistente (`pg_dump`). MinIO y Neo4j se copian desde sus volúmenes en caliente:
sirve para el stack local. Neo4j Community no tiene respaldo en línea; el grafo se puede reconstruir
reprocesando los documentos (procedimiento formal pendiente en EG-23).

### Restaurar sobre la base principal (local) — procedimiento sin probar

Destructivo: reemplaza los datos actuales. Hacer antes un `make backup-local`.

```bash
make local-down
docker compose --env-file .env -f deploy/local/docker/docker-compose.yml up -d postgres minio neo4j
docker exec -i grounding-design-ai-postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < backups/<stamp>/postgres.dump
for s in minio neo4j; do docker compose --env-file .env -f deploy/local/docker/docker-compose.yml stop $s;
  docker run --rm --user 0 --entrypoint sh -v grounding-design-ai-$s-data:/data -v "$PWD/backups/<stamp>:/backup:ro" \
    grounding-design-ai-agent-worker -c "rm -rf /data/* /data/.[!.]* && tar -xzf /backup/$s-data.tgz -C /data"; done
make local-up
make smoke-local
```

### Producción (Railway) — procedimiento sin probar, a configurar antes del piloto

1. PostgreSQL administrado de Railway: activar respaldos automáticos y comprobar la retención; hacer una
   restauración de prueba en un servicio aparte antes del primer usuario externo y anotar la fecha aquí.
2. MinIO (fuentes, PDF de estudios, logos): volumen con snapshot programado o réplica a un bucket S3 externo
   (`mc mirror`). Sin esto, un fallo del volumen pierde los documentos originales.
3. Neo4j: reconstruible desde los documentos; respaldar su volumen reduce el tiempo de recuperación.
4. Secretos: fuera del repositorio y de la imagen (BL-05); guardar una copia en el gestor de secretos del equipo.

## 3. Incidentes frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El agente contesta «No puedo seguir: tu bolsa de tokens…» | Bolsa agotada (o `AGENT_REQUIRE_BUDGET=true` sin bolsa) | Un `super_admin` amplía o asigna la bolsa en **Usuarios** o con `PATCH /api/v1/budgets/{id}`. |
| Un ingeniero no puede crear proyectos | Su cuenta solo tiene el rol `viewer` | Invitarlo desde **Usuarios** (asigna `designer`) o `POST /api/v1/user-roles`. |
| Un ingeniero no recibe el enlace de acceso | Correo mal configurado o worker `mail` caído | Producción: `MAIL_PROVIDER=resend`, `RESEND_API_KEY`, `MAIL_FROM` de un dominio verificado; logs del `mail-worker` (un fallo a los 20 s exactos = conexión bloqueada; Railway bloquea SMTP fuera de Pro). «Reenviar enlace» en **Usuarios**. Local: Mailpit en `/mailpit/`. |
| Corridas del agente en espera mucho tiempo | Worker `agent` caído o LLM sin respuesta | `/api/v1/system/queues`; reiniciar el worker; revisar `LLM_*`. |
| Logs con «Returning fallback prompt … label 'staging'» | `LANGFUSE_PROMPT_LABEL` apunta a una etiqueta sin prompts publicados | Usar `production` o publicar los prompts con `make sync-prompts` en esa etiqueta. Mientras tanto se usan los prompts locales. |
| El optimizador dice «Optimización bloqueada» | No hay perfil normativo revisado fijado al proyecto | Correcto mientras T0 siga abierto: solo un especialista puede publicar el perfil revisado. |
| Estudio público devuelve 404 | Proyecto borrado o estudio revocado/expirado | El diálogo de borrado ya lo advierte; republicar desde «Compartir estudio». |

## 4. Antes de cada despliegue

1. `make lint` y `make test` en verde (el CI de GitHub corre lo mismo en cada PR).
2. `make smoke-local` y `make smoke-ui` contra el stack local en verde.
3. `make backup-local` del entorno que se va a migrar (o respaldo manual en Railway) y anotar el nombre.
