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

El snapshot contiene `schema_version: "1.0"`, `name`, `geometry`, `soil_layers`, `soil_measurements`, `soil_model`, `fault`, `conductor` y `compliance`. El contrato ejecutable y versionado está en `backend/src/domain/spat/schemas/design-artifact-1.0.json`. Los campos desconocidos se rechazan en el snapshot y sus objetos tipados anidados; `soil_model` y `source` permanecen como objetos de extensión explícitos. Los escenarios se representan actualmente con un único objeto `fault` por versión del artefacto; escenarios alternativos se guardan como versiones independientes. Si no se envía `compliance`, se inicializan criterios pendientes para IEEE 80, IEC 61936-1, IEC 60364-5-54, IEEE 81 y RETIE. RETIE y las normas IEC se marcan con aplicabilidad condicional; la edición debe fijarse para la jurisdicción, alcance y fecha del proyecto.

Cada criterio contiene identificador, título, descripción, estado (`pending`, `compliant`, `non_compliant` o `not_applicable`), evidencia y notas. La sección sirve para registrar y revisar criterios; no emite una declaración de conformidad ni sustituye la revisión de un profesional competente.

Los resultados y trazas son documentos separados ligados a la versión exacta del artefacto. Sus contratos actuales están en `calculation-result-1.0.json` y `calculation-trace-1.0.json`. El diff del agente conserva su representación de lista de rutas modificadas y se valida contra `artifact-diff-1.0.json`. Alembic `0013_versioned_artifact_contracts` marca snapshots existentes como 1.0 y conserva resultados/trazas previos bajo el contrato de transición `0.legacy`, sin reescribir su contenido. Las incompatibilidades futuras deben añadir un esquema y una migración explícita entre versiones.
