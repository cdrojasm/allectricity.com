# Plan de pruebas P0: optimización, perfil, plano y respuesta del agente

Casos listos para recorrer los cuatro hallazgos P0 del mapa de flujos. El recorrido capturado el 15 nov 2026 pertenece al commit `82e3a13`; estos casos validan las correcciones de código posteriores.

## Alcance y límites

- **P1 — Optimizar hasta cumplir:** modo autónomo, iteraciones, versiones nuevas, recálculos, límite y cierre.
- **P2 — Optimizador de topologías:** catálogo y selección de perfiles, resolución de contexto y corrida desde la interfaz.
- **P3 — Plano:** representación de geometría paramétrica y persistencia al editar.
- **P4 — Respuesta del agente:** la respuesta final debe corresponder con la versión que realmente guardó.

El perfil sintético que crea `05-optimizador-topologia.spec.js` sirve para comprobar el flujo de software, no la validez de IEEE 80/RETIE ni el cumplimiento de un diseño real. No publicar estudios ni usar resultados de este plan para ingeniería.

## Preparar el entorno local

1. Levantar el stack: `make local-up`.
2. Crear las cuentas locales: `make smoke-ui-seed`. Las credenciales quedan en `app/.env.smoke-ui`; usar una sesión por perfil y reutilizarla.
3. Para el flujo de agente, confirmar que el worker está activo y que `DESIGN_AGENT_ENABLED` y el proveedor LLM están configurados. El optimizador de agente requiere una respuesta real del modelo.
4. Usar solo proyectos con prefijo `zz-smoke-`. Registrar los IDs de proyecto, conversación, artefacto, versión, corrida y cálculo en la hoja de ejecución.
5. Para comprobar el optimizador topológico con perfil sintético, usar el caso existente: `make smoke-ui ARGS='05-optimizador-topologia'`. Solo local; crea y retira un perfil de prueba, crea datos y los barre al terminar. No ejecutar en un entorno remoto.
6. Si una corrida deja proyectos `zz-smoke-*`, eliminarlos con `make smoke-ui-sweep`.

### Datos comunes

- Proyecto: `zz-smoke-<fecha>-<id>`.
- Geometría inicial para plano: 40 × 30 m, profundidad 0,5 m, separación X 5 m / Y 6 m, 8 varillas de 2,4 m; dejar `geometry.conductors` ausente o como lista vacía para probar el caso paramétrico.
- Entradas de cálculo para el escenario de agente: suelo homogéneo 100 Ω·m; corriente de falla 8.000 A; despeje 0,5 s; capa superficial 3.000 Ω·m y 0,1 m. Confirmar antes de empezar que el resultado inicial sea «No cumple».
- En los casos P1 no cambiar datos de falla, suelo, perfil, criterios de exposición ni restricciones entre iteraciones; solo debe cambiar la geometría que el usuario autorizó.

## Casos de prueba

