# Paquete de revisión independiente — motor de potencial SPAT

Generado el 2026-10-04 con `validation/review_report.py`, solver 3.0.0. Regenerar después de cualquier cambio del motor o de `reference_cases.json`.

## Alcance que se revisa

Motor cuasiestático de electrodos cilíndricos delgados en suelo homogéneo o de dos capas horizontales, isotrópico y semiinfinito, con metal ideal equipotencial por grupo. No cubre suelo de n capas, impedancia del conductor, reparto de corriente de falla, capa superficial ni criterios tolerables normativos. La revisión aprueba o rechaza el motor solo para ese alcance.

## Resultado: 40 de 44 comprobaciones dentro de tolerancia; 4 desviaciones conocidas investigadas

| Caso | Magnitud | Motor | Referencia | Desviación | Tolerancia propuesta | Estado | Fuente |
|---|---|---|---|---|---|---|---|
| single_rod | resistance_ohm (rod) | 33.29 | 33.4927 | -0.61 % | ±2 % | pasa | dwight_1936 |
| horizontal_wire | resistance_ohm (wire) | 8.474 | 8.535 | -0.72 % | ±2 % | pasa | dwight_1936 |
| two_rods_bonded | resistance_ohm (pair) | 17.44 | 17.5208 | -0.49 % | ±2 % | pasa | dwight_1936 |
| two_rods_coupled_groups | group_potential_v (rod_a) | 32.55 | 32.7182 | -0.51 % | ±2 % | pasa | dwight_1936 |
| two_rods_coupled_groups | group_potential_v (rod_b) | -15.12 | -15.1974 | -0.53 % | ±2 % | pasa | dwight_1936 |
| floating_rod | group_potential_v (floating) | 1.545 | 1.549 | -0.23 % | ±3 % | pasa | dwight_1936 |
| floating_rod | group_potential_v (driven) | 33.33 | 33.4927 | -0.50 % | ±2 % | pasa | dwight_1936 |
| ieee80_annex_h_grid1 | resistance_ohm (grid) | 1 | 1 – 1.01 | +0.00 % | ±2.5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid1 | T1 corner-mesh centre | 195.8 | 194.9 – 200.9 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid1 | T3 worst touch inside the grid | 203.7 | 202.7 – 209 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid1 | S1 grid corner, 1 m outward diagonal | 91.25 | 87.2 – 89.3 | +2.19 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid1 | S1 regression against converged value | 91.25 | 91.24 | +0.01 % | ±0.5 % | pasa | spat_convergence_2026_10_04 |
| ieee80_annex_h_grid2 | resistance_ohm (grid) | 0.9172 | 0.917 – 0.92 | +0.00 % | ±2.5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid2 | T1 corner-mesh centre | 145.7 | 145.4 – 150.2 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid2 | T3 worst touch inside the grid | 150 | 149.6 – 154 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid2 | S1 grid corner, 1 m outward diagonal | 69.96 | 70.7 – 79.3 | -1.05 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid2 | S1 regression against converged value | 69.96 | 69.78 | +0.25 % | ±0.5 % | pasa | spat_convergence_2026_10_04 |
| ieee80_annex_b_example1 | resistance_ohm (grid) | 2.648 | 2.67 | -0.84 % | ±5 % | pasa | ieee80_2013_annex_b |
| ieee80_annex_b_example1 | worst touch inside the grid | 969.3 | 984.3 | -1.52 % | ±5 % | pasa | ieee80_2013_annex_b |
| ieee80_annex_h_grid3 | resistance_ohm (grid) | 0.9663 | 0.97 – 0.972 | -0.38 % | ±2.5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid3 | T1 corner-mesh centre | 261.5 | 261 – 268.5 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid3 | T3 worst touch inside the grid | 262.8 | 262.5 – 269.7 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid3 | S1 grid corner, 1 m outward diagonal | 100.7 | 101.9 – 117 | -1.13 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid3 | S1 regression against converged value | 100.7 | 100.47 | +0.28 % | ±0.5 % | pasa | spat_convergence_2026_10_04 |
| ieee80_annex_h_grid4 | resistance_ohm (grid) | 0.9653 | 0.96 – 0.97 | +0.00 % | ±2.5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4 | transferred voltage grid to fence | 310 | 309.2 – 312.4 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4 | T1 corner-mesh centre | 260.7 | 259.7 – 263.6 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4 | T2 grid corner | 129.1 | 127.1 – 130.1 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4 | T3 worst touch inside the grid | 261.9 | 261.1 – 264.9 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4 | T4 fence conductor corner | 49.21 | 49.9 – 51.1 | -1.38 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4 | S1 grid corner, 1 m outward diagonal | 95.72 | 97 – 97.4 | -1.31 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4 | S2 fence corner, 1 m outward diagonal | 39.57 | 37.4 – 38.1 | +3.87 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid4_fence_alone | resistance_ohm (fence) | 1.679 | 1.6 – 1.62 | +3.63 % | ±2.5 % | desviación conocida | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid5 | resistance_ohm (grid) | 0.8075 | 0.81 | -0.31 % | ±2.5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid5 | GPR | 601.4 | 602.7 – 606.4 | -0.22 % | ±2.5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid5 | worst touch inside the outline | 128.5 | 131.6 – 138.1 | -2.34 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid5 | worst step within 1 m outside the outline | 90.04 | 83 – 90.7 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid6 | resistance_ohm (grid) | 1.427 | 1.42 – 1.43 | +0.00 % | ±2.5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid6 | GPR | 1063 | 1054.4 – 1068.2 | +0.00 % | ±2.5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid6 | worst touch inside the outline | 136.4 | 134.4 – 140.2 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_h_grid6 | worst step within 1 m outside the outline | 85.42 | 77.4 – 99.2 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h_layered |
| ieee80_annex_b_exhibit1 | resistance_ohm (grid) | 1.137 | 1.353 | -15.94 % | ±5 % | desviación conocida | ieee80_2013_annex_b_exhibit1 |
| ieee80_annex_b_exhibit1 | mesh voltage, % of GPR | 43.65 | 49.66 | -12.11 % | ±5 % | desviación conocida | ieee80_2013_annex_b_exhibit1 |
| ieee80_annex_b_exhibit1 | corner step voltage, % of GPR | 14.81 | 18.33 | -19.22 % | ±5 % | desviación conocida | ieee80_2013_annex_b_exhibit1 |

