# Matriz de autorización por recurso

Auditoría de rutas API del 24 nov 2026. La política general exige autenticación y permiso;
esta matriz registra el control de pertenencia que se aplica además. Los controles de
`privileged` corresponden a `super_admin` o a principales M2M autorizados por la política.

| Recurso / rutas | Permiso base | Control de pertenencia o visibilidad | Pruebas de referencia |
|---|---|---|---|
| Proyectos: `GET/PATCH/DELETE /api/v1/projects/{project_id}` | Bearer válido | Dueño del proyecto o principal privilegiado (`project_record`) | `test_foreign_user_cannot_read_project_or_nested_resources` |
| Artefactos, versiones y cálculos: `/projects/{project_id}/artefactos-diseno-tierras/**` | `designs:read/write` | Cada handler comprueba proyecto dueño y consulta con `project_id` junto con `artifact_id`, versión o cálculo | `test_missing_artifact_version_is_not_queued`; prueba transversal |
| Archivos: `/api/v1/files/**` | `files:read/write` | Presign exige proyecto dueño; estado, descarga, preview, complete y retry buscan también `owner_id`; adjuntos de chat coinciden en owner y project | `test_foreign_user_cannot_read_project_or_nested_resources`; pruebas de carga y escaneo |
| Conversaciones y mensajes: `/projects/{project_id}/conversations`, `/conversations/{conversation_id}/**`, `/messages/{message_id}/cancel` | Bearer válido; escritura de diseño donde aplica | Conversación → proyecto dueño; archivo adjunto → dueño y proyecto; cancelar mensaje → conversación/proyecto dueño | `test_agent_routes.py` (acceso cruzado a conversación/run) y prueba transversal |
| Runs del agente: `/agent-runs/{run_id}`, `/conversations/{id}/agent-*` | Bearer válido; `designs:write` en mutaciones específicas | Run o conversación → proyecto dueño; el `run_id` debe pertenecer a la conversación indicada en streaming | `test_agent_state_and_authorization` |
| Trabajos asíncronos: `/api/v1/jobs/{job_id}` | Bearer válido | `owner_id` coincide, salvo acceso privilegiado explícito | `test_job_is_private_to_its_owner` |
| Estudios: `/projects/{project_id}/studies/**` | `designs:read/write` | Proyecto dueño y estudio consultado con `project_id` + `study_id` | `test_an_unavailable_public_study_says_why`; prueba transversal |
| Estudios públicos: `/api/v1/public/studies/{slug}` | Público por diseño | Slug opaco; visibilidad depende de publicado, no vencido/revocado y contraseña cuando corresponda. Nunca entrega `password_hash` | pruebas de estudio público y Argon2id en `test_study_payload.py` |
| Optimización: `/projects/{project_id}/optimizer-runs/**` | `designs:read/write` | Proyecto dueño; runs y alternativas se consultan por `project_id` y `run_id` | `test_topology_optimizer_routes.py` (proyecto con búsqueda activa, cancelación y aplicación) |
| Grafo documental: `/projects/{project_id}/knowledge-graph/**` | `files:read` o `designs:write` | Cada operación valida el proyecto antes de leer/escribir el grafo | `test_project_authorization_and_permissions` |
| Perfiles de restricciones | `designs:read/write` | Perfiles personales limitados a `owner_id`; catálogos compartidos requieren curador privilegiado; solo versiones revisadas son visibles y seleccionables | `test_constraint_profile_scopes.py` |
| Catálogo de materiales de proyecto | `designs:read/write` | Proyecto y elemento/versiones consultados conjuntamente; catálogo personal filtrado por dueño | rutas de catálogo y `test_foreign_user_cannot_read_project_or_nested_resources` |
| Suscripciones y licencias | Bearer válido | Suscripción/resumen/reembolso asociados al usuario actual; emisión, listado y revocación de licencias requieren principal privilegiado; códigos son de un solo uso | `test_subscriptions.py` (propiedad, revocación y canje) |
| Sesiones, usuarios y presupuestos | Bearer válido + permiso | Sesiones limitadas al usuario; lectura de otro usuario exige `users:read`; presupuestos y uso se filtran por `owner_id` salvo administrador | `test_revoke_all_and_session_ownership`, `test_budget_ownership_idempotency_and_audit` |
| Roles, clientes M2M y administración global | `privileged` o permiso administrativo | Rutas mutables exigen `users:write`, `roles:*` o privilegio; el middleware valida que cada handler declare autorización | `test_role_crud_and_constraints`, `test_m2m_flow_and_rotation`, `validate_endpoint_policies` |

Las rutas públicas de login, catálogo público, webhooks y estudios compartidos son excepciones
registradas explícitamente en `middleware.py`; el startup falla si una ruta API nueva no declara
política. Las pruebas no reemplazan una revisión de las reglas y roles reales de producción:
la configuración efectiva de identidades permanece bajo SEC-09.
