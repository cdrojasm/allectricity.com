# Hoja de revisión experta — perfil RETIE Colombia para subestaciones c.a.

**Perfil bajo revisión:** `co.retie.substation_ac`, borrador v1
**Estado:** pre-revisión documental; no aprobado para declarar cumplimiento
**Fecha de preparación:** 2026-11-15
**Revisor competente:** ____________________  **Matrícula/credencial:** ____________________
**Fecha de revisión:** ____________________  **Firma/registro de aprobación:** ____________________

Esta hoja convierte los bloqueos de OP-20 en decisiones verificables. La lectura de fuentes oficiales sirve para preparar la revisión; no sustituye el juicio de un profesional competente ni confirma por sí sola la aplicabilidad al proyecto.

## Referencias consultadas

- Ministerio de Minas y Energía, página oficial del [RETIE](https://minenergia.gov.co/es/misional/energia-electrica-2/reglamentos-tecnicos/reglamento-t%C3%A9cnico-de-instalaciones-el%C3%A9ctricas-retie/). La página identifica la Resolución 40284 del 23 de junio de 2026 como modificación vigente publicada en cuatro libros. Confirmar en cada uso la fecha de diseño, régimen de transición y actos posteriores aplicables.
- [Libro 3 de la Resolución 40284 de 2026 (PDF oficial)](https://minenergia.gov.co/documents/15921/Libro-3-Resolucion-40284-23-06-2026.pdf).
- Perfil fuente: `substation_ac_retie_2026_draft.json`.
- Registro técnico del proyecto: `docs/BACKLOG_OPTIMIZADOR.md`, OP-20 y nota de fuentes.

## Decisiones que debe cerrar el revisor

| ID | Decisión requerida y evidencia base | Respuesta del revisor | Evidencia/cláusula validada | Estado |
|---|---|---|---|---|
| R1 | Confirmar edición RETIE aplicable según fecha de diseño, actos modificatorios y transición. Base consultada: Resolución 40284 (2026), Libro 3. |  |  | Pendiente |
| R2 | Delimitar alcance del perfil: tipo de subestación c.a., nivel de tensión, jurisdicción, acceso público/ocupacional y exclusiones. |  |  | Pendiente |
| R3 | Aprobar el método de contacto: Art. 3.12.1(g), Tabla 3.12.1.a. Confirmar fila/columna por exposición y despeje, y cuándo la tabla aplica sin capa superficial; documentar cómo se combina con IEEE 80 sin mezclar límites. |  |  | Pendiente |
| R4 | Aprobar el método y parámetros de paso bajo IEEE 80. La Tabla 3.12.1.a se describe como límite de contacto; confirmar expresamente que no se reutiliza como límite de paso. |  |  | Pendiente |
| R5 | Definir entradas obligatorias y casos `not_applicable` / `no_evaluable`: clase de exposición, tiempos, propiedades/capa superficial, geometría, suelo e inventario de puntos accesibles. |  |  | Pendiente |
| R6 | Validar modelo de transferencia: equipotencialidad del objeto metálico, conexiones/topología, potencial del suelo local en el punto de contacto y superficie z=0. Precisar si la conexión lumped del modelo representa los casos del alcance o exige excluirlos. |  |  | Pendiente |
| R7 | Establecer criterio de aceptación para cada tensión transferida. El borrador usa el límite de contacto aplicable a la exposición como propuesta; confirmar su fundamento y alcance o definir otro método. No asumir que RETIE fija aquí un umbral transferido independiente. |  |  | Pendiente |
| R8 | Confirmar requisitos de NTC 2050, segunda actualización, sección 250-53(G), y el alcance del requisito de 75 cm para electrodos horizontales. Evitar mapearlo como profundidad global de malla. |  |  | Pendiente |
| R9 | Validar la resistencia de referencia del Art. 3.12.3, Tabla 3.12.3.a, por clase de tensión y confirmar que se comunica como referencia, no como único criterio de seguridad. |  |  | Pendiente |
| R10 | Revisar expresiones, unidades, algoritmo y correspondencia de cada regla del JSON con la cláusula citada; clasificar cada una como obligatoria o guía. |  |  | Pendiente |

## Cambios requeridos antes de publicación

1. Registrar las respuestas anteriores en el JSON del perfil, con fuente, cláusula, edición, unidad, método de verificación y aplicabilidad concreta.
2. Añadir criterios de rechazo o `no_evaluable` cuando falte una entrada necesaria; no transformar ausencia de datos en cumplimiento ni en `not_applicable`.
3. Versionar el perfil revisado sin sobrescribir el borrador. Adjuntar identidad del revisor, fecha y referencia de esta hoja en el registro de curaduría.
4. Ejecutar validación del esquema y pruebas del catálogo/API para selección, fijación por proyecto, resolución del contexto y bloqueo por criterios obligatorios faltantes.
5. Solo tras aprobación registrada, publicar como `reviewed` y habilitar uso según las reglas de permisos del catálogo.

## Dictamen

- [ ] Aprobado dentro del alcance descrito.
- [ ] Aprobado con condiciones que deben incorporarse antes de publicar.
- [ ] Rechazado; mantener como borrador.

**Condiciones/exclusiones:**

______________________________________________________________________________

**Registro de versión aprobada / enlace a evidencia:**

______________________________________________________________________________

> Hasta completar y firmar esta hoja, el perfil debe permanecer en borrador y bloqueado para declarar cumplimiento.