La desviación es 0 cuando el valor cae dentro del rango publicado; si no, se mide contra el extremo más cercano.

## Fuentes

- **ieee80_2013_annex_h_layered** — IEEE Std 80-2013 incl. Cor 1-2015, Annex H.3, Tables H.7 to H.10 (Grids 3 to 6): range of results from CDEGS, ETAP and WinIGS. Método: commercial method-of-moments grounding programs, two-layer soil. Versión: IEEE Std 80-2013/Cor 1-2015; values and geometry assumptions transcribed from github.com/jacho35/protectionpro testing/earth-grid-validation/validate.py at commit 557027e415936e9fb1738997f1cccd49767988de (2026-10-04).
- **ieee80_2013_annex_b_exhibit1** — IEEE Std 80-2013, Annex B, Exhibit 1 (square grid with rods in two-layer soil): computer results from EPRI TR-100622. Método: EPRI SGSYS-type method-of-moments program, two-layer soil. Versión: IEEE Std 80-2013; values and geometry assumptions transcribed from github.com/jacho35/protectionpro testing/earth-grid-validation/validate.py at commit 557027e415936e9fb1738997f1cccd49767988de (2026-10-04).
- **dwight_1936** — H. B. Dwight, 'Calculation of resistances to ground', AIEE Transactions, vol. 55, pp. 1319-1328, 1936; reproduced in IEEE Std 142-2007 (Green Book), Table 4-5. Método: closed form, average-potential method with uniform leakage current. Versión: IEEE Std 142-2007.
- **ieee80_2013_annex_h** — IEEE Std 80-2013 incl. Cor 1-2015, Annex H.3, Tables H.5 and H.6 (Grids 1 and 2): range of results from CDEGS, ETAP and WinIGS. Método: commercial method-of-moments grounding programs, uniform soil. Versión: IEEE Std 80-2013/Cor 1-2015; values transcribed from github.com/jacho35/protectionpro testing/earth-grid-validation/validate.py at commit 557027e415936e9fb1738997f1cccd49767988de (2026-10-04).
- **spat_convergence_2026_10_04** — Internal convergence study of this engine: IEEE 80 Annex H Grids 1, 2 and 3 with uniform 1, 0.5 and 0.25 m segments (840-3980 segments) and Richardson extrapolation to zero segment length (Grid 1 S1 91.24 V, order 2.57; Grid 2 S1 69.78 V, order 1.91; Grid 3 S1 100.47 V, order 1.99). Método: Galerkin method of moments, solver 2.0.0 (Grid 1) and 3.0.0 (Grids 2-3); Grid 1 cross-checked with a midpoint-collocation variant. Versión: solver 2.0.0/3.0.0, 2026-10-04; not an independent reference.
- **ieee80_2013_annex_b** — IEEE Std 80-2013, Annex B, Example 1 (square grid without rods): computer result from EPRI TR-100622. Método: EPRI SGSYS-type method-of-moments program. Versión: IEEE Std 80-2013; values transcribed from github.com/jacho35/protectionpro testing/earth-grid-validation/validate.py at commit 557027e415936e9fb1738997f1cccd49767988de (2026-10-04).

