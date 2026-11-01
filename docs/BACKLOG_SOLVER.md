# Backlog del solver (motor de potencial)

> Ids `SV-NN`. Complementa `services/potential_engine/BACKLOG.md` (`PE-NN`, estado histórico del motor) y
> `docs/BACKLOG.md` (`BL-NN`, backlog técnico del producto). Cada fila indica qué `PE`/`BL` extiende para no
> duplicar. El optimizador tiene su propio backlog: [BACKLOG_OPTIMIZADOR.md](BACKLOG_OPTIMIZADOR.md).
> Origen: roadmap «Grounding Solver v0.1» + Epic G, ajustado contra el código el 2026-10-16.

## Contrato entre solver y optimizador

- El solver **calcula física**; no conoce costos, restricciones constructivas ni algoritmos de optimización.
- El optimizador consume el solver solo por la interfaz de evaluación (`SV-12`) y, más adelante, sensibilidades (`SV-16`).
- Todo resultado lleva versión de protocolo/solver, hash de entradas y diagnóstico numérico (ya cumplido, PE-04).

## Punto de partida verificado

| Capacidad | Estado | Referencia |
|---|---|---|
| Suelo homogéneo, 2 capas y 1–8 capas horizontales | ✅ (revisión independiente postergada) | PE-06, PE-08 |
| Autotérmino en forma cerrada + cuadratura graduada Gauss-Legendre 8 con línea analítica cerca de singularidades | ✅ base; sin estimador de error ni clasificación explícita | `src/main.cpp` |
| LU denso ≤ 1 500 segmentos, GMRES ≤ 4 000; diagnóstico de residuo, condición y balance | ✅ | PE-03, PE-16 |
| Convergencia de discretización, segmentación graduada, incertidumbre numérica | ✅ | PE-02, PE-15 |
| Varillas que cruzan interfaces (se parten) | ✅ | PE-06 |
| Varios grupos acoplados por el suelo, potencial por grupo | ✅ en el motor; el modelo de artefacto aún asocia una malla a un edificio | PE-04 |
| Tolerables IEEE 80-2013, `D_f`, `S_f`, conductor térmico | ✅ en backend | PE-09, PE-11, BL-04 |
| Caché de cualquier nivel | ❌ ninguno. Un proceso por cálculo; la matriz se ensambla y factoriza cada vez | README del motor |

## Backlog

Prioridades: **P0** fiabilidad o prerrequisito del optimizador · **P1** alto valor · **P2** condicionado a datos · **P3** investigación.

### A. Fiabilidad numérica y validación

