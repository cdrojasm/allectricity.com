# Paquete de revisión independiente — motor de potencial SPAT

Generado el 2026-10-04 con `validation/review_report.py`, solver 2.0.0. Regenerar después de cualquier cambio del motor o de `reference_cases.json`.

## Alcance que se revisa

Motor cuasiestático de electrodos cilíndricos delgados en suelo homogéneo, isotrópico y semiinfinito, con metal ideal equipotencial por grupo. No cubre suelo estratificado, impedancia del conductor, reparto de corriente de falla, capa superficial ni criterios tolerables normativos. La revisión aprueba o rechaza el motor solo para ese alcance.

## Resultado: 18 de 18 comprobaciones dentro de tolerancia

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
| ieee80_annex_h_grid1 | T1 corner-mesh centre | 195.7 | 194.9 – 200.9 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid1 | T3 worst touch inside the grid | 203.4 | 202.7 – 209 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid1 | S1 grid corner, 1 m outward diagonal | 90.97 | 87.2 – 89.3 | +1.87 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid1 | S1 regression against converged value | 90.97 | 91.24 | -0.29 % | ±0.5 % | pasa | spat_convergence_2026_10_04 |
| ieee80_annex_h_grid2 | resistance_ohm (grid) | 0.9173 | 0.917 – 0.92 | +0.00 % | ±2.5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid2 | T1 corner-mesh centre | 145.8 | 145.4 – 150.2 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid2 | T3 worst touch inside the grid | 150 | 149.6 – 154 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_h_grid2 | S1 grid corner, 1 m outward diagonal | 70.88 | 70.7 – 79.3 | +0.00 % | ±5 % | pasa | ieee80_2013_annex_h |
| ieee80_annex_b_example1 | resistance_ohm (grid) | 2.648 | 2.67 | -0.84 % | ±5 % | pasa | ieee80_2013_annex_b |
| ieee80_annex_b_example1 | worst touch inside the grid | 969.3 | 984.3 | -1.52 % | ±5 % | pasa | ieee80_2013_annex_b |

La desviación es 0 cuando el valor cae dentro del rango publicado; si no, se mide contra el extremo más cercano.

## Fuentes

- **dwight_1936** — H. B. Dwight, 'Calculation of resistances to ground', AIEE Transactions, vol. 55, pp. 1319-1328, 1936; reproduced in IEEE Std 142-2007 (Green Book), Table 4-5. Método: closed form, average-potential method with uniform leakage current. Versión: IEEE Std 142-2007.
- **ieee80_2013_annex_h** — IEEE Std 80-2013 incl. Cor 1-2015, Annex H.3, Tables H.5 and H.6 (Grids 1 and 2): range of results from CDEGS, ETAP and WinIGS. Método: commercial method-of-moments grounding programs, uniform soil. Versión: IEEE Std 80-2013/Cor 1-2015; values transcribed from github.com/jacho35/protectionpro testing/earth-grid-validation/validate.py at commit 557027e415936e9fb1738997f1cccd49767988de (2026-10-04).
- **spat_convergence_2026_10_04** — Internal convergence study of this engine: IEEE 80 Annex H Grid 1 with 1, 0.5 and 0.25 m segments (840-3360 segments) and Richardson extrapolation to zero segment length. Método: Galerkin method of moments, solver 2.0.0; cross-checked with a midpoint-collocation variant. Versión: solver 2.0.0, 2026-10-04; not an independent reference.
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
- **ieee80_annex_h_grid1 / S1 regression against converged value:** Self-consistency check, not independent validation: detects solver changes that move the converged corner step voltage. At the case's 1 m segments the engine is 0.3 % below the extrapolated value.
- **ieee80_annex_b_example1 / resistance_ohm:** older single-program result; wider tolerance than the Annex H range

## Convergencia de discretización

Cambio relativo de cada magnitud respecto al refinamiento anterior.

**ieee80_annex_h_grid1**

| Segmento | Segmentos | resistance_ohm | T1 corner-mesh centre | T3 worst touch inside the grid | S1 grid corner, 1 m outward diagonal | S1 regression against converged value |
|---|---|---|---|---|---|---|
| 3.5 m | 240 | 1.001 | 196.4 | 204 | 89.62 | 89.62 |
| 1.75 m | 480 | 1 (0.06 %) | 195.9 (0.27 %) | 203.6 (0.22 %) | 90.51 (1.00 %) | 90.51 (1.00 %) |
| 1.0 m | 840 | 1 (0.03 %) | 195.7 (0.10 %) | 203.4 (0.09 %) | 90.97 (0.51 %) | 90.97 (0.51 %) |
| 0.7 m | 1200 | 1 (0.00 %) | 195.7 (0.02 %) | 203.4 (0.01 %) | 91.13 (0.17 %) | 91.13 (0.17 %) |

**ieee80_annex_h_grid2**

| Segmento | Segmentos | resistance_ohm | T1 corner-mesh centre | T3 worst touch inside the grid | S1 grid corner, 1 m outward diagonal |
|---|---|---|---|---|---|
| 3.5 m | 300 | 0.9188 | 147 | 151.1 | 74.94 |
| 1.75 m | 580 | 0.9178 (0.12 %) | 146.1 (0.60 %) | 150.3 (0.58 %) | 72.25 (3.58 %) |
| 1.0 m | 1000 | 0.9173 (0.05 %) | 145.8 (0.21 %) | 150 (0.21 %) | 70.88 (1.90 %) |
| 0.7 m | 1420 | 0.9172 (0.01 %) | 145.7 (0.06 %) | 149.9 (0.06 %) | 70.36 (0.73 %) |

## Preguntas para el revisor

1. ¿Son aceptables las tolerancias propuestas (±2–2,5 % en resistencia, ±5 % en tensiones; ±0,5 % en la regresión interna)?
2. Cotejar cada valor de las fuentes `ieee80_2013_annex_h` y `ieee80_2013_annex_b` con una copia licenciada de IEEE Std 80-2013/Cor 1-2015; se transcribieron de un tercero.
3. ¿Se acepta la explicación de la desviación del paso S1 del Grid 1 (referencia sub-resuelta en la esquina), o se exige confirmarla con la Tabla H.5 o con una corrida fina en un programa comercial?
4. ¿Es adecuada la recomendación de segmentos de 1 m o menos cerca de varillas y esquinas?
5. ¿Hace falta algún caso adicional dentro del alcance homogéneo antes de exponer resultados a usuarios?

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
