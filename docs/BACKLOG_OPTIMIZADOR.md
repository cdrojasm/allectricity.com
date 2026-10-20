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
| OP-01 | P0 | ⬜ | Indicador de utilización y restricciones | `Phi = max(Vs/Vs_lim, Vt/Vt_lim)` para reportar; para optimizar, restricciones de paso y contacto **por separado** (sin operador máximo). Los límites vienen de PE-09 y quedan registrados con norma y edición. | PE-09 |
| OP-02 | P0 | ⬜ | Generador paramétrico de geometría | Variables: ancho, alto, posición/espaciado de conductores, longitud de varillas, extensión perimetral. Topología constante, determinista, sin segmentos degenerados (longitud mínima 5 radios), compatible con el solver. | SV-09, BL-19 |
| OP-03 | P0 | ⬜ | Catálogo de costos y costo de material | Catálogo editable por proyecto y moneda, con vigencia y unidades; costo por longitud, material, sección (la mínima viene del cálculo térmico), tipo y número de varillas. Desglose y trazabilidad. Comparte la lista de materiales con BL-21. | BL-21 |
| OP-04 | P0 | ⬜ | Evaluador unificado de diseño | `DesignParameters → Geometría → Solver → Costo → Restricciones` con salida `{Rg, Vs, Vt, Cost, Feasible, ConstraintViolations, NumericalStatus}`. Cuenta evaluaciones y las registra. | SV-12, SV-08, OP-01…03 |
| OP-05 | P0 | ⬜ | Restricciones geométricas y constructivas | Regiones permitidas poligonales, zonas de exclusión (cimentaciones, servicios, vías), separaciones mínimas, profundidades admisibles, longitudes comerciales. Geometría inválida se detecta y se reporta; no se envía al solver. | OP-02, BL-19 |
| OP-06 | P0 | ⬜ | Experimento base con búsqueda local o evolutiva | Sobre una malla existente (La Esperanza, `docs/datos_prueba_agente`): diseño factible de menor costo con topología fija, comparado contra el diseño inicial, con presupuesto de evaluaciones, semilla y repetibilidad. **Criterio de continuidad: si esto ya da la mayor parte de la ganancia, IPOPT se pospone.** | OP-04, OP-05 |
| OP-07 | P0 | ⬜ | Revalidación final y versionado | Toda solución se recalcula con el solver completo y malla fina; si difiere de la evaluada más allá de tolerancia, se rechaza. Se guarda como versión nueva del artefacto con traza del optimizador y de la semilla. | OP-06 |

### B. Optimización con restricciones (P1)

| Id | Prio | Estado | Feature | Criterio de aceptación | Depende de |
|---|---|---|---|---|---|
| OP-08 | P1 | ⬜ | Costo de instalación | Excavación, mano de obra, conexiones, perforaciones, movilización y dificultad del terreno, con supuestos trazables. | OP-03 |
| OP-09 | P1 | ⬜ | Mínimo costo sujeto a seguridad | Factibilidad verificada y costo detallado frente al diseño base. Multistart desde varios iniciales para reducir la dependencia de un óptimo local; se reporta la variación entre corridas. | OP-06, OP-07 |
| OP-10 | P1 | ⬜ | Exploración costo–margen (Pareto) | Resolver `min C` sujeto a `Phi ≤ α` para varios `α`; alternativas no dominadas, comparación gráfica y exportación. | OP-09 |
| OP-11 | P1 | ⬜ | Análisis de sensibilidad | Influencia de cada parámetro sobre costo, `Vs` y `Vt` (diferencias finitas al inicio); orienta qué variables vale la pena optimizar. | OP-04 |
| OP-12 | P1 | ⬜ | Ejecución como job asíncrono | Lanzar, consultar y cancelar optimizaciones por Celery; el agente solo configura y lee resultados. Registro de decisiones y auditoría (SV-15). | OP-07, PE-17 |
| OP-13 | P1 | ⬜ | Comparación de alternativas y reporte | Costo, `Rg`, `Vs`, `Vt`, margen y complejidad constructiva; reporte con entradas, hipótesis, restricciones, presupuesto, alternativas y advertencias. | OP-10, BL-21, PE-24 |

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