| Id | Prio | Estado | Feature | Criterio de aceptación | Extiende |
|---|---|---|---|---|---|
| SV-01 | P0 | ◐ | Suite de referencia con error registrado y regresión en CI | Casos homogéneo, 2 capas, ≥3 capas, geometrías simples y complejas; fuente, supuestos y error relativo registrados por caso; falla el CI si el error se degrada más que la tolerancia. Incluye `Vs`/`Vt`, no solo `Rg`. La revisión independiente (PE-01) sigue siendo la puerta para declarar «validado». | PE-01, PE-08 |
| SV-02 | P0 | ✅ 2026-10-16 | Pruebas de invariancia multicapa | Capas de igual ρ ≡ homogéneo; capas adyacentes idénticas fusionables; espesor → 0 elimina la capa; capa superior muy profunda ≈ semiespacio; escalado uniforme de ρ escala `Rg` y tensiones. Hecho en `tests/infrastructure/test_potential_engine_invariance.py`, que además cubre escalado geométrico, traslación, rotación, espejo y orden/sentido de segmentos en suelo homogéneo, de 2 capas y de n capas. Hallazgo: en suelo homogéneo girar la malla cambia `R` en 6e-6 y las corrientes por segmento en 2e-4; en suelo estratificado, por debajo de 1e-6. | PE-08 |
| SV-03 | P0 | ✅ 2026-10-19 | Clasificación determinista de interacciones | C++ clasifica self, shared endpoint, T, crossing, near y separated con tolerancia `1e-6` de la longitud menor; reporta también degenerados y pares cerca de interfaces. Cuenta pares no ordenados incluyendo auto-pares, con la misma regla Python; los 34 casos de SV-04 verifican conteos exactos en ambos lados. La clasificación elige cuadratura adaptativa para interacciones cercanas y GL8 fijo para pares separados sin imagen próxima. Además, reusa por reciprocidad las entradas de matriz transpuestas cuando ambos alambres tienen el mismo radio; radios distintos conservan los cálculos dirigidos. El método informa ambas rutas y solver 3.4.0. 261 pruebas de singularidad, potencial, invariancia y kernel multicapa pasan. Perfil macOS arm64 contra base SV-06, 752 segmentos/8 capas: ensamblaje de 2,561 a 656 ms (−74 %), total de 2,631 a 722 ms (−73 %); con 728 segmentos/4 capas: ensamblaje de 2,155 a 539 ms (−75 %). | `main.cpp` |
| SV-04 | P0 | ✅ 2026-10-16 | Suite de regresión de singularidades | Un segmento; colineales; perpendiculares; extremo común; paralelos muy próximos; horizontal–varilla; electrodos cerca de interfaz; contrastes extremos de ρ. Métricas: error absoluto/relativo, convergencia, sensibilidad a tolerancias, tiempo. Hecho en `test_potential_engine_singularities.py` contra un solver de Galerkin independiente (`galerkin_reference.py`, scipy/QUADPACK, verificado a 1e-15 contra integración doble de fuerza bruta); 34 casos: 14 en suelo homogéneo y 4 contrastes de dos capas (hasta |K| = 0,905), también con el kernel de n capas. Cada caso tiene una cota de regresión y un objetivo de 1e-5 con control de trinquete (solo puede mejorar): ver SV-05. | SV-03 |
| SV-05 | P0 | ✅ 2026-10-19 | Cuadratura cercana adaptativa con estimador de error | Gauss-Legendre 8 compara un panel con dos medios paneles; refina localmente hasta la tolerancia relativa configurada (1e-9 por defecto, tolerancia absoluta por panel 1e-12) o falla tras 16 niveles con evaluaciones reportadas en el error. La tolerancia configurable (1e-12–1e-4) y los diagnósticos `quadrature_tolerance`, `quadrature_evaluations`, `quadrature_refinements`, `quadrature_max_depth`, `quadrature_converged` se exponen por cliente y protocolo. Medición contra Galerkin independiente: 107 checks de singularidades pasan; las 34 geometrías cumplen 1e-5 en resistencia y corriente, error máximo 5,39e-8 (K=+0,905, varilla que cruza interfaz). En el subconjunto de precisión actual, 34 casos tardan 4,40 s frente a 4,66 s con HEAD (−5,6 %, mismo equipo). | SV-03, SV-04 |
| SV-06 | P0 | ✅ 2026-10-19 | Perfil de rendimiento por fase | `make potential-engine-profile` construye y mide 12 combinaciones (suelos homogéneo, 2, 4 y 8 capas; mallas de 10, 20 y 40 m; 100 puntos), imprime y guarda las trazas JSON. DIAG añade kernel, ensamblaje, factorización, solve, estimación de condición, evaluación de puntos, duración total y RSS pico. Medición macOS arm64: con 752 segmentos/8 capas, ensamblaje 2,561 s y total 2,631 s en base; después de clasificación y reuso recíproco, 656 ms y 722 ms (−74 % y −73 %). Trazas: `/tmp/grounding-potential-engine-profile.json` y `/tmp/grounding-potential-engine-profile-symmetric.json`. **Puerta de todos los cachés (A→D).** | PE-16 |
| SV-07 | P1 | ✅ 2026-10-19 | Prueba de contrato Python/C++ | `test_potential_engine_protocol_contract.py` cubre las tres líneas de suelo, las extensiones de tolerancia y compatibilidad con solicitudes SPAT-POTENTIAL-3 antiguas; comprueba campos de respuesta y diagnósticos requeridos; verifica rechazo idéntico de tolerancias inválidas; y compara límites numéricos compartidos entre constantes Python y C++. 7 checks pasan. | PE-18 |
| SV-08 | P1 | ✅ 2026-10-19 | Búsqueda y localización de máximos de `Vs`/`Vt` | `artifact_potential._field` refina localmente los máximos; informa ubicación de contacto y extremos de paso a 1 m, y excluye obstáculos/áreas no intervenibles. Pruebas focalizadas: `test_artifact_potential.py` pasó dentro de Docker. | PE-09, PE-23 |
| SV-22 | P1 | ⬜ | Validador por elementos finitos axisimétricos | Script opcional en `services/potential_engine/validation/` (scikit-fem, FEniCSx o Elmer con Gmsh, en un entorno aparte) que resuelve la ecuación de Laplace con cilindros de radio real para varilla vertical, anillo y varilla más anillo, en suelo homogéneo, de 2 capas y de 3 a 5 capas, incluidas varillas que cruzan interfaces. Compara `R` y potencial superficial con el motor y **cuantifica el error del modelo de hilo delgado** (varillas gruesas o cortas), que ni mi referencia ni el motor miden porque comparten el modelo. Primera comprobación: hemisferio, `R = ρ/2πa`. Árbitro si se cambia el tratamiento del radio o la forma de la corriente. | PE-01, PE-08 |
| SV-23 | P1 | ⬜ | Referencia externa para 3 a 8 capas | Casos publicados con resultados de CDEGS u otro software industrial (artículos con tablas) añadidos a `reference_cases.json` con fuente y tolerancia, o licencia de evaluación de CDEGS/XGSLab. GroundCalc se descartó como referencia precisa (sección de preguntas abiertas). | PE-01 |

