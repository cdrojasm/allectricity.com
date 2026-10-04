# Autenticación, autorización y presupuesto

## Ejecutar exclusivamente en Docker

Requisito del host: Docker con Compose. No se requiere Python, pip, PostgreSQL,
Redis ni Celery instalados en la máquina.

```bash
make local-config   # crea .env con secretos aleatorios desde un contenedor
make local-up       # imagen, PostgreSQL, migración, API, Redis, worker, scheduler y frontend Nginx
make create-admin   # email y contraseña por prompt; sin contraseñas por defecto
make test           # tests en contenedor contra PostgreSQL exclusivo de pruebas
make lint           # análisis estático dentro del contenedor de pruebas
make smoke-auth     # prueba HTTP/Celery/SMTP real, con cuenta temporal desactivada al terminar
```

`make local-config` no sobrescribe un `.env` existente. Los secretos se generan
sin imprimirlos, con permisos 0600; el archivo está excluido de Git y del build.
`make local-down` detiene el despliegue y conserva los volúmenes.

Todos los contenedores tienen prefijo `grounding-design-ai-`, igual que las
imágenes propias, red y volúmenes. PostgreSQL/Redis no publican puertos al host.
Frontend y API: `http://localhost:3000`; Nginx sirve la UI y expone `/api/`,
`/docs`, `/openapi.json` y `/ready`. La API no publica un puerto de host.
Correo local: `http://localhost:18025` (Mailpit, captura mensajes sin enviarlos
a Internet). Cambiar `SPAT_FRONTEND_PORT` y `SPAT_MAIL_PORT` en `.env` si esos
puertos ya están ocupados.

## Arquitectura

`domain/identity.py`: principal y catálogo de permisos.
`application/ports/identity.py`: contratos de persistencia, JWT, password hash,
proveedor externo, cifrado y correo. Casos de uso separados para autenticación,
administración, presupuesto y entrega de correos. Los adaptadores residen en
`infrastructure/security`, `infrastructure/persistence` y el entrypoint worker.

`TokenProvider` encapsula emisión/verificación: hoy `HS256Tokens`. Google es otro
puerto, `ExternalIdentityProvider`: valida un ID token externo y emite una sesión
local. Para Cognito se implementa otro adaptador y se configura en el composition
root `security/container.py`; ni los casos de uso ni el frontend dependen de HS256.
Aceptar JWT de Cognito directamente requerirá además mapear el sujeto externo
al usuario/sesión local para conservar revocación y RBAC, no solo cambiar algoritmo.

## Flujos y contratos

Todos los endpoints siguientes tienen prefijo `/api/v1`. Las respuestas de API
llevan `Cache-Control: no-store`. La API no almacena tokens en cookies; recibe
`Authorization: Bearer <access_token>`. La UI usa autenticación local mediante
correo y contraseña, guarda el access token en `localStorage` y consulta
`/auth/me` al iniciar para validar la sesión. La UI de restablecimiento sigue
pendiente, incluido leer `#token=` en la página de restablecimiento.

