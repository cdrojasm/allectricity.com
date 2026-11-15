# Backlog del optimizador de diseño

> Ids `OP-NN`. Extiende `BL-20` (bucle de optimización) y `PE-21` (barridos y optimización). El solver tiene su
> propio backlog: [BACKLOG_SOLVER.md](BACKLOG_SOLVER.md). Origen: roadmap «Grounding Solver v0.1» ajustado el 2026-10-16.

## Principios

1. **El optimizador no toca el solver**: solo cambia parámetros geométricos y llama a `evaluate` (SV-12). Los resultados eléctricos siempre vienen del solver.
2. **Seguridad como restricción, costo como objetivo** (ADR-005): mínimo costo sujeto a `Vs ≤ Vs_lim` y `Vt ≤ Vt_lim`. No se minimiza solo `Rg`.
3. **Topología fija y variables continuas primero** (ADR-004). Las decisiones binarias (agregar o quitar electrodos) vienen después.
4. **Todo resultado se revalida** con el solver completo (ADR-007) y **nunca se aplica sin crear versión nueva** del artefacto (BL-20).
5. **El agente lanza y consulta**; no interviene en iteraciones (ADR-006). Determinismo y semilla registrada.
6. **El modelo de costo es independiente** del solver.

## Dependencias del solver

| Necesita | Id | Por qué |
|---|---|---|
| Interfaz de evaluación estable | SV-12 | Única puerta de entrada |
| Máximos de `Vs`/`Vt` con ubicación | SV-08 | El máximo cambia de lugar con la geometría; es la fuente de no suavidad |
| Perfil de rendimiento | SV-06 | Fija el presupuesto de evaluaciones |
| Geometría v2 / desacople edificio–malla | SV-09, BL-19 | El generador necesita una geometría paramétrica persistible |
| Sensibilidades | SV-16 | Solo para IPOPT |

## Ya existe y se reutiliza

- Tolerables IEEE 80-2013 con `Cs`, `D_f`, `S_f` (PE-09, PE-11): base de `Phi(x)`.
- Dimensionamiento térmico del conductor (BL-04 A/B): fija sección mínima y por tanto costo de material.
- Obstáculos constructivos y validaciones geométricas básicas en el editor (BL-19).

## Backlog

### A. Fundamentos (P0)