### B. Modelo eléctrico de múltiples redes

| Id | Prio | Estado | Feature | Criterio de aceptación | Extiende |
|---|---|---|---|---|---|
| SV-09 | P0 | ✅ 2026-10-19 | Desacoplar edificio, malla y electrodo en el artefacto | Contrato 2.0 separa edificios, redes y electrodos con geometría independiente y vínculos muchos-a-muchos validados. El worker evalúa cada red/electrodo con SV-12 y agrupa resultados por edificio; artefactos 1.0 mantienen su flujo. Sin conectividad eléctrica ni reparto conjunto de corriente, que corresponden a SV-10/11. | BL-19, PE-14 |
| SV-28 | P1 | ⬜ | Validar varillas de longitudes distintas | En geometría 2.0, cada varilla puede declarar `length_m`; si se omite, hereda `geometry.rod_length_m`. Confirmar y cubrir con pruebas que validación, persistencia, cálculo eléctrico y trazas conservan y usan la longitud efectiva de cada varilla, incluso cuando una red combina varias longitudes y estas cruzan distintas capas del suelo. La optimización puede variar cada longitud individual bajo límites constructivos; el solver solo recibe y evalúa la geometría resultante. | SV-09, OP-02, OP-05 |
| SV-10 | P1 | ◐ | Redes independientes, conectividad ideal y conexiones de impedancia finita | Implementado parcialmente en solver 3.5.0 / protocolo 4: bonos ideales contraen grupos equipotenciales; resistencias lumped entre grupos se resuelven con Laplaciano de conductancias y corriente de enlace firmada; se comprueba KCL nodal. La resistencia longitudinal puede aproximarse hoy creando grupos por celda y resistores entre celdas. Pendiente: derivar esa topología/resistencia desde artefactos 2.0 y comparar automáticamente contra una solución nodal independiente. | BL-10, PE-12 |
| SV-11 | P1 | ◐ | Escenarios de inyección múltiples y potenciales transferidos | Parcial en artefactos 2.0: recibe inyecciones firmadas por entidad y escenario, resuelve la topología conjunta vía SV-10/13, registra potenciales referidos a tierra remota, corrientes de enlace y balance por grupo; calcula diferencias transferidas y máximos de toque/paso sobre puntos de superficie accesibles. Las pruebas locales verifican superposición, balance, ley de Ohm, signo de transferencia y convergencia del raster 1→0,25 m en un caso de alambre pequeño (`test_artifact_v2_calculation.py`). Las corrientes ya deben incluir reparto de falla y decremento; el modelo no los infiere. Pendiente: referencia física verdaderamente independiente, refinamiento local SV-08 para máximos conjuntos y cobertura de contrato/API. | SV-10, SV-13 |