| ID | Prioridad | Caso y pasos | Resultado esperado / evidencia |
|---|---|---|---|
| P1-01 | P0 | Abrir el proyecto con un cálculo vigente «No cumple» y pulsar **Optimizar hasta cumplir**. Esperar eventos y cálculos hasta que termine. | Se crea una corrida autónoma ligada al artefacto y al cálculo mostrado. Cada intento aplicado crea una versión y un cálculo de esa versión. El chat y el panel muestran el mismo resultado y el botón no lanza dos corridas con doble clic. Guardar secuencia versión → cálculo → veredicto. |
| P1-02 | P0 | En la misma secuencia, provocar o configurar un límite local de una iteración (`DESIGN_MAX_ITERATIONS=1`) y reiniciar worker/API antes de repetir P1-01. | Como máximo se crea una versión de iteración. El run termina; informa el mejor candidato y la restricción dominante sin afirmar cumplimiento si el resultado no cumple. Restaurar la configuración original al acabar. |
| P1-03 | P1 | Repetir P1-01 con una geometría donde el diseñador no pueda proponer un cambio válido (p. ej. área intervenible restringida o una mejora que viole una restricción). | No se guarda una versión inválida ni se encola cálculo con geometría inválida. El run termina con explicación accionable y sin ciclo infinito. Capturar el evento de error y la respuesta final. |
| P1-04 | P1 | Ejecutar varias iteraciones: guardar el margen/veredicto de cada versión y comparar con el candidato marcado como mejor por el run. | Se conserva el ID/versión del candidato con mejor margen. Si la versión final tiene peor margen, la interfaz identifica claramente el mejor candidato y permite abrir/restaurar esa versión; anotar como defecto si solo se registra y no se puede recuperar desde el flujo. |
| P2-01 | P0 | Retirar del proyecto el único perfil revisado fijado y pulsar **Resolver contexto**. | El sistema bloquea la resolución con `normative_profile_not_selected`; el usuario puede volver a fijar el perfil. No se sugiere un perfil normativo por defecto. |
| P2-02 | P0 | Localmente, ejecutar `make smoke-ui ARGS='05-optimizador-topologia'`. Además de su siembra por API, en una ejecución manual abrir el selector, elegir el perfil `zz-smoke-*`, guardar la selección y recargar el proyecto. | El perfil revisado aparece en el selector, queda fijado al proyecto tras recargar y el contexto muestra ese perfil/versión. La corrida concluye, la alternativa se previsualiza y se aplica como versión nueva. El perfil sintético no valida normativa. |
| P2-03 | P1 | Crear un perfil borrador con el perfil `super_admin`; abrir el selector como `designer`. Luego intentar fijar el borrador por API solo en el entorno local de pruebas. | El borrador no aparece en la lista de selección; la API rechaza la fijación y la selección previa permanece sin cambios. Solo versiones revisadas se pueden seleccionar. Guardar estado y respuesta HTTP. |
| P2-04 | P1 | Fijar dos perfiles revisados con tipos de instalación incompatibles y resolver el contexto. | La resolución queda bloqueada e identifica la incompatibilidad; no inicia una corrida ni se presenta como diseño conforme. |
| P3-01 | P0 | Crear un artefacto con geometría paramétrica, sin conductores explícitos y con varillas por `rods_count`. Abrir Resumen y Plano. | Ambos muestran retícula y número/posición de varillas coherentes. El plano no muestra «0 elementos». Registrar conteo visual en cada vista y capturas. |
| P3-02 | P0 | En P3-01 comprobar separación asimétrica (X=5 m, Y=6 m), varillas y extensión. Editar y guardar una línea; cerrar y volver a abrir el plano. | La malla materializada conserva dimensiones, espaciamientos y varillas; la edición crea una nueva versión y persiste tras recargar. No duplica conductores o varillas en aperturas sucesivas. Comparar snapshots antes/después. |
| P3-03 | P1 | Abrir un artefacto con conductores/varillas explícitos y uno con listas explícitamente vacías. Reabrir ambos tras guardar sin editar y tras una edición. | La geometría explícita se conserva tal cual; las listas vacías usan la retícula paramétrica una sola vez. No reemplaza ni duplica conductores explícitos. |
| P4-01 | P0 | Pedir al agente una edición clara («agrega varillas en las esquinas y recalcula»); confirmar que se crea versión. Observar la respuesta final. | La tarjeta, el número de versión y la respuesta del agente coinciden. Si el modelo responde «no hubo cambios», el backend corrige la respuesta indicando la versión y campos guardados. |
| P4-02 | P1 | Repetir P4-01 con distintas formas de negación: «no se realizaron cambios», «no hicimos cambios», «no hubo cambios» y «no changes were made». | Con una versión guardada, ninguna negación contradice el evento; la respuesta corregida identifica la versión/cambios. Con cero cambios guardados, no inventa una versión ni afirma que hubo cambios. |
| P4-03 | P1 | Hacer que el diseñador proponga un cambio que falle validación o no sea aplicado y pedir al agente un resumen. | No se muestra un mensaje de éxito ni una versión nueva inexistente. El error de validación se conserva y se explica; verificar que `last_applied` no se reutilice desde una edición anterior del mismo run. |