| Id | Prio | Estado | Feature | Criterio de aceptación | Depende de |
|---|---|---|---|---|---|
| OP-01 | P0 | ✅ | Indicador de utilización y restricciones | Implementado: `Phi` para reporte, restricciones independientes de paso/contacto y adaptador que deriva límites desde PE-09 con exposición, norma, edición, fórmulas y parámetros trazables. Integrado en OP-04. | PE-09 |
| OP-02 | P0 | ◐ | Generador paramétrico de geometría | Implementadas generación rectangular regular y transformación determinista de mallas trazadas. Contrato inicial: dimensiones y espaciamientos por eje para retícula regular; traslación y extensión para trazadas; profundidad común; longitud común o vector `rod_lengths_m` indexado por el orden de las varillas base; y, para trazadas, deltas de ambos extremos por conductor mediante `conductor_endpoint_deltas`. `variable_bounds` acepta límites inclusivos y OP-05 genera límites seguros de traslación; los dominios comerciales discretos aceptan longitudes de varilla declaradas explícitamente, con opción/versiones y procedencia del catálogo aprobado. OP-04 rechaza candidatos fuera de límite o sin selección inequívoca de opción comercial. Se preservan conteos y contactos; se exige longitud mínima de cinco radios y se validan áreas y obstáculos antes del solver. La interfaz de plano y el endpoint de corrida consumen el contexto OP-05 sobre la misma versión de geometría guardada. Pendiente probar estabilidad de conexiones frente a deformaciones. | SV-09, BL-19, OP-05 |
| OP-03 | ◐ | Suite de abastecimiento y costo de materiales | Implementado: búsqueda web con OpenAI `web_search` o Tavily, lectura acotada de páginas públicas, extracción IA contrastada contra evidencia, catálogo persistido por proyecto, historial inmutable, aprobación con fuente/precio/proveedor y control de vigencia. Calcula subtotales por moneda con cantidad × precio unitario; no mezcla monedas ni completa datos ausentes. Pendiente: conversión de unidades físicas/monedas con tasas trazables y cantidades automáticas desde la geometría del diseño. Las sugerencias y leads web requieren revisión; no equivalen a cotizaciones verificadas. | BL-21 |
| OP-04 | P0 | ◐ | Evaluador unificado de diseño | Implementado el flujo `DesignParameters → Geometría → Solver → Seguridad`, con `{Rg, Vs, Vt, Feasible, ConstraintViolations, NumericalStatus}` y conteo/presupuesto de evaluaciones. OP-05 valida dominios comerciales y restricciones geométricas antes del solver. El endpoint OP-06 ya lo combina con costo OP-03: requiere cantidades explícitas, una moneda objetivo y no convierte monedas; falta política trazable de cantidades derivadas de geometría. | SV-12, SV-08, OP-01…03 |
| OP-05 | P0 | ◐ | Restricciones geométricas y constructivas | Modelo de áreas migrado a polígonos. El contexto combina perfiles revisados, cotas geométricas trazables y dominios discretos desde opciones de ingeniería explícitas en cotizaciones aprobadas y vigentes; la aprobación/versionado fija item, opción, unidad y fuente. Los filtros de aplicabilidad desconocida no producen candidatas. `evaluate_design` verifica que el candidato coincida con una opción comercial aplicable e identifique su opción de catálogo; los dominios continuos y discretos se mantienen separados. Polígonos intervenibles, exclusiones, obstáculos, contacto de varillas y conectividad siguen como filtros exactos antes del solver; polígonos arbitrarios no se reducen a intervalos escalares. La interfaz de plano revisa el contexto y el endpoint lo vuelve a resolver desde las versiones fijadas al proyecto y catálogo aprobado. Pendiente registrar hechos de aplicabilidad con sus fuentes y poblar perfiles revisados globales/opciones comerciales con especificación curada. Si falta jurisdicción, regla aplicable o dato necesario, dejar la variable fuera de la búsqueda; no sustituirlo por un default. | OP-02, OP-20, BL-19 |
| OP-06 | P0 | ◐ | Experimento base con búsqueda local discreta | Implementado `search_discrete_local` y el endpoint autenticado de corrida: recibe versión de artefacto, escenario eléctrico explícito, variables, hechos de aplicabilidad, cantidades declaradas y moneda objetivo; resuelve OP-05 en servidor y conecta construcción OP-02, evaluación OP-04, costo OP-03 y presupuestos reproducibles. Límite síncrono inicial: máximo 5 candidatas únicas. Se rechaza costo incompleto, vencido o de una moneda distinta; no hay conversión. Pendiente ejecutar La Esperanza cuando existan perfil revisado con criterios obligatorios evaluables, opciones/cotizaciones aprobadas y datos de costo; luego comparar convergencia y mejora frente al diseño base. Su paquete de datos sí permite preparar una evaluación eléctrica base, pero no optimización de costo. **Criterio de continuidad: si esto da la ganancia requerida, IPOPT se pospone.** | OP-04, OP-05, OP-19 |
| OP-07 | P0 | ⬜ | Revalidación final y versionado | Toda solución se recalcula con el solver completo y malla fina; si difiere de la evaluada más allá de tolerancia, se rechaza. Se guarda como versión nueva del artefacto con traza del optimizador y de la semilla. | OP-06 |
| OP-19 | P0 | ◐ | Historial de corridas y alternativas factibles | Implementadas tablas, migración, repositorio y endpoints de creación/listado/detalle. Se fija versión de artefacto, request, contexto OP-05, perfil/dominios/catálogo, hashes, algoritmo, semilla/presupuesto y diagnósticos; alternativas guardan candidato, geometría, métricas eléctricas, restricciones, costo/desglose y traza. Solo se persisten candidatas con `Feasible=true`; la de menor costo en moneda objetivo queda recomendada. Pendiente valorar persistencia de corridas bloqueadas/canceladas y comparación de alternativas no dominadas por costo y margen. | OP-04…OP-07, OP-13 |
| OP-20 | P0 | ◐ | Perfiles de restricciones normativas | Implementado catálogo versionado con estados borrador/revisado/retirado, revisión privilegiada, pin por proyecto a versiones revisadas y combinación trazable de perfiles compatibles. Cada regla declara cláusula, expresión/valor, unidades, aplicabilidad, categoría, fuente y método de verificación. Creado borrador de perfil Colombia para subestaciones de c.a. basado en RETIE Resolución 40284 de 2026 (`docs/normative_profiles/CO/substation_ac_retie_2026_draft.json`); no está cargado ni revisado en el catálogo. El evaluador calcula contacto con la Tabla 3.12.1.a cuando no hay capa superficial y paso con metodología IEEE 80-2013, registrando los métodos por separado; esa tabla es de contacto y no se reutiliza como límite de paso. El cálculo v2 admite exposiciones transferidas explícitas: entidad metálica conectada por la topología, punto local de suelo muestreado, escenario y evidencia de inventario/accesibilidad; cada exposición puede fijar sus propios datos de despeje, clase y capa para seleccionar su límite. No usa diferencias GPR entre entidades como tensión aplicada a una persona. La transferencia compara el par metal-suelo local con el límite de contacto seleccionado bajo el modelo equipotencial declarado; ese criterio numérico es una propuesta del perfil pendiente de validación, no un límite transferido específico fijado por RETIE. Un inventario incompleto, dato de límite faltante o exposición accesible sin cálculo mantiene el criterio como `no_evaluable`; solo un inventario completo sin puntos accesibles permite `not_applicable`. Si falta un criterio obligatorio evaluable, el resultado de seguridad no declara cumplimiento. Perfil aún bloqueado para revisión: confirmar aplicabilidad/métodos con especialista, el supuesto del objeto equipotencial, NTC 2050 y validación profesional antes de activar. Separar requisitos obligatorios de recomendaciones técnicas; nunca inferir cumplimiento cuando falte una regla obligatoria aplicable o no esté confirmada su aplicabilidad. No copiar números de RETIE, IEEE u otra norma como constantes del algoritmo. | OP-05, OP-19 |
| OP-21 | P0 | ⬜ | Recomendaciones internacionales de diseño | Mantener un catálogo curado y versionado de guías IEEE/IEC, asociado al tipo de instalación y al alcance de cada documento. Si el perfil jurisdiccional no fija una recomendación de diseño, devolver sugerencias orientativas compatibles con el contexto; registrar documento/edición/cláusula, ámbito, supuestos, parámetros sugeridos y advertencias de aplicabilidad. No convertir sugerencias en límites obligatorios, no completar requisitos legales ausentes y no declarar cumplimiento basándose solo en una guía. | OP-05, OP-19, OP-20 |