## Desviaciones conocidas y notas

- **single_rod / resistance_ohm:** R = rho/(2 pi L) (ln(4L/a) - 1); Dwight assumes uniform leakage, so method-of-moments results sit slightly below
- **horizontal_wire / resistance_ohm:** R = rho/(4 pi L)(ln(4L/a) + ln(4L/s) - 2 + s/(2L) - s^2/(16L^2) + s^4/(512L^4)), wire length 2L, s twice the depth
- **two_rods_bonded / resistance_ohm:** two rods, s > L: R = rho/(4 pi L)(ln(4L/a) - 1) + rho/(4 pi s)(1 - L^2/(3 s^2) + 2 L^4/(5 s^4))
- **two_rods_coupled_groups / group_potential_v:** V_A = R_s I_A + R_m I_B with R_s single-rod and R_m = rho/(2 pi s)(1 - L^2/(3 s^2) + 2 L^4/(5 s^4)) from the two-rod formula
- **two_rods_coupled_groups / group_potential_v:** V_B = R_s I_B + R_m I_A
- **floating_rod / group_potential_v:** transferred potential V_B = R_m I_A (mutual resistance from the two-rod formula)
- **floating_rod / group_potential_v:** the floating rod carries no net current, so the driven rod stays close to its isolated resistance
- **ieee80_annex_h_grid1 / S1 grid corner, 1 m outward diagonal:** Known deviation of about +2 %: the engine converges to 91.24 V (Richardson extrapolation, observed order 2.6, from 1, 0.5 and 0.25 m segments; Galerkin and collocation agree within 0.3 %). With 3.5-7 m segments it reproduces 86-89 V, so the published range is most likely under-resolved at the corner, where leakage current concentrates. Not an engine defect; pending confirmation of the programs' segmentation (IEEE 80-2013 Table H.5) or a fine-segment run in a commercial tool.
- **ieee80_annex_h_grid1 / S1 regression against converged value:** Self-consistency check, not independent validation: detects solver or segmentation changes that move the converged corner step voltage. With the case's graded segments (452) the engine is within 0.02 % of the extrapolated value; uniform 1 m pieces (840) are 0.3 % below.
- **ieee80_annex_h_grid2 / S1 grid corner, 1 m outward diagonal:** The converged value (69.78 V, see the regression check) lies about 1.3 % below the published range. Uniform segments give 78.1 V at 7 m and 70.9 V at 1 m, so, as for Grid 1 S1, the published spread most likely reflects corner under-resolution in the programs. Within tolerance.
- **ieee80_annex_h_grid2 / S1 regression against converged value:** Self-consistency check, not independent validation. With the case's graded segments (612) the engine is about 0.25 % above the extrapolated value; uniform 1 m pieces (1000) are 1.6 % above.
- **ieee80_annex_b_example1 / resistance_ohm:** older single-program result; wider tolerance than the Annex H range
- **ieee80_annex_h_grid3 / S1 grid corner, 1 m outward diagonal:** The converged value (100.47 V, see the regression check) lies about 1.4 % below the published range, the same corner under-resolution pattern as Grids 1 and 2 (uniform 3.5 m segments give 109.6 V, inside the range). Within tolerance.
- **ieee80_annex_h_grid3 / S1 regression against converged value:** Self-consistency check, not independent validation. With the case's graded segments (692) the engine is about 0.25 % above the extrapolated value; uniform 1 m pieces (1000) are 1.8 % above.
- **ieee80_annex_h_grid4_fence_alone / resistance_ohm:** Known deviation of about +3.6 %, driven by the fence-conductor depth, which the figure leaves open and is assumed 0.5 m: the same model gives 1.632 ohm with the ring at 0.762 m and 1.597 ohm at 1.0 m (inside the range). With 0.5 m the in-grid fence quantities (transfer, T4, S2) stay within 5 %. Not an engine defect; confirm the depth in IEEE 80-2013 Annex H before tightening this check.
- **ieee80_annex_b_exhibit1 / resistance_ohm:** Known deviation (-12 to -19 %), also unexplained by an independent solver (protectionpro BACKLOG: 'Exhibit 1 unexplained'). Without rods the engine gives 1.4112 ohm against 1.4102 ohm from that solver. With rods shortened to 4 m (not reaching the 100 ohm-m layer) it reproduces the published figures (1.357 ohm, 49.3 %, 17.3 %), so the EPRI result most likely did not model the 9.144 m rods penetrating the lower layer. Rods crossing the interface are validated by Annex H Grids 3-6. Informative only.
- **ieee80_annex_b_exhibit1 / mesh voltage, % of GPR:** Known deviation (-12 to -19 %), also unexplained by an independent solver (protectionpro BACKLOG: 'Exhibit 1 unexplained'). Without rods the engine gives 1.4112 ohm against 1.4102 ohm from that solver. With rods shortened to 4 m (not reaching the 100 ohm-m layer) it reproduces the published figures (1.357 ohm, 49.3 %, 17.3 %), so the EPRI result most likely did not model the 9.144 m rods penetrating the lower layer. Rods crossing the interface are validated by Annex H Grids 3-6. Informative only.
- **ieee80_annex_b_exhibit1 / corner step voltage, % of GPR:** Known deviation (-12 to -19 %), also unexplained by an independent solver (protectionpro BACKLOG: 'Exhibit 1 unexplained'). Without rods the engine gives 1.4112 ohm against 1.4102 ohm from that solver. With rods shortened to 4 m (not reaching the 100 ohm-m layer) it reproduces the published figures (1.357 ohm, 49.3 %, 17.3 %), so the EPRI result most likely did not model the 9.144 m rods penetrating the lower layer. Rods crossing the interface are validated by Annex H Grids 3-6. Informative only.