| Método y endpoint | Entrada / comportamiento | Autorización |
|---|---|---|
| POST `/auth/login` | `email`, `password`; access JWT + refresh opaco | Público, limitado por IP/cuenta |
| POST `/auth/google` | `token`: ID token Google validado | Público, `GOOGLE_CLIENT_ID` requerido |
| POST `/auth/token` | `grant_type=client_credentials`, `client_id`, `client_secret` | Credencial M2M; sin refresh |
| POST `/auth/refresh` | `refresh_token`; rota el refresh | Posesión del refresh vigente |
| POST `/auth/revoke` | `all_sessions` (false por defecto) | Usuario autenticado; propias sesiones |
| GET `/auth/me` | Perfil, roles y permisos efectivos | Autenticado |
| GET `/auth/sessions` | Sesiones propias paginadas | Autenticado |
| DELETE `/auth/sessions/{id}` | Revocar una sesión propia | Autenticado |
| POST `/auth/forgot-password` | `email`; respuesta 202 genérica | Público, limitado por IP/cuenta |
| POST `/auth/reset-password` | `token`, `password`; 204 | Token de un solo uso |
| POST `/auth/change-password` | `current_password`, `password`; revoca sesiones | Autenticado, cuenta local |
| POST `/auth/clients` | `name`, `email`; entrega secreto M2M una sola vez | super_admin o M2M autorizado |
| POST `/auth/clients/{id}/rotate-secret` | Sustituye secreto y revoca sesiones | super_admin o M2M autorizado |
| GET, POST `/users` | Listar / crear cuenta local con rol viewer | users:read / users:write |
| GET `/users/{id}` | Perfil propio o administración | Propietario o users:read |
| PATCH, DELETE `/users/{id}` | Editar / desactivar, nunca borrado físico | users:write; cuentas privilegiadas requieren super_admin/M2M |
| GET `/permissions` | Catálogo conocido | super_admin o M2M autorizado |
| GET, POST `/roles` | Listar / crear rol y permisos | super_admin o M2M autorizado |
| GET, PUT, DELETE `/roles/{id}` | Leer / reemplazar / eliminar rol | super_admin o M2M autorizado |
| GET, POST `/user-roles` | Listar (`user_id` opcional) / asignar | super_admin o M2M autorizado |
| DELETE `/user-roles/{id}` | Retirar asignación; para cambiarla, retirar y asignar | super_admin o M2M autorizado |
| GET, POST `/budgets` | Listar bolsas propias / crear bolsa para usuario | budgets:read / super_admin o M2M |
| GET, PATCH `/budgets/{id}` | Saldo / nombre, límite, estado | Propietario con budgets:read / super_admin o M2M |
| GET, POST `/budgets/{id}/usage` | Libro de consumo / registrar débito | Propietario con budgets:read / super_admin o M2M |
| POST `/designs/assess`, GET `/designs/{id}` | Diseño existente, ahora protegido | designs:write / designs:read + propietario o privilegiado |

Las listas aceptan `limit` (1–100) y `offset`. La consulta de consumos admite
`project_id`. `/health`, `/ready`, `/docs` y `/openapi.json` son públicos.
Una nueva ruta privada sin política explícita hace fallar el arranque.

### JWT y sesiones

- HS256 fijo en el adaptador; nunca se elige algoritmo usando el header del token.
- Se verifica firma con `AUTH_JWT_SECRET`, `iss`, `aud`, `exp`, `iat`, `nbf`,
  `sub`, `sid`, `jti`, `kind` y `token_use=access`. Secret mínimo 32 bytes.
- Access: 15 minutos; sesión/refresh: 30 días de duración absoluta (configurables).
- Cada refresh se consume atómicamente y se sustituye por otro. Reutilizar uno
  consumido revoca su familia completa, también los JWT de acceso ya emitidos.
  El cliente debe serializar peticiones de refresh para evitar carreras legítimas.
- Refresh y reset se almacenan como SHA-256 de valores aleatorios de alta entropía.
  Contraseñas y secretos M2M se guardan con Argon2id.
- Se verifica actividad de usuario y sesión en base de datos en cada petición;
  los roles/permisos también se leen allí, no se confía en permisos del JWT.
- Logout, desactivación, cambio/reset de contraseña y rotación de secreto M2M
  invalidan las sesiones correspondientes. La rotación de secreto JWT invalida
  access tokens previos; revocar sesiones también si se trata de un incidente.

### Usuarios y roles

Tablas `users`, `roles`, `permissions`, `user_roles`, `role_permissions`.
El perfil incluye email, nombre, apellido, teléfono, locale, timezone, avatar,
estado, email verificado, tipo human/M2M, timestamps y datos IdP:
provider, subject, issuer, metadata. Contraseñas y metadata IdP interna no se
devuelven en el API. Email es único y se normaliza a minúsculas.

Roles semilla: `super_admin`, `m2m`, `user_admin`, `designer`, `viewer`.
Los roles semilla son inmutables; se pueden crear roles personalizados con el
catálogo de permisos. Solo super_admin o un principal de tipo M2M con rol `m2m`
puede alterar roles/asignaciones. No se puede asignar `m2m` a un humano ni eliminar
el último superadmin humano activo. Un user_admin no puede editar cuentas
privilegiadas. Bootstrap solo por CLI interactiva, una vez y sin endpoint público.