### B. Optimización con restricciones (P1)

| Id | Prio | Estado | Feature | Criterio de aceptación | Depende de |
|---|---|---|---|---|---|
| OP-08 | P1 | ◐ | Costo de instalación | Implementado en la búsqueda topológica: la tarifa cubre material de conductor y varilla, excavación de zanja (ancho explícito con fuente), tendido, hincado y conexiones; cada tarifa viene del catálogo aprobado (vigente, misma moneda, unidad del cómputo) o de un monto explícito con fuente, y una línea sin tarifa bloquea la corrida antes del solver. Pendiente: movilización, perforaciones y dificultad del terreno con supuestos trazables. | OP-03 |
| OP-09 | P1 | ⬜ | Mínimo costo sujeto a seguridad | Factibilidad verificada y costo detallado frente al diseño base. Multistart desde varios iniciales para reducir la dependencia de un óptimo local; se reporta la variación entre corridas. | OP-06, OP-07 |
| OP-10 | P1 | ◐ | Exploración costo–margen (Pareto) | Parcial: la comparación marca el frente costo–utilización entre las alternativas validadas en L3 de una corrida. Pendiente: barrer `min C` sujeto a `Phi ≤ α` para varios `α`, la gráfica y la exportación. | OP-09 |
| OP-11 | P1 | ⬜ | Análisis de sensibilidad | Influencia de cada parámetro sobre costo, `Vs` y `Vt` (diferencias finitas al inicio); orienta qué variables vale la pena optimizar. | OP-04 |
| OP-12 | P1 | ◐ | Ejecución como job asíncrono | Implementado para la búsqueda topológica: `POST /optimizer-runs/topology` pone la corrida en cola (Celery, cola `calculations`, tarea `spat.optimize_topology`); se consulta con `GET /optimizer-runs/{id}` (progreso en `result_summary.progress`) y se cancela con `POST /{id}/cancel`, que detiene la búsqueda tras la llamada en curso. Un worker reiniciado reanuda desde el checkpoint de la corrida; un estado terminal nunca se sobrescribe. Pendiente: llevar la búsqueda discreta OP-06 al mismo job y registrar decisiones en SV-15. | OP-07, PE-17 |
| OP-13 | P1 | ◐ | Comparación de alternativas y reporte | Implementado `GET /optimizer-runs/{id}/comparison`: costo y desglose, `Rg`, `Vs`, `Vt`, utilización y margen, complejidad constructiva (m de conductor, varillas, conexiones), ahorro frente al diseño base, procedencia de tarifas, perfil y advertencias (sin certificar, borrador). `POST /{id}/alternatives/{alt}/apply` crea una versión nueva del artefacto (BL-20). Panel en el editor de plano. El diseño base se evalúa en L3 (llamada fuera del presupuesto) y el ahorro solo se reporta si cumple. Pendiente: reporte exportable (PDF). | OP-10, BL-21, PE-24 |