### C. Interfaz hacia el optimizador y el agente

| Id | Prio | Estado | Feature | Criterio de aceptación | Extiende |
|---|---|---|---|---|---|
| SV-12 | P0 | ✅ 2026-10-19 | Interfaz de evaluación estable | `solver_evaluation.evaluate(geometry, soil, injection_a, points, client, settings)` entrega cantidades, ubicaciones, diagnósticos, estado aproximado y potenciales solicitados; hash SHA-256 canónico e independiente del orden de puntos, hora y proceso. SV-09 la usa para evaluar redes/electrodos v2. Cobertura de contrato y adaptador contra el motor real. | PE-04, PE-17 |
| SV-13 | P1 | ◐ | Varias inyecciones por factorización | Solver 3.6.0 / protocolo 5: `calculate_scenarios` resuelve vectores nombrados con geometría, suelo y topología compartidos; ruta LU ensambla y factoriza una vez y verifica residual/KCL por vector. GMRES reutiliza la matriz ensamblada, pero ejecuta una iteración por RHS. Pendiente ampliar validaciones de estado/interferencia y valorar un precondicionador reutilizable para sistemas grandes. | — |
| SV-14 | P1 | ◐ | Modo de ejecución para lotes | Hoy `Popen` lanza un proceso por cálculo. Si SV-06 muestra que el arranque o el ensamblado repetido dominan, ofrecer proceso persistente (pipes o gRPC) o lote en una sola invocación. **No se integra sin SV-24 a SV-27.** | README del motor |
| SV-15 | P1 | ⬜ | Auditoría de cálculo completa | Versión del solver, configuración, entradas, escenarios, resultados, estado de convergencia y fecha, ligados al artefacto versionado. La base ya está en PE-04; falta cubrir escenarios múltiples y optimización. | PE-04 |
| SV-16 | P2 | ⬜ | Sensibilidades `∂R/∂p`, `∂V/∂p` | Derivadas por método adjunto o diferenciación implícita, validadas contra diferencias finitas (error relativo documentado, detección de discontinuidades). `lu_solve_transpose` ya existe. Solo si OP-14 (IPOPT) se aprueba. | OP-14 |

### D. Reutilización de cálculo (todo condicionado a SV-06)

Regla: **ningún caché puede alterar resultados fuera de tolerancias verificadas**, y la clave incluye todas las dependencias físicas y numéricas. Comparación obligatoria: sin caché vs con caché vs referencia de mayor precisión. **Ningún caché ni el modo persistente (SV-14) se integra sin las pruebas de estado SV-24 a SV-27**: hoy cada cálculo corre en un proceso nuevo y la suite no puede ver errores que dependen del historial.

| Id | Prio | Estado | Feature | Condición de entrada | Notas |
|---|---|---|---|---|---|
| SV-17 | P1 | ⬜ | Caché de suelo (`SoilKernelContext`, L1) | SV-06 muestra que el ajuste de imágenes/TSVD pesa de forma apreciable | Inmutable; invalida al cambiar ρ, espesores o precisión; seguro en paralelo. Con un proceso por cálculo solo rinde si antes hay SV-14. |
| SV-18 | P2 | ⬜ | Tabulación o memoización de Green (L2) | La evaluación del kernel domina en SV-06 | Clave: modelo de suelo, `r`, `z`, `z'`, precisión. Cuantizar solo con error acotado y documentado. |
| SV-19 | P2 | ⬜ | Reutilización de factorización entre llamadas (L4) | Estudios de varias fallas sobre la misma geometría (SV-13 no basta) | Detección de matriz idéntica por hash. |
| SV-20 | P2 | ⬜ | Operador de observación `H` reutilizable (L5) | Escenarios múltiples con mismos puntos de observación | Control de memoria. |
| SV-21 | P3 | ⬜ | Actualización incremental de matriz y por bloques (Schur, Woodbury) | Solo si OP-16 (agregar electrodos) existe y SV-06 lo justifica | **Poco útil para optimización continua**: al mover `W`, `H` o espaciado casi todos los coeficientes cambian. Rinde al agregar electrodos o cambiar una varilla. Con rastreo de dependencias geométricas. |