## Orden recomendado de ejecución

1. **P3-01 a P3-03**: no requieren LLM ni perfil normativo y comprueban la hidratación del editor.
2. **P4-01 a P4-03**: requieren LLM, pero no optimizador normativo.
3. **P2-01 a P2-04**: usar `super_admin` solo para crear/retirar el perfil sintético; ejecutar el flujo de topología únicamente en local.
4. **P1-01 a P1-04**: dejar para el final porque consumen cálculos y dependen del proveedor LLM. Usar un caso donde el primer cálculo sea «No cumple».

## Registro de ejecución

Por caso, apuntar: fecha/commit, entorno, perfil de usuario, pass/fail/bloqueado, IDs de proyecto/conversación/artefacto/run/cálculos, versiones creadas, mensaje visible, capturas y enlace a trazas/eventos. Al fallar, conservar la evidencia antes de limpiar; borrar solo los proyectos `zz-smoke-*` y retirar el perfil sintético.

| Caso | Estado | Proyecto / IDs | Evidencia / observaciones |
|---|---|---|---|
| P1-01 | **Pasó · 2026-11-15 local** |  | `make smoke-ui ARGS='07-p1-optimizacion-autonoma'`: se completó el cálculo más reciente, el run cerró con `design_loop_result`, la interfaz mostró el mejor candidato y el tope fue ≤3. La rama de restauración no se forzó porque depende de que una iteración posterior empeore. |
| P1-02 | **Pasó · 2026-11-16 local** | proyecto `9f703a4fc2cc`, cálculo inicial `9bc1d613`, mejor `ef143dd8` | Worker con `DESIGN_MAX_ITERATIONS=1` y proveedor real; `SMOKE_LOOP_SCENARIO=limit1 make smoke-ui ARGS='specs/08-p1-casos-forzados.spec.js'`. Una sola iteración (v2, margen −135,7 % → −128,0 %), cierre `iteration_limit`, «No cumple» sin afirmar cumplimiento; el panel muestra «Iteraciones: 1/1» y el mejor candidato (contacto, IEEE 80-2013). Worker restaurado al terminar. |
| P1-03 | **Pasó tras corrección · 2026-11-16 local** | cálculo `64252ddd` | LLM de prueba `invalid` (profundidad −1 m en las 6 rondas del diseñador). **Defecto encontrado y corregido:** el diseñador devolvía `applied` junto con errores y el bucle intentaba guardar (cerraba como `save_failed` con el borrador inválido en el run); ahora una propuesta con errores cierra como `no_valid_candidate` y descarta el borrador. Resultado: solo v1, ningún cálculo nuevo, mensaje «No se pudo guardar una mejora válida; no se creó una versión nueva… Iteraciones usadas: 1/3», sin botón de rescate. |
| P1-04 | **Pasó · 2026-11-16 local** | cálculos v1 `1eeb75ae`, v2 `e9390b8e`, v3 `ad94ae15` | LLM de prueba `worse` (retícula 10 × 10 m). v1 −135,7 %, v2 −239,3 %; el agente restauró v1 como v3 (`origin.restored_from = 1`, snapshot idéntico), la recalculó con los parámetros de v1 (−135,7 %) y cerró con `no_improvement`, «Mejor resultado: versión 3 (restaurada desde la versión 1)». Tarjeta «Se editó el artefacto» con «Deshacer (volver a v2)», resultado al día, sin rescate manual. |
| P2-01 | **Pasó · 2026-11-15 local** |  | `make smoke-ui ARGS='05-optimizador-topologia'`: el proyecto quedó sin perfiles fijados, contexto bloqueado con `normative_profile_not_selected` y perfil repuesto al terminar. **Catálogo global vacío (2026-11-16):** `make smoke-ui ARGS='specs/09-p2-catalogo-vacio.spec.js'` con 0 perfiles revisados en el catálogo: el selector muestra «No hay perfiles normativos revisados disponibles», «Guardar perfiles» deshabilitado, ningún perfil sugerido ni fijado, y «Resolver contexto» queda en «Optimización bloqueada» (`normative_profile_not_selected`). Detalle menor: la línea de perfil muestra «vnone». |
| P2-02 | **Pasó · 2026-11-15 local** |  | `make smoke-ui ARGS='05-optimizador-topologia'`: 7/7. La UI retiró y volvió a fijar el perfil de prueba; corrida del solver, alternativa, historial, tarifa de catálogo y estudio publicado correctos. Perfil sintético, sin validación normativa. |
| P2-03 | **Pasó · 2026-11-15 local** |  | El borrador quedó oculto en el catálogo; API rechazó fijarlo y la selección revisada original se conservó. Incluido en el runner `05`, 7/7. |
| P2-04 | **Pasó · 2026-11-15 local** |  | Dos perfiles revisados con tipos de instalación incompatibles quedaron bloqueados al resolver contexto. El runner `05` pasó 7/7 y limpió los perfiles sintéticos. |
| P3-01 | **Pasó · 2026-11-15 local** |  | `make smoke-ui ARGS='06-p0-plano-y-agente'`: Resumen, lanzador y editor mostraron 15 conductores y 8 varillas; abrir sin editar conservó solo la versión 1. |
| P3-02 | **Pasó · 2026-11-15 local** |  | `make smoke-ui ARGS='06-p0-plano-y-agente'`: mover la línea x=5 a x=4 creó una versión única; v1 quedó intacta y cerrar/reabrir conservó 15 conductores y 8 varillas. |
| P3-03 | **Pasó · 2026-11-15 local** |  | `make smoke-ui ARGS='06-p0-plano-y-agente'`: geometría explícita, listas vacías y listas ausentes mostraron 15 conductores/8 varillas y no añadieron versiones al abrir. |
| P4-01 | **Pasó · 2026-11-15 local** |  | `make smoke-ui ARGS='06-p0-plano-y-agente'`: el agente guardó `geometry.width_m = 31` y contestó que cambió el ancho. La primera aserción usó por error la versión más antigua; corregida a newest-first y repetida con éxito. No se forzó una respuesta falsa de «no hubo cambios». |
| P4-02 | **Pasó · 2026-11-16 local** |  | Forzado (`SMOKE_LOOP_SCENARIO=p4`, `specs/11-p4-respuesta-forzada.spec.js`): el modelo emitió las cuatro negaciones tras guardar v2–v5 y el chat mostró «Se guardó la versión N… geometry.width_m=…» en cada caso; afirmar «Guardé la versión 99» sin cambios se corrigió a «No se guardó una versión nueva». Proveedor real (`specs/10-p4-respuesta-inducida.spec.js`, 6/6): versiones y mensajes coherentes, pero el modelo se negó a afirmar el guardado falso y su texto original no queda en los logs, así que solo el forzado demuestra la corrección. |
| P4-03 | **Pasó · 2026-11-16 local** |  | Forzado y con proveedor real: tras guardar el ancho (v6) la profundidad −2 m se rechaza, ninguna versión la guarda y el paso siguiente no reutiliza `last_applied`. **Corregido:** la respuesta reconciliada ahora también informa los cambios rechazados después de la última versión guardada (y los campos que `apply` descartó): «Se guardó la versión 6… Campos guardados: geometry.width_m=38.0. Cambios no aplicados: geometry.burial_depth_m: Input should be greater than 0.». Pendiente menor: el motivo sale en inglés (mensaje del validador). |