### C. Optimización con gradientes (P2, condicionada)

**Puerta de entrada para IPOPT:** se implementa solo si, tras OP-06 y OP-09, se cumple que (a) la búsqueda sin gradientes no alcanza el costo o el tiempo objetivo, (b) hay suficientes variables continuas para que valga la pena y (c) SV-06 muestra que las diferencias finitas son inviables. De lo contrario se mantiene la búsqueda local.

| Id | Prio | Estado | Feature | Criterio de aceptación | Depende de |
|---|---|---|---|---|---|
| OP-14 | P2 | ⬜ | Integración IPOPT (C++) | Objetivo, restricciones, gradientes, jacobianos, límites de variables y estado de convergencia, detrás de una interfaz que permita sustituir el algoritmo (ADR-002). | SV-16 |
| OP-15 | P2 | ⬜ | Validación de gradientes | Comparación con diferencias finitas en varios diseños, errores relativos documentados, detección de discontinuidades con diagnóstico automático. | OP-14 |

### D. Topología y modelos reducidos (P3, investigación)

| Id | Prio | Feature | Notas |
|---|---|---|---|
| OP-16 | P3 | Agregar o quitar electrodos (decisiones discretas) | Búsqueda voraz o por ramificación. Aquí sí rinde la actualización incremental de matriz (SV-21). |
| OP-17 | P3 | Modelos reducidos `V = H·I` y `V_electrodos = R_eq·I` | Aceleración de escenarios múltiples bajo geometría y suelo fijos; no sustituyen al solver. |
| OP-18 | P3 | Optimización de topología y generación desde cero | Se decide tras ver si el mercado pide optimizar mallas existentes o diseñar desde cero. |

### Contrato de variables de OP-02

El generador recibe los parámetros del candidato y, opcionalmente, `variable_bounds`. En la optimización, OP-05 será responsable de generar estos límites a partir de las restricciones del sitio y de reglas constructivas con fuente; el usuario no tendrá que inventar intervalos manualmente. Las claves de límites son rutas a valores numéricos del candidato; se usan índices base cero para listas y puntos para campos anidados, por ejemplo `rod_lengths_m[0]` o `conductor_endpoint_deltas[2].start_dx_m`. Cada límite tiene la forma `{"min": ..., "max": ...}` y es inclusivo. Si el candidato excede un límite, no se construye la geometría ni se llama al solver. La ausencia de un límite generado significa que la variable no se ofrece a optimización, no que tenga un rango constructivo implícito.

| Familia de geometría | Variables admitidas |
|---|---|
| Retícula regular | `length_m`, `width_m`, `conductor_spacing_x_m`, `conductor_spacing_y_m`, `burial_depth_m`, `rod_length_m` uniforme o `rod_lengths_m` por varilla, `perimeter_extension_m` y `conductor_radius_m` para validar longitud mínima. |
| Malla trazada | `translate_x_m`, `translate_y_m`, `perimeter_extension_m`, `burial_depth_m`, `rod_length_m` uniforme o `rod_lengths_m` por varilla, `conductor_endpoint_deltas` por conductor y `conductor_radius_m` para validar longitud mínima. |

`rod_length_m` y `rod_lengths_m` son excluyentes. `conductor_endpoint_deltas` contiene una entrada por conductor; cada entrada admite `start_dx_m`, `start_dy_m`, `end_dx_m` y `end_dy_m`, con deltas omitidos iguales a cero. Los parámetros desconocidos se rechazan. Las longitudes se representan como continuas; seleccionar exclusivamente longitudes comerciales discretas requiere una política de OP-05 y una búsqueda que maneje variables discretas.

### Arquitectura normativa y selección de algoritmo (OP-05/OP-06/OP-20)

