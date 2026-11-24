# Backlog de seguridad y vulnerabilidades

Revisión estática del repositorio, 23 nov 2026. Este backlog separa defectos observados en código de controles que requieren confirmar la configuración del despliegue. No implica que los servicios publicados hayan sido probados.

## Orden de trabajo

| Id | Prioridad | Estado | Hallazgo / trabajo | Criterio de aceptación | Dependencias |
|---|---|---|---|---|---|
| SEC-01 | P0 | ✅ Código, migración y pruebas locales validados; release pendiente | **Hash de contraseñas de estudios compartidos.** `study_routes.py` crea hashes Argon2id, verifica hashes SHA-256 existentes y los rehashea al primer acceso correcto; las respuestas de gestión omiten `password_hash`. La migración `0026_study_argon2_hashes` amplía la columna. `docs/AUTH.md` documenta cambio de contraseña y revocación de enlace. Pruebas cubren upgrade, hash inválido y redacción. | Aplicar migración y desplegar; comprobar el comportamiento en producción después del release. | Release y verificación de SEC-01 |
| SEC-02 | P0 | ◐ Mitigación en código, pendiente de infraestructura | **Exposición del token de tarjeta en Celery/Redis.** El token ahora se cifra antes de pasar a Celery y el mensaje vence a los 180 s. El worker lo descifra solo para llamar a Mercado Pago; se conserva la clave de idempotencia. La migración `0027_scrub_billing_webhook_payloads` elimina cuerpos históricos de webhooks que ya no se necesitan. | Falta confirmar que el token no aparece en telemetría/logs, que Redis de producción exige TLS y ACL/autenticación con acceso de red limitado, y qué cifrado en reposo y retención ofrece el proveedor. | Confirmar configuración de Railway/Redis; revisión del flujo Mercado Pago |
| SEC-03 | P0 | ◐ Lock hash-verified y scan de dependencias en CI; faltan digests exactos | **Inventario reproducible de dependencias e imágenes.** `dependencies/uv.lock` y ocho exports por perfil fijan versiones y hashes; los Dockerfiles instalan con `pip --require-hashes`. `make security-lock-inventory` genera SBOM CycloneDX y reportes Grype; CI los escanea en cada PR/push y semanalmente y guarda artefactos por 90 días. El último escaneo halló 0 CVE en los ocho perfiles Python. Railway no entrega aquí SBOM de las doce imágenes propias por digest y capas de sistema. | Escanear y archivar SBOM por digest desplegado, incluyendo OS; definir política de bloqueo/excepciones y triage con responsable y vencimiento; mantener procedimiento de corrección. | Acceso a artefactos/digests Railway; política y responsable de triage |
| SEC-04 | P1 | ◐ Mitigación en código, pendiente de validación | **Límite de intentos en estudios protegidos por contraseña.** El endpoint aplica límites compartidos en base de datos por conexión remota y slug; los rechazos de acceso responden con el mismo estado/mensaje para slugs desconocidos, inválidos, vencidos o revocados. | Validar bloqueo y expiración entre réplicas; confirmar que la IP remota corresponde al cliente detrás del proxy; revisar resistencia a enumeración. | SEC-01; validación de SEC-04 |
| SEC-05 | P1 | ◐ Revisión de código y matriz documentadas; pruebas transversales parciales | **Autorización por objeto (IDOR/BOLA).** Los handlers revisados limitan recursos por `project_id`, `owner_id` y/o relación padre-hijo; la matriz por familia está en `docs/SECURITY_AUTHORIZATION_MATRIX.md`. Una prueba de dos usuarios verifica 11 rutas de lectura de proyectos y recursos anidados. Ya existían pruebas de acceso cruzado para jobs, runs, grafo, presupuestos y sesiones. | Completar casos de mutación, descarga, cancelación y borrado cruzados para cada familia; cubrir explícitamente roles privilegiados/M2M y probar la denegación por defecto. | Fixtures de dos usuarios/roles y cobertura por familia |
| SEC-06 | P1 | ◐ Cabeceras y límite de cuerpo configurados; validación del proxy pendiente | **Cabeceras y endurecimiento de la frontera web.** NGINX agrega HSTS (producción), `Referrer-Policy`, `Permissions-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, límite API de cuerpo de 1 MiB y timeout de 15 s; FastAPI desactiva Swagger/OpenAPI fuera de local/test. No se fijó CSP sin verificar los orígenes usados por el frontend y Mercado Pago. | Confirmar cabeceras y límites efectivos tras el proxy/CDN; definir CSP compatible; verificar HSTS solo cuando todos los hosts estén en HTTPS. | Inventario de dominios, recursos frontend y proxy de producción |
| SEC-07 | P1 | ◐ Límites base en código; inventario de rutas costosas incompleto | **Abuso y agotamiento de recursos.** NGINX limita API a 1 MiB y 15 s para completar el cuerpo; el webhook limita a 64 KiB; archivos se limitan por defecto a 20 MiB en procesamiento; OCR limita imagen a 20 MiB; preview PDF acota tamaño/render; Celery fija tiempos máximos por tarea. Falta consolidar frecuencia, concurrencia y presupuesto para cada ruta costosa y exponer métricas. | Matriz ruta × cuerpo × frecuencia × concurrencia × timeout × presupuesto; límites entre réplicas; respuestas controladas y métricas sin contenido sensible. | SEC-05; límites por usuario/proyecto y métricas |
| SEC-08 | P2 | ◐ Escaneo recurrente de dependencias listo; SLA y digest pendiente | **Verificación continua de CVE.** CI escanea ocho SBOM de locks por push, PR y cada lunes; conserva SBOM y reportes Grype por 90 días. `make security-rescan` vuelve a cotejar SBOM archivados con la base actual. Falta triage con responsables/SLA y escaneo de imágenes desplegadas por digest. | Alertas KEV/explotación activa con responsable y plazo; triage de aplicabilidad registrado; imágenes de producción y locks se reevalúan cuando cambien base, dependencias o exposición. | SEC-03; política de triage y responsables |
| SEC-09 | P2 | ⬜ Pendiente | **Revisión de secretos y elementos expuestos en despliegue.** Confirmar en Railway dominio, puertos, red privada, permisos de servicios, buckets MinIO, Phoenix, Neo4j, Redis, Postgres, salud y métricas. El análisis del repositorio no permite confirmar el estado efectivo de producción. | Checklist de producción con evidencia fechada: no hay puertos administrativos públicos; buckets son privados; secretos están solo en gestor de secretos y nunca en imágenes/logs; servicios internos usan credenciales únicas y privilegio mínimo; rotación/revocación está documentada; los endpoints de health no revelan datos internos. | Acceso de lectura a configuración de despliegue; responsable de infraestructura |
| SEC-10 | P2 | ◐ Pruebas locales parciales; sandbox de pagos pendiente | **Seguridad del flujo de webhooks y pagos.** Firma, deduplicación, relectura del recurso, cuerpo máximo de 64 KiB y descarte del JSON entrante están cubiertos en código; hay pruebas para cuerpo grande, datos persistidos, indisponibilidad del broker y fallos del worker. El checkout mantiene idempotencia y cifra el token con caducidad de cola. | Probar payload malformado y eventos fuera de orden; revisar reintentos y confirmación de crédito con Mercado Pago en entorno de prueba. | SEC-02; entorno de pruebas de Mercado Pago |

## Triage CVE inicial (23 nov 2026)

- Este bloque registra el triage previo al inventario directo de Railway que se agregó más abajo. El resultado posterior identifica coincidencias concretas de Python y las separa de las reconstrucciones locales.

## Reglas de cierre

- Cada SEC se cierra con cambio revisado, evidencia reproducible y actualización del estado aquí.
- Una excepción de CVE incluye paquete/versión/digest, razón de no aplicabilidad o mitigación, responsable y fecha de vencimiento.

## Validación local del trabajo actual

- `make lint`: correcto.
- `make test`: 1.023 pruebas aprobadas, 2 omitidas, con los locks Python activos.
- `make security-lock-inventory`: ocho SBOM de perfiles Python; Grype reportó 0 hallazgos críticos/altos/medios/bajos para todos. Reportes en `artifacts/security/locks-20261124T045147Z-1765d129beb2/`.
- `make local-build`: imágenes locales de API, workers, OCR y motor de potenciales construidas desde requirements fijados por hash.
- `make test TEST_ARGS='tests/infrastructure/test_agent_routes.py::test_foreign_user_cannot_read_project_or_nested_resources' TEST_WORKERS=1`: la prueba de acceso cruzado de 11 rutas pasó.
- La validación local no acredita la configuración de Railway ni que una corrección esté desplegada. SEC-02, SEC-04 a SEC-10 conservan dependencias externas o de cobertura adicionales.

## Inventario de imágenes (SEC-03)

Requiere Syft `1.57.2` y Grype `0.122.1`. Se pueden instalar en el host o ejecutarlos en Docker
con `SECURITY_DOCKER=true`; el target solo acepta digests inmutables por defecto y guarda resultados
bajo `artifacts/security/` (ignorado por Git):

```bash
make security-inventory SECURITY_IMAGES="api=registry/imagen-api@sha256:<digest> frontend=registry/imagen-frontend@sha256:<digest>"
make security-inventory SECURITY_DOCKER=true SECURITY_IMAGES="api=registry/imagen-api@sha256:<digest>"
make security-runtime-inventory
make security-rescan
```

Reemplaza cada referencia con el digest real del artefacto desplegado. `SECURITY_ALLOW_MUTABLE=true`
permite escaneos exploratorios por tag, pero el resultado los marca como no inmutables y no sirve
para certificar un release. `security-rescan` vuelve a cotejar cada CycloneDX guardado con la base
actual de Grype, que incorpora datos de proveedores y KEV. El escáner no sustituye la revisión de
versión afectada, parches retroportados, exposición del servicio ni falsos positivos; registra la
evidencia para ese triage.
- `make security-runtime-inventory` consulta por SSH `pip list --format=json` en diez servicios Python
  de producción, guarda sus versiones exactas y el deployment/digest informado por Railway, genera
  CycloneDX y corre Grype. **Ese SBOM cubre paquetes Python, no el sistema operativo de la imagen.**
- Ejecución del 24 nov 2026: Railway reportó 17 servicios. Cinco imágenes públicas se escanearon por
  digest exacto (`clamav`, `neo4j`, `phoenix`, `postgres`, `redis`); esos reportes suman 1.894
  coincidencias, 18 críticas y 247 altas al deduplicar CVE dentro de cada imagen. Los resultados
  requieren triage de aplicabilidad, aliases y parches retroportados.
- También se leyeron los paquetes instalados en los diez servicios Python (`api`, `scheduler`, los seis
  workers, `ocr`, `potential-engine`). Los snapshots están en `artifacts/security/runtime-20261124T032547621184Z-1765d129beb2/`
  y `artifacts/security/runtime-20261124T032729074467Z-1765d129beb2/`. En `api`, `scheduler` y
  `document-worker` el runtime reporta Pillow 12.3.0 y avisos críticos corregidos en 13.0.0. Se cambió
  la restricción a `pillow>=13,<14` en `dependencies/pyproject.toml` y en el Dockerfile OCR. El rebuild
  local confirmó Pillow 13.0.0 para API, scheduler, document worker y OCR; producción sigue en la
  versión anterior hasta que se despliegue.
- Las 12 imágenes propias de Railway se reconstruyeron localmente desde los Dockerfiles con las bases
  más recientes disponibles (`make local-build PULL=--pull`). Frontend y MinIO usan `docker build
  --pull` porque no hay un target de Make para esos Dockerfiles. El escaneo completo está en
  `artifacts/security/20261124T035700775122Z-1765d129beb2/`. **Son aproximaciones del árbol de trabajo
  actual y de las bases/dependencias resueltas al reconstruir, no los digests que Railway desplegó.**
  El inventario y sus límites están consolidados en
  `artifacts/security/production-inventory-summary.md` (artefacto ignorado por Git).
- Los builds locales salieron ARM64 por el host Apple Silicon. Se intentó `PLATFORM=linux/amd64`,
  pero Docker Hub agotó el tiempo al resolver `python:3.12-slim`; no se desactivó la verificación ni
  se reportó ese intento como build exitoso. Las alertas de paquetes del sistema en esos builds no
  equivalen a un inventario de la arquitectura desplegada.
- El runtime de frontend usaba Vite 6.4.3, marcado alto por npm. `npm audit fix --package-lock-only`
  actualizó el lockfile a 6.4.6; `npm audit` y `npm ci` reportaron cero vulnerabilidades. El último
  build local usó Vite 6.4.6 y el SBOM para paquetes de build está en
  `artifacts/security/20261124T035700775122Z-1765d129beb2/frontend-build.cdx.json`.
- Dos conexiones SSH iniciales avisaron que cambió la host key de Railway y fallaron. No se desactivó
  la verificación; reintentos normales de ambos servicios funcionaron. Revisar ese cambio de identidad
  antes de automatizar consultas SSH.
- Las pruebas de endpoints se ejecutan solo contra entornos locales o de prueba; los hallazgos de producción se validan primero mediante inventario/configuración de solo lectura.