**Cobertura pendiente:** ninguna de código en la matriz P0. **Repetición completa 2026-11-16:** escenarios forzados `limit1`, `invalid`, `worse` y `p4` en verde (P1-03 falló una vez por una suspensión de la máquina a mitad de la prueba —reloj del contenedor desfasado 5 min— y pasó al repetirla) y `make smoke-ui` completo con el worker normal: 30 pasaron, 9 omitidos por diseño (08 y 11 requieren el worker de escenario). P1-02 a P1-04 y los P4 forzados se repiten con [`app/smoke-ui/loop-scenarios`](../app/smoke-ui/loop-scenarios/README.md) (LLM de prueba local; solver, API y UI reales). P2-01 a P2-04 pasan en los runners `05` y `09`. **Sigue abierto T0:** el perfil sintético no acredita cumplimiento; falta la revisión y firma del especialista.

## Plan de mejoras posterior a la prueba

Las tareas están ordenadas por bloqueo de lanzamiento. Los criterios de cierre describen evidencia que debe quedar en código, pruebas o documentación.

### T0 · Publicar un perfil normativo revisado

**Responsable:** especialista de puesta a tierra/normativa, con apoyo del equipo de producto. **Bloquea el uso real del optimizador topológico.** La prueba sintética confirmó que la interfaz deja seleccionar y fijar perfiles y que la corrida funciona; no hay un perfil revisado real cargado.