- La búsqueda RETIE/NTC/IEEE es evidencia para poblar un perfil de Colombia; sus valores no son reglas globales del producto. La referencia consultada es RETIE, Resolución 40284 de 2026, Libro 3: §3.12.1 exige evaluar las tensiones de paso y contacto según IEEE 80 y la Tabla 3.12.1.a fija límites de contacto según tiempo y exposición; la tabla no es un límite de paso. §3.3.3.3 requiere evaluar tensiones transferidas. §3.12.2.1 remite a NTC 2050 para instalación de electrodos y menciona 75 cm solo para un electrodo instalado horizontalmente. §3.12.3 presenta resistencias de referencia (1 Ω para subestaciones de alta/extra alta tensión), y explícitamente aclara que no sustituyen la verificación de tensiones aplicadas. El perfil debe guardar la cita exacta, versión y condición de aplicabilidad antes de habilitar reglas. Ninguno de esos valores se aplica como límite universal de profundidad o separación de malla ni a toda jurisdicción.
- IEEE Std 80-2013 está enfocado en subestaciones de c.a. y describe métodos de seguridad para ese ámbito; IEEE SA lo marca Inactive-Reserved desde 2024-03-21, por lo que el catálogo debe conservar ese estado y revisar el proyecto P80 antes de presentar una recomendación como vigente. Puede ser una referencia técnica si el perfil/proyecto la selecciona, pero sus recomendaciones no se vuelven límites reglamentarios. La obligación de seguridad y su método también se representa como regla del perfil que corresponda a la instalación.
- Las referencias internacionales se seleccionan por alcance, no como una fuente universal: IEEE Std 80 para sistemas de puesta a tierra de subestaciones de c.a.; IEC 60364-5-54 para arreglos de puesta a tierra y conductores de protección en instalaciones de baja tensión; IEC 61936-1 como referencia de requisitos para instalaciones de potencia de más de 1 kV en c.a.; e IEC 62305-3 cuando el alcance incluye protección contra el rayo. La edición, estado, cláusula aplicable y compatibilidad con el proyecto se verifican al curar cada recomendación.
- Las recomendaciones IEEE/IEC solo llenan vacíos de orientación de diseño. La salida las presenta como propuestas técnicas revisables, junto con procedencia y supuestos; no las incorpora silenciosamente al conjunto factible ni las usa para certificar cumplimiento. Si falta una exigencia obligatoria aplicable para evaluar seguridad, no se reporta el diseño como conforme.
- El motor de restricciones consume reglas normalizadas (predicados geométricos, límites escalares, restricciones discretas y verificaciones eléctricas); no conoce códigos de país. La instancia resuelta para una corrida incluye jurisdicción, tipo de instalación, identificador y versión del perfil, reglas seleccionadas, datos usados, resultados de aplicabilidad y evidencia. Cuando no se puede decidir si una regla aplica, la variable dependiente no se optimiza hasta resolverlo.
- OP-05 debe bloquear zonas no intervenibles y elementos enterrados conocidos. Debe exigir una red conductora conectada: una zona permitida aislada necesita conductor/enlace explícito o se modela como sistema independiente y se evalúa por separado.
- Las opciones comerciales son discretas y los cambios geométricos pueden alterar topología y factibilidad. OP-06 empieza con búsqueda de vecindad discreta (búsqueda local con reinicios; ampliar a VNS si hace falta) sobre configuraciones construibles, con el evaluador eléctrico como filtro de factibilidad/costo. No conviene aplicar IPOPT a variables redondeadas: redondeos y cambios de conectividad producen discontinuidades. IPOPT puede considerarse después para subproblemas continuos de topología fija; cualquier diseño aceptado se discretiza y vuelve a evaluar antes de guardarse.
- La entidad de alternativa conserva cada solución seleccionada junto con la corrida, materiales/longitudes exactas, costo desglosado, métricas eléctricas, cumplimiento y fuentes/ediciones de restricciones. Así la recomendación se reproduce aunque cambien catálogo o reglamento.

## Riesgos propios

| Riesgo | Mitigación |
|---|---|
| Máximos de tensión no suaves y que cambian de lugar | Restricciones por separado; SV-08 devuelve ubicación; verificación en rejilla fina |
| Óptimos locales | Multistart (OP-09) y comparación con búsqueda evolutiva |
| Costos incompletos dan recomendaciones irreales | Catálogo versionado (OP-03, OP-08); el reporte declara qué costos no incluye |
| Optimizar sobre un solver con malla gruesa y aceptar un diseño que falla en malla fina | OP-07, revalidación obligatoria |
| El optimizador explota errores del solver (singularidades, discretización) | SV-01…SV-05 deben estar cerrados antes de OP-09 |
| Una versión optimizada se confunde con un diseño aprobado | La salida queda como borrador; la aprobación es de un profesional competente (BL-01, visión de producto PR) |

## Orden recomendado

1. En paralelo con el solver: OP-01, OP-02, OP-03.
2. OP-04 → OP-05 → OP-06 → OP-07: **primer entregable**, una optimización de costo sujeta a seguridad sobre una malla existente.
3. OP-09 → OP-10 → OP-12 → OP-13.
4. Decidir OP-14/15 con los datos de OP-06 y OP-09.