## Convergencia de discretización

Cambio relativo de cada magnitud respecto al refinamiento anterior.

**ieee80_annex_h_grid1** (segmentación graded; d = longitud de refinamiento)

| d | Segmentos | resistance_ohm | T1 corner-mesh centre | T3 worst touch inside the grid | S1 grid corner, 1 m outward diagonal | S1 regression against converged value |
|---|---|---|---|---|---|---|
| 4.0 m | 272 | 1.001 | 196.3 | 204 | 91.1 | 91.1 |
| 2.0 m | 356 | 1 (0.05 %) | 195.9 (0.20 %) | 203.8 (0.06 %) | 91.25 (0.17 %) | 91.25 (0.17 %) |
| 1.0 m | 452 | 1 (0.02 %) | 195.8 (0.08 %) | 203.7 (0.08 %) | 91.25 (0.00 %) | 91.25 (0.00 %) |
| 0.5 m | 592 | 1 (0.01 %) | 195.7 (0.04 %) | 203.4 (0.11 %) | 91.22 (0.03 %) | 91.22 (0.03 %) |

**ieee80_annex_h_grid2** (segmentación graded; d = longitud de refinamiento)

| d | Segmentos | resistance_ohm | T1 corner-mesh centre | T3 worst touch inside the grid | S1 grid corner, 1 m outward diagonal | S1 regression against converged value |
|---|---|---|---|---|---|---|
| 4.0 m | 372 | 0.9179 | 146.3 | 150.4 | 71.01 | 71.01 |
| 2.0 m | 496 | 0.9174 (0.06 %) | 145.9 (0.26 %) | 150.1 (0.18 %) | 70.19 (1.16 %) | 70.19 (1.16 %) |
| 1.0 m | 612 | 0.9172 (0.03 %) | 145.7 (0.11 %) | 150 (0.11 %) | 69.96 (0.33 %) | 69.96 (0.33 %) |
| 0.5 m | 792 | 0.9171 (0.01 %) | 145.6 (0.06 %) | 149.8 (0.10 %) | 69.9 (0.08 %) | 69.9 (0.08 %) |