**Estado de inicio (2026-11-15):** pre-revisión documental iniciada y preparada en [`docs/normative_profiles/CO/REVIEW_CHECKLIST.md`](normative_profiles/CO/REVIEW_CHECKLIST.md). Se cotejaron los artículos citados contra el Libro 3 oficial; quedan decisiones de ingeniería y vigencia que requieren firma de especialista. El borrador sigue `draft`, `reviewed=false` y `may_be_used_for_compliance=false`.

1. El especialista debe completar y firmar cada decisión de `docs/normative_profiles/CO/REVIEW_CHECKLIST.md`, incluyendo norma/edición aplicable, criterios obligatorios, método de contacto y paso, modelo de transferencia, NTC 2050 y límites de aplicabilidad.
2. Actualizar `docs/normative_profiles/CO/substation_ac_retie_2026_draft.json` y responder/documentar los puntos abiertos de OP-20 en `docs/BACKLOG_OPTIMIZADOR.md`, citando fuentes/cláusulas y separando requisitos obligatorios de recomendaciones.
3. Cargar la versión aprobada al catálogo como borrador, pasar la validación del esquema y publicarla como `reviewed` solo con la evidencia de revisión registrada.
4. Probar con una cuenta `designer` nueva: seleccionar y fijar la versión revisada, recargar, resolver OP-05 y completar una corrida de topologías. Probar además un proyecto sin perfil y un perfil que no aplique.

**Cierre:** un proyecto nuevo puede elegir una versión revisada identificable; una corrida válida registra perfil, versión y reglas resueltas; sin perfil o ante criterios obligatorios incompletos el sistema bloquea la corrida y explica qué falta. No cerrar esta tarea con el perfil sintético de smoke.

### T1 · Hacer verificable el cierre del bucle autónomo

**Responsable:** backend de agente y experiencia de resultados. **Hecho (2026-11-16):** el backend registra y puntúa el mejor candidato, cierra de forma determinista y, si una iteración posterior empeora, restaura el mejor diseño como versión nueva y lo recalcula; una propuesta que nunca validó cierra como `no_valid_candidate` sin guardar ni calcular. P1-01 a P1-04 pasan desde la UI (P1-03/P1-04 con el LLM de prueba de `app/smoke-ui/loop-scenarios`).

