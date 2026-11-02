# OPT-014 / OPT-014B: refinamiento paramétrico de topologías élite

**Estado: implementado y evaluado; no activado. No es una mejora de optimización demostrada.**
La política oficial es ALNS puro (`DEFAULT_STRATEGY = "alns"` en `optimizer_topology_run.py`).

## Qué se construyó
`parametric_refinement.refine_rods` ajusta el largo de cada varilla de una topología élite con la búsqueda local
OP-06 (`search_discrete_local`, con el nuevo parámetro `start`). Los candidatos pasan por el mismo controlador de
fidelidad y el mismo presupuesto que el resto; lo confirmado compite por los puestos de finalista, que se validan
con L3 al final. Solo se ajustan largos de varilla (no profundidad ni material).

## Políticas (todas con el mismo tope de llamadas)
| Política | Estrategia | Estado |
|---|---|---|
| A. ALNS puro | `alns` | **Predeterminada** |
| B. Reserva fija del 25 % | `alns_refined` | Experimental, no recomendada |
| C. Oportunista (solo presupuesto sobrante) | `alns_opportunistic` | Experimental, sin efecto observado |
| D. Punto de control al 80 % | `alns_checkpoint` | Experimental, no recomendada |

D decide con una regla fija: si el incumbente mejoró en el último 25 % de las llamadas gastadas, el resto va a más
descensos desde los élites; si no, a refinamiento.

## Resultados (4 escenarios x 6 semillas = 24 pares, tope de 150 llamadas, mismas semillas iniciales)
| Política | Costo medio (M) | Llamadas usadas | vs ALNS (mejor/igual/peor) | Cambio de costo [IC95] |
|---|---|---|---|---|
| A | 5,802 | 148 | — | — |
| B | 5,965 | 116 | 3/10/11 (p=0,057) | +2,8 % [+1,2; +4,8] |
| C | 5,802 | 148 | 0/24/0 | 0,0 % |
| D | 5,884 | 128 | 3/14/7 (p=0,34) | +1,4 % [+0,4; +2,7] |

Datos completos y tabla por escenario: `services/potential_engine/validation/benchmark-refinement-policies-macos-arm64.json`
(reproducible con `make optimizer-benchmark ARGS='--strategies alns,alns_refined,alns_opportunistic,alns_checkpoint --seeds 6 --budget 150'`).

## Limitaciones
- **C no ejecutó ningún refinamiento en las 24 ejecuciones:** ALNS agotó el presupuesto (148 de 150 llamadas), así que no quedó sobrante. El resultado no dice nada sobre la calidad del refinador.
- **B y D dejaron presupuesto sin usar** (116 y 128 de 150 llamadas en promedio): el refinamiento satura rápido y esas llamadas no vuelven a la exploración.
- **D eligió refinar en las 24 ejecuciones** (ALNS ya estaba estancado en el último 25 %), y aun así costó más que seguir con ALNS.
- El refinamiento cambió el incumbente en 11 de 24 ejecuciones (B y D), pero esas mejoras no compensan las llamadas que quita a ALNS.
- Sin tiempo real comparado entre políticas más allá del promedio por ejecución; resultados en una sola plataforma.

## No evaluado (tarea futura)
Refinamiento con devolución al buscador del presupuesto no utilizado. Solo retomar OPT-014 con presupuestos
considerablemente mayores, topologías que ya no mejoran con ALNS, o un refinador sustancialmente más eficiente.
