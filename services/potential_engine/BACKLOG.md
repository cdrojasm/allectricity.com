# Backlog del motor de potencial de malla

## Estado actual

El motor C++17 (protocolo `SPAT-POTENTIAL-3`, solver 3.2.0) resuelve una distribución cuasiestática de potencial para segmentos rectos de electrodos cilíndricos ideales en suelo homogéneo, de dos capas (serie de imágenes) o de 1–8 capas horizontales (línea `n-layer`, kernel de reflexión generalizada con imágenes ajustadas). Usa LU denso hasta 1 500 segmentos y GMRES con matriz densa hasta 4 000 segmentos. Calcula acoplamiento por el suelo entre grupos, corriente por segmento, potencial de cada grupo y potencial superficial en puntos consultados, y devuelve diagnósticos numéricos y metadatos de trazabilidad. El cliente Python invoca el ejecutable con `subprocess.Popen`.

La validación del 2026-10-04 encontró que la versión 1 usaba ρ/(2πr) para una fuente enterrada y sobrestimaba resistencias y tensiones por un factor de 2. Todo resultado calculado con `SPAT-POTENTIAL-1` debe descartarse.

El resultado actual es exploratorio. No se debe usar para declarar cumplimiento IEEE/IEC, emitir diseños aprobados ni reemplazar mediciones o revisión profesional. IEEE Std 80 trata la seguridad de puesta a tierra de subestaciones AC; IEC 61936-1:2021 cubre instalaciones de potencia por encima de 1 kV AC. El alcance del modelo debe compararse con las normas y métodos aplicables al proyecto y su jurisdicción ([IEEE](https://standards.ieee.org/ieee/80/12145/), [IEC](https://webstore.iec.ch/en/publication/64490)).

## Backlog priorizado

| Id | Prioridad | Estado | Feature | Entregable y criterio de aceptación |
|---|---|---|---|---|
| PE-01 | Importante · Postergado | Casos y comprobaciones implementados; revisión independiente postergada | Validación numérica independiente | Casos de referencia con geometría, entradas, solución publicada o herramienta profesional de referencia, tolerancia acordada y revisión independiente. Incluir al menos electrodo simple, malla rectangular, varillas, grupos acoplados y conductor flotante. Registrar fuente, método y versión de cada referencia. La firma del revisor se mantiene postergada; hasta entonces, los resultados no habilitan declaraciones de cumplimiento. |
| PE-02 | P0 | Hecho | Convergencia de discretización | Ejecutar cada caso con varios tamaños de segmento y densidades de puntos; reportar error relativo y demostrar convergencia de resistencia, GPR y máximos de tensión de paso/contacto antes de exponer resultados de ingeniería. |
| PE-03 | P0 | Hecho | Diagnóstico de condicionamiento y balance | Devolver residuo del sistema, error de balance de corriente por grupo, condición de pivote y advertencia cuando el sistema sea singular o mal condicionado. Rechazar resultados no finitos o con error por encima del límite. |
| PE-04 | P0 | Hecho | Contrato de cálculo y trazabilidad | Versionar protocolo, solver, hipótesis, unidades, geometría discretizada, parámetros y origen de cada inyección. Incluir estos metadatos en cada resultado y artefacto/versionado del proyecto. |
| PE-05 | P0 | Hecho; re-medir en la CPU de producción | Límites operativos del ejecutable | Validar dimensiones, radio, cruces, segmentos duplicados, IDs, suelo e inyecciones en Python y C++. Definir límites de segmentos/puntos, timeout y memoria con mediciones de rendimiento representativas. |
| PE-06 | P1 · Orden 3 | Hecho (motor 3.2.0, cliente, artefactos y ajuste); falta vista de n capas en el frontend | Suelo estratificado multicapa | Generalizar Green a 1–8 capas horizontales, isotrópicas y semiinfinitas (espesor positivo en todas salvo la última); admitir electrodos que cruzan varias interfaces; conectar protocolo, cliente, artefactos y ajuste Wenner/Schlumberger; conservar incertidumbre, residuos y trazabilidad. Validar límites homogéneo/dos capas, reciprocidad, continuidad, convergencia y referencias publicadas; fijar límites de coste. La revisión independiente está postergada. Resultado en «Resultado del orden 3». |
| PE-07 | P1 | Hecho (2 capas; 3–8 capas en el endpoint; la vista del frontend solo muestra 2) | Modelo de suelo desde mediciones | Interpretar mediciones Wenner y Schlumberger (IEEE Std 81) e invertir modelos de 2 y n capas con error RMS, sensibilidad y descarte de lecturas atípicas. Conservar las mediciones crudas y el modelo elegido como entradas versionadas. Validar con los modelos de suelo del Anexo H de IEEE 80 y los casos de IEEE 81. |
| PE-08 | P1 | Casos implementados; revisión independiente postergada | Validación de suelo estratificado | Agregar a `reference_cases.json` los Grids 3–6 del Anexo H de IEEE 80-2013: dos capas, cerca separada con conductor flotante, malla en L y malla irregular con diagonales. Cubre el conductor flotante en malla que falta en la validación P0. Depende de "Suelo estratificado". La firma del revisor se mantiene postergada. |
| PE-09 | P1 | Hecho para IEEE 80-2013 | Verificación de tensiones de seguridad | Evaluar paso, contacto, malla y tensiones transferidas (incluidas cercas y estructuras) sobre una grilla adaptativa. Usar criterios tolerables con tiempo de despeje, masa corporal, capa superficial y norma/edición seleccionadas: IEEE Std 80, IEC/EN 50522 y RETIE para proyectos en Colombia. Mantener cálculo de campo separado de decisión normativa. |
| PE-10 | P1 | Parcial | Capa superficial | Modelar gravilla/concreto/capa superficial en la respuesta del suelo y las tensiones tolerables según el método normativo seleccionado; validar casos publicados antes de mostrar estados de cumplimiento. |
| PE-11 | P1 | Hecho (base) | Corriente de falla y reparto de retorno | Modelar factor de decremento, división de corriente entre malla, neutros, cables de guarda, pantallas y tierras remotas. Aceptar impedancias/conexiones de la red externa y conservar el desglose de aportes. |
| PE-12 | P1 · Orden 4 | Pendiente | Impedancia de conductores y escalera de cables de guarda | Incorporar resistividad, sección y conexiones de los conductores, caída longitudinal y una red de retorno distribuida para cables de guarda (modelo de escalera con impedancias por tramo, apoyos y puesta a tierra de torres). Acoplar la red con la malla y otros retornos para calcular reparto de corriente de falla y potenciales transferidos en instalaciones extensas. Validar contra casos de referencia y conservar parámetros, supuestos y aportes en la traza. Depende de definir nodos/conexiones eléctricos y de cerrar los límites de malla grande; reutiliza la interfaz de reparto de corriente existente. |
| PE-13 | P1 | Pendiente | Malla y geometría CAD | Crear importador DXF, asignar capas a tipos de elemento, detectar uniones/cruces reales y construir segmentos/nodos automáticamente. Añadir revisión visual de malla y puntos de consulta del mapa de potencial. |
| PE-14 | Por priorizar | Parcial | Editor de geometría en canvas | Existe un prototipo SVG con conductores, electrodos, obstáculos y validación geométrica básica. Faltan el esquema de geometría v2 persistido, reglas completas de frontend/backend, geometrías irregulares y enlace con DXF. Desglose, dudas y estimación en «Editor de geometría en canvas». Relacionado con «Malla y geometría CAD» y «Mapa de potencial superficial U». |
| PE-15 | P1 | Hecho | Segmentación graduada e incertidumbre numérica | Segmentos cortos cerca de puntas, esquinas, uniones y varillas, y largos en tramos rectos. Estimar el error de discretización en cada cálculo (dos refinamientos y extrapolación de Richardson) y reportarlo junto a cada magnitud, por ejemplo "S1 = 91,2 V ± 0,1 %". Criterio: igualar el paso convergido del Grid 1 (91,24 V) con menos de 500 segmentos. |
| PE-16 | P1 | Parcial (GMRES hasta 4 000, Grid 5 medido; >10 000 pendiente) | Rendimiento de mallas grandes | Sustituir LU por un método iterativo o acelerado para superar los 1 500 segmentos del Grid 5 y llegar a más de 10 000 segmentos; medir tiempo, memoria y precisión en CPU de despliegue antes de ampliar límites. |
| PE-17 | P1 | Hecho (base) | Integración asíncrona | Ejecutar cálculos largos desde Celery/worker aislado; API encola y devuelve identificador, estado, cancelación y resultado. Aplicar concurrencia limitada, timeout y reintentos idempotentes. |
| PE-18 | P1 | Pendiente | Prueba de contrato Python/C++ | Formalizar serialización, escaping, unidades, errores, límites y versionado. Evaluar JSON Lines o Protobuf para reemplazar el protocolo de tokens cuando se requieran objetos más ricos; conservar `Popen` como adaptador sencillo. |
| PE-19 | P2 | Pendiente | Impedancia compleja en AC | Extender la formulación a frecuencia y fasores para incluir inductancia, efecto piel, impedancia de conductores y acoplamientos mutuos. Validar por frecuencia y con redes de retorno representativas. |
| PE-20 | P2 | Pendiente | Transitorios e impulso | Desarrollar un solver transitorio separado para rayos/frentes rápidos, con parámetros dependientes de frecuencia y modelos físicos de electrodos. No extrapolar el solver cuasiestático actual. |
| PE-21 | P2 | Pendiente | Barridos paramétricos y optimización | Calcular alternativas de espaciamiento, profundidad, sección, varillas y capa superficial; comparar costo, seguridad y sensibilidad y publicar cada alternativa como una versión inmutable del artefacto. |
| PE-22 | P2 | Pendiente | Formatos de salida y visualización | Exportar raster/CSV de potencial, isolíneas, máximos locales, pares paso/contacto y distribución de corriente por elemento con unidades y leyenda. Agregar vista 3D de la malla con densidad de corriente y potenciales. |
| PE-23 | P2 · Primer entregable de la fila anterior | ◐ Parcial | Mapa de potencial superficial U sobre la malla | El cálculo del artefacto persiste la rejilla de U (origen, espaciado, extensión, dimensiones y valores) y la API la devuelve con el resultado; el frontend muestra un mapa de calor y ofrece vista 3D de la malla. Pendiente: descarga CSV/raster dedicada, superponer varillas y cercas en el mapa 2D, marcar en el mapa los puntos críticos de contacto y paso, y validar tamaños/coherencia para modelos de 1, 2 y 3–8 capas. |
| PE-24 | P2 | Pendiente | Memoria de cálculo | Generar un informe reproducible con entradas, modelo de suelo, geometría, hipótesis, norma/edición, resultados, diagnóstico numérico, incertidumbre y `trace` del motor, firmable por el ingeniero responsable. Los programas comerciales lo entregan de serie. |
| PE-25 | P2 | Pendiente | Electrodos no cilíndricos | Modelar placas, platinas, anillos curvos y cimentaciones o electrodos en concreto. Validar contra fórmulas cerradas (placa, anillo) y casos publicados. |
| PE-26 | P2 | Pendiente | Simulación de mediciones IEEE 81 | Simular la prueba de caída de potencial con la posición de los electrodos auxiliares y el acoplamiento de los cables de prueba, para comparar la resistencia medida en campo con la calculada. Ayuda a cerrar la recomendación 5 con datos de campo. |
| PE-27 | P2 | Pendiente | Suelo heterogéneo | Capas verticales o inclinadas, volúmenes finitos de distinta resistividad (rellenos, rocas, agua) y tratamientos de suelo. Depende de "Suelo estratificado". |
| PE-28 | P3 | Evaluar | Interferencia AC y protección catódica | Acoplamiento inductivo, conductivo y capacitivo de líneas de transmisión con tuberías y vías férreas. Lo cubren CDEGS y XGSLab; queda fuera del alcance actual hasta que lo pida un proyecto. |
| PE-29 | P2 | Pendiente | Observabilidad y operación | Registrar versión del binario, duración, segmentos/puntos, timeout, fallos y tamaños de salida; incorporar métricas, límites de cola, alertas, runbook y política de retención. |

## Resultado de los P0 (2026-10-04)

- **Validación:** `validation/reference_cases.json` contiene 8 casos y 18 comprobaciones: varilla simple, conductor horizontal, dos varillas unidas, grupos acoplados con inyecciones independientes, varilla flotante (fórmulas de Dwight, IEEE Std 142-2007), mallas IEEE Std 80-2013 Anexo H Grid 1 y Grid 2 (rango CDEGS/ETAP/WinIGS) y Anexo B Ejemplo 1 (EPRI TR-100622). Todas pasan. El paquete para el revisor está en `validation/REVIEW.md`, generado con `validation/review_report.py`. Incluye resultados, fuentes, desviaciones conocidas, convergencia, preguntas abiertas y una tabla de dictamen para firmar. Las mayores desviaciones son −1,5 % en el contacto máximo del Anexo B y +1,9 % en el paso S1 del Grid 1. Esta última está documentada en el caso: el motor converge a 91,24 V, y con segmentos de 3,5–7 m reproduce el rango publicado, así que la referencia probablemente está sub-resuelta en la esquina. Una comprobación de regresión fija ese valor convergido con tolerancia de 0,5 %. **Pendiente:** confirmar con valores por programa. La Tabla 3 del estudio de ELEK los trae, pero su sitio bloquea el acceso automatizado y hay que revisarla manualmente. Cada referencia registra fuente, método y edición. **Pendiente:** firma de tolerancias por un ingeniero competente y cotejo de los valores del Anexo H/B con una copia licenciada de IEEE 80. Los valores se transcribieron del script de validación del repositorio `protectionpro`, porque no se encontró un motor de referencia abierto con licencia adecuada. El paquete `earthing` (GPLv3) se descartó como referencia: su modelo de discos converge lento y da T1 = 327 V cuando el rango publicado es 195–201 V. Ningún caso de referencia cubre todavía una malla con conductor flotante en suelo homogéneo; el Grid 4 del Anexo H usa suelo estratificado (P1).
- **Convergencia:** `validation/convergence.py`. Del penúltimo al último refinamiento, en el Grid 1 la resistencia cambia 0,00 %, T1 0,02 %, el contacto máximo 0,01 % y el paso 0,17 %. En el Grid 2 los cambios son 0,01 %, 0,06 %, 0,06 % y 0,73 %. Con rejillas de búsqueda de 0,5 m a 0,25 m el contacto máximo cambia ≤0,02 %. El paso cerca de varillas y esquinas exige segmentos ≤1 m.
- **Diagnóstico:** error hacia atrás normado, estimación de condición en norma 1 (Hager/Higham), razón de pivotes, error de balance por grupo y dispersión del potencial del grupo. Se rechazan resultados no finitos, con error hacia atrás >1e-10, condición >1e13 o balance >1e-9; se advierte si la condición supera 1e10 o no hay inyección.
- **Trazabilidad:** cada resultado incluye protocolo, versión del solver, método, hipótesis, unidades, SHA-256 de la solicitud y del binario, fecha, duración, geometría discretizada y origen de cada inyección. Desde el 2026-10-04 cada cálculo de un artefacto se guarda en `calculos_potencial_tierras` (migración 0008), ligado a (artefacto, versión), con parámetros, resultado y `trace` completo, incluidos los hashes de cada lote de puntos.
- **Límites:** validación espejo en Python y C++. Los antiguos benchmarks de LU fijaron el máximo inicial en 1 500 segmentos, 100 000 puntos, 2e7 puntos × segmentos, timeout de 60 s y 512 MiB en Linux. Con GMRES el máximo de entrada es 4 000 segmentos; benchmark específico de Grid 5 hasta 2 079 segmentos está en `validation/benchmark-grid5-large-macos-arm64.json`. **Pendiente:** medir el máximo de 4 000 y repetir en la CPU real de producción, que aún no está definida.
- **Mallas grandes:** el motor conserva LU hasta 1 500 segmentos y cambia a GMRES con equilibrado por filas entre 1 501 y 4 000. Benchmark del Grid 5 del Anexo H, suelo de dos capas, en Apple arm64: con 1 883 segmentos y d=1 m converge en 55 iteraciones y 1,87 s; frente a LU en la misma matriz, resistencia y GPR coinciden exactamente a la precisión publicada. Error hacia atrás 1,1e-15 y balance relativo de corriente 7,2e-14. Con 2 079 segmentos y d=0,7 m: 54 iteraciones, 2,29 s, error hacia atrás 1,4e-15. Datos reproducibles en `validation/benchmark-grid5-large-macos-arm64.json`; ejecutar `validation/large_mesh_benchmark.py`. El diagnóstico de condición 1-norma no está disponible con GMRES y se marca como -1 con advertencia explícita. **Pendiente:** >4 000 y en particular >10 000 segmentos con aceleración jerárquica, más medición en CPU de producción.

## Resultado del orden 3: suelo de 3–8 capas (2026-10-05)

- **Contrato:** `SPAT-POTENTIAL-3` extendido de forma explícita y aditiva con la línea `n-layer <count> <rho_1> <h_1> ... <rho_N> inf <kernel_density> <segments>` (solver 3.2.0). Las solicitudes y respuestas homogéneas y de dos capas no cambian; un binario anterior rechaza la línea nueva con error. La respuesta añade `META soil_model n-layer`, capas pedidas y resueltas, `kernel_limits` y `DIAG kernel_*`/`*_image_work`. En Python, `LayerStackSoil` (1–8 capas, última semiespacio) se valida, serializa, registra en el `trace`, estima su coste igual que el motor (`kernel_terms`, `image_work`, `point_batch_size`) y el cliente rechaza respuestas que no resolvieron `n-layer`. La ruta de dos capas por serie de imágenes se conserva para `TwoLayerSoil` y para los artefactos de dos capas.
- **Kernel (`src/main.cpp`, sección «N-layer soil»):** forma espectral de Sunde/Koefoed con coeficientes por recursión estable de reflexión/transmisión generalizada (sin exponenciales crecientes; el espesor que cruza el rayo directo se factoriza analíticamente); cada coeficiente menos su límite se aproxima con exponenciales reales en una malla geométrica de profundidades (SVD truncado, variante real del método de imágenes complejas de Chow et al. 1992 y Li et al. 2006), y cada término es una imagen exacta del segmento, de modo que la integral de línea analítica y la cuadratura Galerkin de dos capas se reutilizan. Cota de error a posteriori del ajuste en el dominio espacial (`kernel_error_bound`), con rechazo por encima de 1e-4. No se aproxima N capas como homogéneo ni se encadenan soluciones de dos capas.
- **Interfaces y conductores:** el cliente corta cada segmento en todas las interfaces que cruza, en orden a lo largo del segmento (también de profundo a superficial), conserva grupo, tipo y radio, nombra las partes `<id>.L<k>` (dos capas: `.u`/`.l`), rechaza partes de menos de 5 radios e IDs que colisionan o superan 80 caracteres. `rectangular_grid_segments(interface_depths_m=...)` y `discretize` ponen nodos en todas las interfaces. El motor rechaza segmentos que cruzan cualquier interfaz.
- **Artefactos:** `artifact_potential.soil_model` acepta 1–8 capas (`depth_m` = espesor, nulo solo en la última), une capas adyacentes de resistividad exactamente igual sumando espesores y rechaza con mensaje claro un fondo finito, espesores faltantes, más de 8 capas o un apilado fuera de los límites del kernel. Cs usa la capa superior. El endpoint `mediciones-suelo/ajustar` con `layer_count` 3–8 devuelve capas en formato de artefacto, dentro de los límites del motor; la prueba de API ajusta, guarda y calcula un artefacto de 3 capas.
- **Ajuste Wenner/Schlumberger (`calculations/n_layer_soil.py`):** transformada de Koefoed (recurrencia de Pekeris) con imágenes reales ajustadas por QR con pivoteo de columnas; error frente a la serie exacta de dos capas ≤ 2e-5 hasta contraste 1e3 y frente a cuadratura directa independiente ≤ 1e-4. Levenberg-Marquardt con arranques deterministas cribados, exclusión de lecturas atípicas por validación cruzada (dejar una fuera), incertidumbre 1σ por parámetro, límites del motor (0,01–1e6 Ω·m, contraste ≤ 1e4, 0,01–1000 m) y presupuesto de 60 s con advertencia. 3 capas: ~2–3 s; 8 capas con 20 lecturas: 7,9 s.
- **Validación (pruebas en `tests/infrastructure/test_n_layer_engine.py`, `test_n_layer_soil.py`, `test_artifact_potential.py`):**
  - Referencia independiente (`tests/infrastructure/layered_green_reference.py`): sistema de contorno completo por λ e integral de Hankel numérica, sin código compartido; reproduce la serie de Sunde de dos capas a 1e-11. Potencial superficial de una fuente en cada capa (3, 3, 4 y 8 capas, contrastes positivos y negativos) dentro de 2e-5; acoplamiento entre capas distintas dentro de 2e-5.
  - Dos capas: kernel n capas frente a la serie de imágenes en malla con varillas, R a 1e-6 y potenciales a 1e-5; Grids 3 y 6 del Anexo H y Exhibit 1 del Anexo B por la ruta n capas reproducen cada comprobación de la ruta de dos capas a 2e-5.
  - Homogéneo: 1 capa o capas iguales dan el resultado homogéneo bit a bit; capas casi iguales (±1e-5 relativo) lo reproducen a 1e-5; un estrato superior grueso tiende al homogéneo.
  - Reciprocidad entre capas a 1e-7; continuidad del potencial en cada interfaz (el salto decrece linealmente con la separación hasta 1e-5 m); convergencia al refinar el kernel (cota de 4e-5 a 1e-7 entre densidades 7 y 10, resultados estables a 2e-7; densidad 6 rechazada).
  - Cortes en varias interfaces en ambas orientaciones con resultados idénticos a 1e-9; rechazo de partes cortas, IDs duplicados, espesores/resistividades inválidos, fondo finito, 9 capas, contraste > 1e4, falta de convergencia, más de 120 imágenes y puntos enterrados, en Python y en C++.
  - Sondeos publicados (no sintéticos): USGS OFR 80-190 (Haines y Campbell 1980), 3 capas 10/4/25 Ω·m con 10 y 50 m, Wenner y Schlumberger: desviación máxima 0,85 % y 0,78 % (mediana 0,19 % y 0,12 %), tolerancia 1 %; USGS OFR 81-160 (El Kahwagy 1981), 4 capas 259/94/27/150 Ω·m con 1, 46 y 150 m, Schlumberger: máxima 3,97 % (mediana 1,56 %), tolerancia 4,5 %. Ambas referencias usan el filtro corto de Ghosh (1971), que el propio OFR 80-190 advierte impreciso en curvas descendentes; la cuadratura directa confirma nuestro modelo a 1e-4 en los puntos donde converge. La inversión del sondeo Wenner publicado recupera el modelo de 3 capas dentro del 3 %.
- **Rendimiento (`validation/n_layer_benchmark.py`, `validation/benchmark-n-layer-macos-arm64.json`, Apple arm64):** el coste crece de forma controlada con el número de capas: para ~3 000 segmentos y 10 000 puntos (3–4 lotes), 17,3 s con la serie de dos capas, 14,4 s con el kernel de 2 capas, 22,3 s con 3, 27,3 s con 4 y 31,6 s con 8 capas; 2,5–12 ns por evaluación de imagen. La construcción del kernel tarda < 0,1 s. Peor solicitud admitida medida (8 capas, 3 456 segmentos, 5 787 puntos en el límite puntos × segmentos, trabajo 2,1e9 + 3,0e9): 20,6 s y 100 MiB, dentro del timeout de 60 s y 512 MiB. Los benchmarks de mallas grandes y su JSON no se modificaron.
- **Brechas:** revisión independiente (postergada; ver `docs/BACKLOG.md`); medir en la CPU de producción; vista de n capas y gráfica de ajuste en el frontend; casos publicados de mallas en suelo de 3 o más capas (p. ej. CDEGS/Dawalibi) para validar resistencias de malla, no solo el kernel y los sondeos; contraste con una tabla de IEEE 81; contrastes > 1e4 y extensiones muy grandes quedan fuera del rango validado; puntos de consulta enterrados no se admiten en n capas.

## Resultado de los P1 (2026-10-04)

## Próximos trabajos acordados (2026-10-05)

### Orden 3 — Suelo de más de dos capas (hecho el 2026-10-05; ver «Resultado del orden 3»)

Los cinco pasos acordados están hechos: contrato de 1–8 capas, kernel estratificado en C++ con la ruta de dos capas conservada y demostrada equivalente, cortes en todas las interfaces, integración de serialización/metadatos/coste/artefactos/ajuste y validación (referencias, reciprocidad, continuidad, convergencia, límites y rendimiento junto al trabajo de mallas grandes).

### Mapa de potencial superficial U sobre la malla (pedido el 2026-10-05; sin orden asignado)

1. Backend: conservar en el resultado del cálculo del artefacto la rejilla de U que `artifact_potential._field` ya evalúa, con espaciado, extensión y unidades, junto a la geometría discretizada (malla, varillas, cercas) y su trazabilidad.
2. API: devolver la rejilla con el resultado o como descarga raster/CSV; acotar tamaño y paginar o comprimir si hace falta.
3. Frontend: reemplazar el `PotentialChart` ilustrativo por un mapa de calor o isolíneas de U con la malla y los elementos físicos superpuestos y los puntos de contacto/paso peores; coordinar con la tarea que edita `app/src/main.jsx`.
4. Validar que el mapa reproduce GPR y los máximos del resultado y que funciona con suelo homogéneo, de dos capas y de 3–8 capas.

### Editor de geometría en canvas (pedido el 2026-10-05; sin prioridad ni orden asignados)

Hoy el motor y el cliente Python resuelven cualquier red de segmentos rectos 3D (validado con mallas en L, diagonales y cercas separadas del Anexo H), pero el artefacto solo describe una malla rectangular (`rectangular_grid_segments`). El canvas permitiría dibujar geometrías irregulares desde el producto.

| Pieza | Complejidad | Entregable |
|---|---|---|
| Esquema de geometría v2 del artefacto | Media | Nodos, conductores como polilíneas, varillas, cercas, obstáculos como polígonos, grupos y profundidad por elemento; versionado y migración de los artefactos rectangulares actuales. Es la decisión que conviene fijar primero. |
| Canvas con paleta | Media | Dibujo, selección, mover, borrar, deshacer/rehacer, zoom, ajuste a rejilla y a nodos, edición de vértices; SVG o una librería tipo Konva. |
| Reglas geométricas en vivo | Media-alta | Ningún conductor atraviesa obstáculos; los cruces entre conductores crean uniones; longitud mínima de 5 radios; varillas fuera de cimentaciones; grupos distintos no se tocan; avisos visuales. |
| Conversión en el backend | Baja-media | Geometría v2 → `ElectrodeSegment`: cortes en cruces de polilíneas arbitrarias, en interfaces del suelo y segmentación graduada (reutiliza `discretize` y `split_at_interface`). |
| Validación en el backend y pruebas | Media | Repetir todas las reglas en Python (no confiar en el frontend); casos con geometrías irregulares y obstáculos. |
| Obstáculos en la verificación de seguridad | Baja | Excluir el área de los obstáculos de la búsqueda de contacto y paso. |

Estimación (una persona con experiencia; incertidumbre alta porque el prototipo SVG actual no se revisó en detalle): MVP en 2–3 semanas (esquema v2, paleta básica, bloqueo de cruces con obstáculos, conversión y cálculo); versión sólida en 6–8 semanas (deshacer/rehacer, edición de vértices, anillos, propiedades y vista de profundidad, migración, validación completa, pruebas y mapa de U superpuesto).

Dudas abiertas a resolver antes de empezar:

1. **Naturaleza de los obstáculos:** ¿son solo restricción geométrica (cimentaciones, edificios, canales) o deben afectar el campo eléctrico (acero de cimentaciones como electrodo, concreto)? Lo segundo entra en «Electrodos no cilíndricos» y es mucho más trabajo.
2. **Conductor que cruza un obstáculo:** ¿se bloquea el trazo, se recorta en el borde o se propone un desvío automático alrededor del obstáculo?
3. **Curvas:** ¿basta con dibujar anillos y arcos guardados como polígonos de N lados (N configurable u oculto al usuario) o se requiere un elemento curvo exacto?
4. **Profundidad y capas:** el canvas es 2D; ¿se edita la profundidad por elemento en un panel de propiedades o hace falta una vista de corte con las capas del suelo?
5. **Relación con DXF:** ¿el importador DXF debe producir el mismo esquema v2 para editar después en el canvas? (recomendado)
6. **Compatibilidad:** ¿se migran los artefactos rectangulares existentes al esquema v2 o conviven ambos formatos?
7. **Coordinación:** el canvas vive en `app/src/main.jsx`, que edita otra tarea; acordar el reparto antes de empezar.

### Orden 4 — Impedancia de conductor y modelo de escalera de cables de guarda

1. Definir nodos eléctricos y uniones para malla, conductores externos, apoyos y tierras de torre.
2. Calcular impedancia longitudinal por tramo a partir de material, sección, longitud y frecuencia; representar conexiones y puestas a tierra como impedancias explícitas.
3. Acoplar la red de cables de guarda a la malla y a los retornos existentes, resolviendo en conjunto reparto de corriente y potenciales transferidos.
4. Validar redes pequeñas contra solución nodal independiente y casos publicados; escalar a mallas extensas con benchmarks, sensibilidad y traza de aportes.

El orden 4 puede avanzar en el contrato de red nodal en paralelo, pero su integración depende del límite de malla grande y de mantener el motor de suelo desacoplado del modelo de circuito.

- **Suelo estratificado:** motor 3.0.0, protocolo `SPAT-POTENTIAL-3`, suelo homogéneo o de dos capas.
  - Usa la serie de imágenes de Sunde/Tagg, truncada con una cota a priori de 1e-7. Si la serie necesita más de 2000 términos, el motor da un error explícito.
  - El suelo homogéneo da resultados idénticos bit a bit al v2. Se verificaron los límites h→∞ y h→0, la reciprocidad y la continuidad en la interfaz.
  - Las varillas que atraviesan la interfaz se parten automáticamente.
  - Límites nuevos de 4e9 evaluaciones de imagen, para la matriz y para los puntos. Peor caso permitido en Linux: 5,7 s con K = −0,5 y 12,3 s con K = 0,82.
  - Los artefactos aceptan de 1 a 8 capas; desde el motor 3.2.0, 3–8 capas usan el kernel n capas (ver «Resultado del orden 3»).
- **Validación de suelo estratificado:** Grids 3–6 del Anexo H y Exhibit 1 del Anexo B; 38 de 42 comprobaciones dentro de tolerancia.
  - 4 desviaciones conocidas, investigadas y documentadas en cada caso:
    - La resistencia de la cerca sola del Grid 4 depende de la profundidad supuesta del conductor: con 0,5 m queda en +3,6 %; con 1,0 m entra en el rango.
    - En el Exhibit 1, la referencia parece no modelar las varillas que atraviesan la interfaz. Sin varillas, el motor coincide con un solver independiente en 0,07 %.
  - El paso de esquina converge más lento que la resistencia y el contacto (0,8 % a 0,7 m). Las comprobaciones de referencia de Grid 5 permanecen a 1,75 m; la solución de 1 m con 1 883 segmentos fue medida y contrastada con LU en `validation/benchmark-grid5-large-macos-arm64.json`.
  - El arnés excluye los puntos a menos de 0,08 m (radio de pie de IEEE 80) de un electrodo que aflora.
- **Modelo de suelo desde mediciones:** `calculations/soil_model.py`.
  - Interpreta sondeos Wenner y Schlumberger con el modelo de dos capas de Sunde (1949) y Tagg (1964). Suma la cola de la serie con Euler-Maclaurin para capas delgadas y contrastes fuertes.
  - Invierte ρ1, ρ2 y h por Levenberg-Marquardt con varios arranques. Reporta error RMS, incertidumbre por parámetro, residuo por lectura, exclusión de lecturas atípicas (umbral de 15 %) y la comparación con el modelo homogéneo.
  - Entrega las capas en el formato de los artefactos.
  - Validado con sondeos sintéticos de los suelos del Anexo H, con 2 % de ruido y con una lectura atípica.
  - El endpoint de ajuste de mediciones y la vista Wenner del producto ya están conectados; cada artefacto guarda las lecturas crudas junto al modelo de suelo.
  - De 3 a 8 capas: `calculations/n_layer_soil.py` (ver «Resultado del orden 3»). **Pendiente:** contraste con una tabla publicada de IEEE 81.
- **Verificación de seguridad y capa superficial:** `calculations/safety_criteria.py`, separado del cálculo de campo.
  - Cada cálculo de artefacto se compara con los tolerables de la norma y la edición pedidas explícitamente (`safety_standards`; por defecto IEEE 80-2013).
  - Cubre 50 y 70 kg, el factor Cs de la capa superficial con la resistividad de la capa superior, el tiempo de despeje entre 0,03 y 3 s, y el chequeo del GPR frente al contacto tolerable.
  - Para el Ejemplo 1 del Anexo B, con Cs redondeado a 0,74, reproduce los tolerables publicados de 838,2 V de contacto y 2686,6 V de paso.
  - La capa superficial solo afecta los tolerables vía Cs; el campo del motor no la modela (por eso "Capa superficial" queda Parcial).
  - **Pendiente:**
    - cargar las tablas de EN 50522:2010 y RETIE (Tabla 15.1) desde copias oficiales; hoy se reportan como "no evaluable";
    - cotejar los valores del Anexo B con una copia licenciada;
    - evaluar las tensiones transferidas a cercas y estructuras externas.
- **Corriente de falla y reparto de retorno:** `calculations/fault_current.py` calcula I_G = D_f·S_f·3I0 según IEEE Std 80-2013 (ecuaciones 64, 74 y 79). D_f se verificó con la Tabla 10.
  - S_f se toma de un valor que da el usuario, con su origen, o se calcula con un divisor de corriente complejo entre R_g y las rutas de retorno, con el desglose de corriente por ruta.
  - Los artefactos inyectan I_G y registran su origen en el trace. Sin datos se conserva la corriente total con advertencia.
  - **Pendiente:** modelo de escalera de cables de guarda (Anexo C de IEEE 80) validado contra una referencia publicada.

- **Segmentación graduada e incertidumbre numérica:** `Segmentation` y `discretize` cortan cada conductor entre nodos con segmentos de 0,25·d junto a extremos libres, esquinas, uniones, varillas y la interfaz entre capas, y de d junto a cruces. Crecen con razón 2 hasta 7·d y respetan los 5 radios.
  - Con d = 1 m, el paso de esquina converge con 40–55 % menos segmentos que en uniforme:

    | Malla | Graduada | Uniforme |
    |---|---|---|
    | Grid 1 | 0,01 % de 91,24 V con 452 segmentos | −0,12 % con 1 200 |
    | Grids 2–3 | 0,25–0,28 % con 612–692 segmentos | 0,8–0,9 % con 1 420 |

    La tabla sale de `validation/segmentation_study.py`.
  - Los artefactos usan graduado por defecto. Los Grids 1–3 se validan así, con regresiones contra el S1 convergido.
  - `estimate_uncertainty` reporta el error estimado de R, GPR, contacto y paso (Richardson con GCI 1,25, o la diferencia entre refinamientos), a cambio de unas 2,3 veces el tiempo de cálculo.
  - **Pendiente:** cortar las diagonales en los cruces y validar la ganancia en mallas densas (Grid 5) y con cercas (Grid 4).

## Integración con artefactos (2026-10-04; exposición de mediciones/cálculos 2026-10-04)

- `POST /api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}/versions/{version}/calculos-potencial` encola un cálculo y responde 202 con su identificador. Parámetros opcionales: radio del conductor (por defecto 2/0 AWG, 5,25 mm), discretización (1 m) y paso de la rejilla superficial (0,25, 0,5 o 1 m).
- `GET .../versions/{version}/calculos-potencial` lista los cálculos de una versión; `GET .../{artifact_id}/calculos-potencial/{id}` devuelve estado, resultado y `trace`; `POST .../{id}/cancelar` cancela un cálculo pendiente o en curso. Si el motor ya estaba corriendo, su resultado se descarta.
- La tarea Celery `spat.calculate_artifact_potential` es idempotente. Una nueva entrega solo ejecuta cálculos pendientes, o en curso si llevan más de 15 minutos sin actualizarse (worker caído). Límite de tiempo: 600 s.
- Estados: `pending`, `running`, `completed`, `failed` (error del motor), `rejected` (modelo no soportado) y `cancelled`. Se rechazan los artefactos con modelos no soportados o mallas que superan el límite vigente.
- El resultado trae resistencia, GPR, contacto máximo dentro del perímetro (con su ubicación) y paso máximo a 1 m. El paso se busca primero en la rejilla y luego en 16 direcciones alrededor de los 20 puntos más críticos. También incluye el diagnóstico del motor y advertencias del modelo: corriente de falla sin factor de división, sin cercas externas, sin capa superficial ni criterios tolerables.
- La interfaz de proyecto permite ajustar el modelo Wenner, configurar la geometría y la falla, encolar el cálculo y consultar estado, resultados y trazabilidad resumida del artefacto.
- **Pendiente:** cola Celery dedicada para no competir con otras tareas (hoy comparte el worker con concurrencia 2) y probar la migración 0008 en PostgreSQL (las pruebas usan SQLite).

## Brechas frente al mercado

Comparación con CDEGS (SES), XGSLab (SINT), SafeGrid (ELEK), ETAP Ground Grid y WinIGS, a partir de la documentación pública de cada producto y sin verificación individual. En suelo homogéneo, el motor queda dentro del rango publicado de esos programas en 7 de las 8 magnitudes de los Grids 1–2 del Anexo H.

| Capacidad del mercado | Estado en SPAT | Fila del backlog |
|---|---|---|
| Suelo de 2 capas y multicapa | Sí: 2 capas (serie) y 3–8 capas (kernel n capas); revisión independiente postergada | Suelo estratificado (P1) |
| Interpretación de mediciones de resistividad | 2–8 capas (Wenner/Schlumberger) con endpoint; vista de 2 capas | Modelo de suelo desde mediciones (P1) |
| Validación con suelo estratificado (Anexo H Grids 3–6) | Sí; revisión independiente postergada | Validación de suelo estratificado (P1) |
| Criterios tolerables IEEE 80 / IEC / EN 50522 | IEEE 80-2013; EN 50522 y RETIE con tabla pendiente | Verificación de tensiones de seguridad (P1), Capa superficial (P1) |
| Reparto de corriente de falla (cables de guarda, neutros, pantallas) | Base: S_f y rutas agrupadas; sin modelo de escalera | Corriente de falla y reparto de retorno (P1) |
| Impedancia del conductor y caída longitudinal | No | Elementos metálicos con impedancia finita (P1) |
| Importación CAD y segmentación automática | Segmentación graduada sí; CAD no | Malla y geometría CAD (P1), Segmentación graduada (P1) |
| Mallas de más de 10 000 segmentos | No (GMRES denso hasta 4 000) | Rendimiento de mallas grandes (P1) |
| Respuesta en frecuencia y rayo | No | Impedancia compleja en AC (P2), Transitorios e impulso (P2) |
| Optimización de diseño | No | Barridos paramétricos y optimización (P2) |
| Informe de cálculo | No | Memoria de cálculo (P2) |
| Gráficas 2D/3D de potencial | No | Formatos de salida y visualización (P2) |
| Placas, platinas y cimentaciones | No | Electrodos no cilíndricos (P2) |
| Simulación de pruebas de campo | No | Simulación de mediciones IEEE 81 (P2) |
| Suelo heterogéneo y volúmenes finitos | No | Suelo heterogéneo (P2) |
| Interferencia AC en tuberías | No | Interferencia AC y protección catódica (P3) |
| Diagnóstico numérico expuesto, trazabilidad por hash, código abierto vía API | **Sí** | Ventaja propia; mantenerla en cada feature nueva |

El 2026-10-04 se completó el orden sugerido para alcanzar paridad en diseños reales: suelo estratificado, modelo de suelo desde mediciones, validación con los Grids 3–6, verificación de seguridad y reparto de corriente de falla, más la segmentación graduada. Siguen bloqueando el uso en proyectos reales:
- las tablas de EN 50522 y RETIE;
- las mallas de más de 4 000 segmentos (en particular el objetivo de 10 000+) y el diagnóstico de condición para GMRES;
- la impedancia del conductor.

## Recomendación de ejecución

1. **Desarrollo local:** compilar una vez con `make potential-engine`; el cliente Python invoca el ejecutable por `Popen`. Usar lotes pequeños y homogéneos, y fijar `SPAT_POTENTIAL_ENGINE` si el binario se instala fuera de la ruta predeterminada.
2. **API interactiva:** permitir cálculo síncrono solo para mallas pequeñas cuyo tiempo máximo se haya medido. Aplicar timeout y límite de concurrencia para no agotar workers de FastAPI.
3. **Cálculos de proyecto o mallas grandes:** enviar un job a Celery y ejecutar el binario en un worker aislado con CPU/memoria limitadas. Persistir entradas, versiones, logs técnicos y resultado junto al artefacto versionado. No hacer el cálculo dentro del proceso HTTP.
4. **Producción:** fijar la versión/hash del binario en una imagen reproducible y desplegarlo como worker C++ dedicado si el volumen o la escala lo justifican. El ejecutable actual procesa una solicitud y termina; por eso `Popen` lanza un proceso por cálculo. Un daemon con pipes persistentes o gRPC solo conviene cuando mediciones muestren que el costo de arranque es relevante.
5. **Antes de habilitar decisiones de seguridad:** completar los P0, acordar referencias y tolerancias con un ingeniero competente, y comparar contra mediciones de campo. Los estándares tienen alcance y ediciones específicas; el motor debe guardar la edición elegida por proyecto, no inferirla.