1. **Hecho:** guardar candidato, versión, cálculo, veredicto, margen mínimo y criterio dominante en `backend/src/infrastructure/agents/design_agent.py`; puntuar márgenes en estructuras antiguas y resultados por escenarios.
2. **Hecho:** el backend guarda y publica `design_loop_result`; el panel presenta razón, iteraciones, veredicto, versión/cálculo y margen mínimo.
3. **Hecho y verificado en UI (P1-04):** el panel restaura la mejor versión como versión nueva y recalcula con los parámetros del cálculo original. Comprobar que la versión nueva apunta al snapshot esperado y que el nuevo cálculo termina antes de anunciar el rescate.
4. **Hecho en backend y en UI:** pruebas deterministas cubren `DESIGN_MAX_ITERATIONS=1`, diseñador sin cambio válido y margen posterior peor. Repetir P1-02/P1-03/P1-04 desde la UI para confirmar límite, no-colgado y rescate del mejor candidato.

**Cierre:** los tres escenarios terminan sin run colgado, el límite no se excede, ningún resultado no conforme se etiqueta como conforme y el mejor candidato puede recuperarse desde la interfaz con versión/cálculo trazables. P1-01 a P1-04 pasan.

### T2 · Probar la edición y persistencia del plano

**Responsable:** frontend del editor y pruebas UI. **Hecho (2026-11-15):** `make smoke-ui ARGS='06-p0-plano-y-agente'` pasó 3/3; edición, recarga, geometría explícita, listas vacías y ausencia de listas están cubiertas.

1. **Hecho:** mover una línea generada crea una sola versión; el snapshot original se conserva.
2. **Hecho:** cerrar/reabrir mantiene la geometría guardada sin duplicar conductores ni varillas.
3. **Hecho:** fixtures explícitos, listas vacías y listas ausentes se hidratan una sola vez; la geometría explícita queda intacta.
4. **Hecho:** el runner compara coordenadas X/Y de la línea editada y arreglos explícitos de conductores/varillas.

**Cierre:** las tres formas de geometría pasan recarga, edición y reapertura; cada edición guarda una única versión y los snapshots coinciden con la vista del plano y el Resumen.

### T3 · Hacer que la respuesta final refleje solo cambios persistidos

**Responsable:** backend de agente. **Implementado (2026-11-15):** reconciliación determinista entre texto final y diff guardado; 34 pruebas del agente pasaron, incluida validación rechazada y respuesta UI con valor/versiones persistidos.

1. **Hecho:** extraer `reconcile_final_response`, función determinista que recibe el texto y el registro aplicado.
2. **Hecho:** cuando se guardan cambios, generar versión, resumen, paths y valores exclusivamente desde el diff persistido.
3. **Hecho:** una afirmación de guardado sin versión se corrige y `workspace.last_applied` se limpia tras consumirla.
4. **Hecho:** pruebas sin LLM cubren las negaciones de P4-02, un valor inventado, cero cambios y validación rechazada; el runner visual P4-01 confirma el dato guardado.

**Cierre:** pruebas unitarias demuestran que texto, versión y diff siempre coinciden; el escenario sin cambios no declara éxito; el escenario UI confirma que la tarjeta y la respuesta coinciden con el snapshot persistido.

### T4 · Cerrar la matriz de regresión P0

**Responsable:** pruebas de producto. Ejecutar solo después de T0–T3.

1. Completar los casos pendientes P1-02 a P1-04, P4-02 y P4-03; actualizar la tabla de ejecución con commit, IDs y evidencia por caso. Añadir una prueba aparte del catálogo global vacío para cerrar el alcance original de P2-01.
2. Ejecutar los runners focalizados `05`, `06` y `07`; luego ejecutar `make smoke-ui` completo para comprobar que los casos nuevos no rompen lectura, ciclo de proyecto, aislamiento ni estudio público.
3. Confirmar que los perfiles `zz-smoke-*` queden retirados y que no existan proyectos `zz-smoke-*` residuales. Ejecutar `make smoke-ui-sweep` si hay alguno.

**Cierre:** todos los casos P0 tienen resultado y evidencia; `make smoke-ui` termina en verde en local y la limpieza no deja proyectos ni perfiles sintéticos activos.