### D2. Pruebas de estado (requisito de entrada de SV-14 y SV-17…SV-21)

Las pruebas actuales ejecutan cada cálculo en un proceso nuevo, así que **no detectarían** errores de caché ni de estado compartido: una clave que omite una dependencia (radio, precisión), estado que se arrastra entre llamadas o resultados que dependen del orden.

| Id | Prio | Estado | Prueba | Criterio de aceptación |
|---|---|---|---|---|
| SV-24 | P0 si hay caché | ⬜ | Consistencia caché frío frente a caliente | Para cada nivel de caché, el resultado con caché caliente coincide con el cálculo sin caché dentro de la tolerancia declarada (ADR-010), en homogéneo, 2 capas y n capas. Falla si cambia una dependencia sin cambiar la clave: radio, espesor, resistividad, profundidad, precisión. |
| SV-25 | P0 si hay proceso persistente | ⬜ | Secuencias en un mismo proceso | La misma entrada repetida y en distinto orden, e intercalada con entradas distintas, da resultados idénticos bit a bit o dentro de la tolerancia; no hay estado arrastrado entre llamadas ni crecimiento de memoria sin cota. |
| SV-26 | P1 | ⬜ | Consistencia de escenarios múltiples | Con SV-13: superponer escenarios resueltos con una factorización coincide con resolverlos por separado y con la reciprocidad `R_ij = R_ji`; el residuo se verifica por vector. |
| SV-27 | P1 | ⬜ | Resultados de referencia congelados | Salida completa (resistencia, corrientes, potenciales, diagnóstico) de un conjunto fijo de casos, guardada por versión del solver; cualquier diferencia debe explicarse. Regla explícita de cuándo se permite regenerarlos: solo con cambio de versión del solver y un registro en `PE-04`. |

### E. Fuera del núcleo actual (referencia)

Impedancia compleja en AC (PE-19), transitorios (PE-20), electrodos no cilíndricos (PE-25), suelo heterogéneo 3D (PE-27), mallas > 10 000 segmentos (PE-16). Se priorizan por demanda real, no por este documento.

| Id | Prio | Estado | Feature | Criterio de aceptación | Extiende |
|---|---|---|---|---|---|
| SV-29 | P2 | ⬜ | Modelar material mejorador localizado alrededor de varillas (p. ej., Favigel) | **Problema:** el suelo actual admite solo resistividad homogénea o capas horizontales infinitas; una zona cilíndrica de relleno alrededor de una varilla es una inclusión 3D finita y no puede representarse como otra capa horizontal ni como un cambio global de resistividad. **Contrato físico:** cada tratamiento declara la varilla asociada, longitud y radio/espesor de la zona tratada (incluida su variación axial si aplica), resistividad del material instalado en Ω·m y origen/condiciones de ese dato; el suelo anfitrión conserva su modelo existente. Aclarar si se admiten relleno anular, contacto imperfecto/interfaz, variación con profundidad y más de una varilla tratada. No inferir resistividad a partir del nombre comercial: exigir ficha/medición o declarar explícitamente un rango de escenario. **Método:** comparar una solución especializada axisimétrica FEM de varilla vertical con inclusión cilíndrica en suelo homogéneo y estratificado contra el modelo de hilo delgado actual; después escoger e integrar un método apto para geometría 3D (p. ej., Green/FEM acoplado o FEM local validado), sin reducirlo silenciosamente a un suelo equivalente. Mantener la ruta actual sin cambio cuando no haya tratamiento. **Validación y aceptación:** casos límite ρ_mejorador = ρ_suelo y radio tratado → radio de varilla recuperan el caso base; estudiar convergencia de malla/dominio y balance de corriente; comparar R y potencial superficial con referencia independiente y cuantificar diferencia frente a hilo delgado; cubrir varillas que cruzan interfaces, radios/longitudes y contrastes representativos; propagar incertidumbre de propiedades como escenarios o intervalo; guardar parámetros, unidades, fuente, versión del modelo y diagnóstico en la traza; rechazar datos incompletos o fuera del dominio validado con error explícito. No habilitarlo para resultados de seguridad hasta fijar tolerancias y revisión independiente. | SV-01, SV-22, PE-27 |