**ieee80_annex_h_grid3** (segmentación graded; d = longitud de refinamiento)

| d | Segmentos | resistance_ohm | T1 corner-mesh centre | T3 worst touch inside the grid | S1 grid corner, 1 m outward diagonal | S1 regression against converged value |
|---|---|---|---|---|---|---|
| 4.0 m | 352 | 0.9686 | 262.9 | 264.2 | 102.4 | 102.4 |
| 2.0 m | 516 | 0.9669 (0.18 %) | 261.8 (0.41 %) | 263.2 (0.37 %) | 101.1 (1.28 %) | 101.1 (1.28 %) |
| 1.0 m | 692 | 0.9663 (0.06 %) | 261.5 (0.14 %) | 262.8 (0.14 %) | 100.7 (0.36 %) | 100.7 (0.36 %) |
| 0.5 m | 912 | 0.966 (0.03 %) | 261.3 (0.07 %) | 262.6 (0.08 %) | 100.7 (0.09 %) | 100.7 (0.09 %) |

## Preguntas para el revisor

1. ¿Son aceptables las tolerancias propuestas (±2–2,5 % en resistencia, ±5 % en tensiones; ±0,5 % en la regresión interna)?
2. Cotejar cada valor de las fuentes `ieee80_2013_annex_h`, `ieee80_2013_annex_h_layered`, `ieee80_2013_annex_b` y `ieee80_2013_annex_b_exhibit1` con una copia licenciada de IEEE Std 80-2013/Cor 1-2015, y los supuestos geométricos de cada caso con sus figuras; se transcribieron de un tercero.
3. ¿Se acepta la explicación de la desviación del paso S1 del Grid 1 (referencia sub-resuelta en la esquina), o se exige confirmarla con la Tabla H.5 o con una corrida fina en un programa comercial?
4. ¿Es adecuada la recomendación de segmentos de 1 m o menos cerca de varillas y esquinas?
5. ¿Se aceptan las desviaciones conocidas (cerca sola del Grid 4 por la profundidad supuesta del conductor; Exhibit 1 del Anexo B, cuya referencia parece no modelar las varillas que atraviesan la interfaz)?
6. ¿Es aceptable excluir los puntos a menos de 0,08 m de un electrodo que aflora (radio de pie de IEEE 80) en la búsqueda de paso y contacto?
7. ¿Hace falta algún caso adicional dentro del alcance (homogéneo y dos capas) antes de exponer resultados a usuarios?

## Dictamen

| Campo | Valor |
|---|---|
| Revisor | |
| Matrícula profesional | |
| Independencia respecto al desarrollo | |
| Fecha | |
| Commit revisado | |
| Dictamen (aprobado / aprobado con condiciones / rechazado) | |
| Tolerancias modificadas | |
| Condiciones u observaciones | |

Al aprobar, actualizar `review.status` en `reference_cases.json` y la fila de validación en `BACKLOG.md`.
