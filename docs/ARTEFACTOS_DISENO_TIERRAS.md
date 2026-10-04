# Artefactos de diseño de tierras

Los artefactos se almacenan en `artefacto_diseno_tierras`. Cada fila representa una versión inmutable y contiene el snapshot completo del diseño. El contador de versión se conserva aunque se elimine una versión, por lo que los números no se reutilizan. El borrado elimina únicamente la versión solicitada.

Todos los endpoints requieren autenticación. Se aplican los permisos `designs:read` y `designs:write`, además de la propiedad del proyecto (salvo roles privilegiados).

| Método | Ruta | Acción |
| --- | --- | --- |
| `POST` | `/api/v1/projects/{project_id}/artefactos-diseno-tierras` | Crear artefacto y su versión 1 |
| `GET` | `/api/v1/projects/{project_id}/artefactos-diseno-tierras` | Listar la última versión existente de cada artefacto |
| `GET` | `/api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}/versions` | Listar las versiones existentes |
| `GET` | `/api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}/versions/{version}` | Consultar una versión |
| `PUT` | `/api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}` | Crear una nueva versión con el snapshot enviado |
| `POST` | `/api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}/versions` | Crear una nueva versión con el snapshot enviado |
| `DELETE` | `/api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}/versions/{version}` | Borrar esa versión |

El snapshot contiene `name`, `geometry`, `soil_layers`, `fault` y `compliance`. Si no se envía `compliance`, se inicializan criterios pendientes para IEEE 80, IEC 61936-1, IEC 60364-5-54, IEEE 81 y RETIE. RETIE y las normas IEC se marcan con aplicabilidad condicional; la edición debe fijarse para la jurisdicción, alcance y fecha del proyecto.

Cada criterio contiene identificador, título, descripción, estado (`pending`, `compliant`, `non_compliant` o `not_applicable`), evidencia y notas. La sección sirve para registrar y revisar criterios; no emite una declaración de conformidad ni sustituye la revisión de un profesional competente.