## Validez de los mecanismos de validación

Qué sigue valiendo si se implementa este backlog (revisado el 2026-10-16).

| Mecanismo | ¿Sigue valiendo? | Condición |
|---|---|---|
| Casos de IEEE 80 y Dwight (`reference_cases.json`) | Sí | Comparan con resultados publicados. Se vuelven a correr tras cada cambio. |
| Invariancias (SV-02) | Sí | Valen para cualquier numérica. Si el ruido baja (SV-05), apretar las tolerancias. |
| Convergencia por refinamiento | Sí | Volver a correr y re-medir tope de segmentos y memoria (PE-05). |
| Singularidades contra la referencia de Galerkin (SV-04) | Solo si el modelo físico no cambia | La referencia asume hilo delgado, corriente constante por segmento, grupo equipotencial y Galerkin. SV-05 no cambia el modelo (el trinquete exige más precisión). SV-10 (impedancia finita) sí lo cambia: hay que extender la referencia o usar una solución nodal independiente. Cambiar el radio o la forma de la corriente exige SV-22 como árbitro. |
| Cualquier prueba con caché o proceso persistente | No existe todavía | Ver SV-24 a SV-27. |

**Límite de todo lo anterior:** la referencia de Galerkin es independiente del motor en la numérica, no en el modelo. No demuestra que el hilo delgado sea correcto para varillas gruesas o cortas (SV-22) ni que coincida con software industrial en 3 a 8 capas (SV-23).

## Orden recomendado

1. **Fiabilidad:** SV-06 (perfil), SV-01, SV-02, SV-03 → SV-04 → SV-05.
2. **Prerrequisitos del optimizador:** SV-12, SV-08, SV-09 (con geometría v2).
3. **Redes y escenarios:** SV-10 → SV-13 → SV-11, y SV-15 en paralelo.
4. **Validación del modelo:** SV-22 (FEM axisimétrico) y SV-23 (referencia externa), en paralelo con 1 a 3.
5. **Rendimiento con datos:** SV-14 y los cachés SV-17…SV-21 solo si el perfil los pide, y solo con SV-24 a SV-27 listas.

## Preguntas abiertas

1. ¿Qué referencias industriales (CDEGS, ETAP, WinIGS) están disponibles para validar? Sin ellas, SV-01 se limita a IEEE 80 y literatura.
   - Contraste con GroundCalc (MATLAB/Octave, licencia MIT limitada que prohíbe incrustarlo en software comercial) el 2026-10-16, modo equipotencial, mallas de 20×16 m: `R` entre 1,2 % y 4,7 % por debajo del motor (homogéneo sin varillas −1,2 %; con 8 varillas −4,7 %; dos capas −2,1 %), estable al refinar. En un hilo aislado de 4 m se aleja de Dwight al refinar (−4,3 %), y con varillas que casi tocan la interfaz oscila (+44 %, +6 %, −0,6 %). Causa no confirmada; con radio 5 mm/√2 el hilo queda a +0,7 %, lo que apunta a su tratamiento del radio en el autotérmino. Conclusión: sirve como orden de magnitud, no como referencia al nivel de 1e-3 que necesitamos. No se incorporó al repositorio.
2. Tiempo de cálculo medido para 100, 1 000 y 5 000 segmentos en la CPU de producción (PE-05 pide re-medirlo).
3. ¿Se acepta pasar de proceso por cálculo a proceso persistente (SV-14)?
4. ¿Qué profundidades distintas por conductor horizontal admite hoy el motor? Está por confirmar contra el código antes de decidir geometría v2.