Google valida firma, emisor, expiración, audiencia/authorized party y correo
verificado con `google-auth`. Identidad estable: provider + `sub`, nunca email.
Una nueva cuenta Google recibe viewer; una coincidencia de email con otra cuenta
produce conflicto y requiere un flujo explícito de vinculación futuro.
No se guardan access/refresh tokens de Google. Las contraseñas de cuentas Google
se administran en Google, no mediante el reset local.

### Presupuesto y uso

`budget`: dueño (`user_id`), nombre, total de tokens, consumidos, estado y fecha.
`budget_usage`: bolsa, actor, proyecto, acción, modelo, input/output/total tokens,
fecha e idempotency_key única por bolsa. El libro es inmutable vía API.

```json
{
  "input_tokens": 800,
  "output_tokens": 200,
  "project_id": "north-substation",
  "action": "refine_ground_mesh",
  "model": "configured-model",
  "idempotency_key": "operation-unique-id"
}
```

Un reintento idéntico devuelve el mismo registro sin doble cobro; datos distintos
con la misma clave dan 409. El saldo y el evento se escriben en una transacción;
se rechazan valores negativos y sobregiros. Los usuarios consultan sus propias
bolsas; el consumo lo registra el worker/M2M o superadmin, no el cliente final.
`project_id` es una referencia externa: todavía no existe tabla de proyectos en
este scaffold. No se descuentan tokens ficticios al ejecutar cálculos SPAT:
el futuro adaptador LLM debe registrar su consumo real mediante este caso de uso.
Esto es contabilidad de consumo; reservar tokens antes de una llamada LLM es una
extensión pendiente si se necesita garantizar presupuesto antes del gasto externo.

### Reset y correo asíncrono

La solicitud genera un reset de 30 minutos, invalida resets previos y guarda en
la misma transacción un mensaje cifrado con una llave Fernet independiente del
secreto JWT. API responde 202 aun si la cuenta no existe o es de Google.
Un Celery Beat encola IDs pendientes cada 15 segundos; el worker descifra y envía
por SMTP. Redis no recibe el enlace ni la contraseña, solo el ID del mensaje.

El outbox sobrevive a caídas del broker. Hay lease de entrega, reintentos y descarte
de mensajes expirados/consumidos; el payload cifrado se limpia al terminar. SMTP
tiene semántica al menos una vez: una caída entre enviar y confirmar puede duplicar
un correo, pero ambos contienen el mismo token de un solo uso. `Message-ID` estable
facilita deduplicación. El enlace usa fragmento `#token=` para no poner el secreto
en logs HTTP. La UI deberá enviarlo mediante POST `/auth/reset-password`.

## Operación y portabilidad

Misma imagen para API, migración, worker y scheduler, con comandos distintos.
PostgreSQL/Redis/SMTP se reemplazan por servicios administrados vía variables.
Ejecutar migraciones antes de servir tráfico y una sola réplica de Beat. En
entornos no locales el reset exige HTTPS y SMTP exige STARTTLS. Inyectar secretos
desde el gestor de secretos de la infraestructura. `GOOGLE_CLIENT_ID` debe ser
el client ID autorizado de tu aplicación.

Las mutaciones críticas están serializadas con una fila de bloqueo transaccional
(`security_lock`), también entre réplicas. Es una implementación conservadora
correcta para este scaffold; antes de alto tráfico conviene pasar a locks por
sesión/bolsa y límites de tasa en el gateway. Los límites internos son persistentes
por IP/cuenta; configurar proxies de confianza explícitos si hay un balanceador.

Hay eventos de auditoría sin credenciales para autenticación, administración y
presupuestos. Planificar retención/purga de sesiones expiradas, tokens consumidos,
rate_limits y auditoría al definir operación productiva. Los diseños siguen en
memoria como antes; usuarios, sesiones, roles, presupuestos y outbox son persistentes.

Referencias de implementación:
[PyJWT](https://pyjwt.readthedocs.io/en/latest/api.html),
[Google ID tokens](https://developers.google.com/identity/sign-in/web/backend-auth),
[Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html).
