# Backlog del motor de potencial de malla

## Estado actual

El motor C++17 (protocolo `SPAT-POTENTIAL-2`, solver 2.0.0) resuelve una distribución cuasiestática de potencial para segmentos rectos de electrodos cilíndricos ideales en suelo homogéneo, isotrópico y semiinfinito. Calcula acoplamiento por el suelo entre grupos, corriente por segmento, potencial de cada grupo y potencial superficial en puntos consultados, y devuelve diagnósticos numéricos y metadatos de trazabilidad. El cliente Python invoca el ejecutable con `subprocess.Popen`.

La validación del 2026-10-04 encontró que la versión 1 usaba ρ/(2πr) para una fuente enterrada y sobrestimaba resistencias y tensiones por un factor de 2. Todo resultado calculado con `SPAT-POTENTIAL-1` debe descartarse.

El resultado actual es exploratorio. No se debe usar para declarar cumplimiento IEEE/IEC, emitir diseños aprobados ni reemplazar mediciones o revisión profesional. IEEE Std 80 trata la seguridad de puesta a tierra de subestaciones AC; IEC 61936-1:2021 cubre instalaciones de potencia por encima de 1 kV AC. El alcance del modelo debe compararse con las normas y métodos aplicables al proyecto y su jurisdicción ([IEEE](https://standards.ieee.org/ieee/80/12145/), [IEC](https://webstore.iec.ch/en/publication/64490)).

## Backlog priorizado

| Prioridad | Estado | Feature | Entregable y criterio de aceptación |
|---|---|---|---|
| P0 | Hecho; falta firma del revisor | Validación numérica independiente | Casos de referencia con geometría, entradas, solución publicada o herramienta profesional de referencia, tolerancia acordada y revisión independiente. Incluir al menos electrodo simple, malla rectangular, varillas, grupos acoplados y conductor flotante. Registrar fuente, método y versión de cada referencia. |
| P0 | Hecho | Convergencia de discretización | Ejecutar cada caso con varios tamaños de segmento y densidades de puntos; reportar error relativo y demostrar convergencia de resistencia, GPR y máximos de tensión de paso/contacto antes de exponer resultados de ingeniería. |
| P0 | Hecho | Diagnóstico de condicionamiento y balance | Devolver residuo del sistema, error de balance de corriente por grupo, condición de pivote y advertencia cuando el sistema sea singular o mal condicionado. Rechazar resultados no finitos o con error por encima del límite. |
| P0 | Hecho | Contrato de cálculo y trazabilidad | Versionar protocolo, solver, hipótesis, unidades, geometría discretizada, parámetros y origen de cada inyección. Incluir estos metadatos en cada resultado y artefacto/versionado del proyecto. |
| P0 | Hecho; re-medir en la CPU de producción | Límites operativos del ejecutable | Validar dimensiones, radio, cruces, segmentos duplicados, IDs, suelo e inyecciones en Python y C++. Definir límites de segmentos/puntos, timeout y memoria con mediciones de rendimiento representativas. |
| P1 | Pendiente | Suelo estratificado | Implementar Green de dos capas y luego n capas con suelo superior, inferior y profundidad de interfaz, incluidas varillas que atraviesan capas. Validar contra soluciones de referencia; propagar incertidumbre de resistividad y espesor. **Brecha de mercado crítica:** todos los programas comerciales lo tienen y casi ningún diseño real usa suelo homogéneo. |
| P1 | Pendiente | Modelo de suelo desde mediciones | Interpretar mediciones Wenner y Schlumberger (IEEE Std 81) e invertir modelos de 2 y n capas con error RMS, sensibilidad y descarte de lecturas atípicas. Conservar las mediciones crudas y el modelo elegido como entradas versionadas. Validar con los modelos de suelo del Anexo H de IEEE 80 y los casos de IEEE 81. |
| P1 | Pendiente | Validación de suelo estratificado | Agregar a `reference_cases.json` los Grids 3–6 del Anexo H de IEEE 80-2013: dos capas, cerca separada con conductor flotante, malla en L y malla irregular con diagonales. Cubre el conductor flotante en malla que falta en la validación P0. Depende de "Suelo estratificado". |
| P1 | Pendiente | Verificación de tensiones de seguridad | Evaluar paso, contacto, malla y tensiones transferidas (incluidas cercas y estructuras) sobre una grilla adaptativa. Usar criterios tolerables con tiempo de despeje, masa corporal, capa superficial y norma/edición seleccionadas: IEEE Std 80, IEC/EN 50522 y RETIE para proyectos en Colombia. Mantener cálculo de campo separado de decisión normativa. |
| P1 | Pendiente | Capa superficial | Modelar gravilla/concreto/capa superficial en la respuesta del suelo y las tensiones tolerables según el método normativo seleccionado; validar casos publicados antes de mostrar estados de cumplimiento. |
| P1 | Pendiente | Corriente de falla y reparto de retorno | Modelar factor de decremento, división de corriente entre malla, neutros, cables de guarda, pantallas y tierras remotas. Aceptar impedancias/conexiones de la red externa y conservar el desglose de aportes. |
| P1 | Pendiente | Elementos metálicos con impedancia finita | Incorporar resistividad y sección del metal, conexiones y caída longitudinal para barras, uniones, pantallas, cercas, estructuras y neutros. Reemplazar el supuesto actual de conductor perfecto/equipotencial por una red eléctrica verificable. |
| P1 | Pendiente | Malla y geometría CAD | Crear importador DXF, asignar capas a tipos de elemento, detectar uniones/cruces reales y construir segmentos/nodos automáticamente. Añadir revisión visual de malla y puntos de consulta del mapa de potencial. |
| P1 | Pendiente | Segmentación graduada e incertidumbre numérica | Segmentos cortos cerca de puntas, esquinas, uniones y varillas, y largos en tramos rectos. Estimar el error de discretización en cada cálculo (dos refinamientos y extrapolación de Richardson) y reportarlo junto a cada magnitud, por ejemplo "S1 = 91,2 V ± 0,1 %". Criterio: igualar el paso convergido del Grid 1 (91,24 V) con menos de 500 segmentos. |
| P1 | Pendiente | Rendimiento de mallas grandes | Las mediciones de 2026-10-04 dan tiempo cúbico y memoria cuadrática en el número de segmentos. Comparar el solucionador denso con métodos iterativos o acelerados para pasar de 1 500 a más de 10 000 segmentos, como exigen las subestaciones grandes. Ampliar límites solo con benchmarks en la CPU de despliegue. |
| P1 | Hecho (base) | Integración asíncrona | Ejecutar cálculos largos desde Celery/worker aislado; API encola y devuelve identificador, estado, cancelación y resultado. Aplicar concurrencia limitada, timeout y reintentos idempotentes. |
| P1 | Pendiente | Prueba de contrato Python/C++ | Formalizar serialización, escaping, unidades, errores, límites y versionado. Evaluar JSON Lines o Protobuf para reemplazar el protocolo de tokens cuando se requieran objetos más ricos; conservar `Popen` como adaptador sencillo. |
| P2 | Pendiente | Impedancia compleja en AC | Extender la formulación a frecuencia y fasores para incluir inductancia, efecto piel, impedancia de conductores y acoplamientos mutuos. Validar por frecuencia y con redes de retorno representativas. |
| P2 | Pendiente | Transitorios e impulso | Desarrollar un solver transitorio separado para rayos/frentes rápidos, con parámetros dependientes de frecuencia y modelos físicos de electrodos. No extrapolar el solver cuasiestático actual. |
| P2 | Pendiente | Barridos paramétricos y optimización | Calcular alternativas de espaciamiento, profundidad, sección, varillas y capa superficial; comparar costo, seguridad y sensibilidad y publicar cada alternativa como una versión inmutable del artefacto. |
| P2 | Pendiente | Formatos de salida y visualización | Exportar raster/CSV de potencial, isolíneas, máximos locales, pares paso/contacto y distribución de corriente por elemento con unidades y leyenda. Agregar vista 3D de la malla con densidad de corriente y potenciales. |
| P2 | Pendiente | Memoria de cálculo | Generar un informe reproducible con entradas, modelo de suelo, geometría, hipótesis, norma/edición, resultados, diagnóstico numérico, incertidumbre y `trace` del motor, firmable por el ingeniero responsable. Los programas comerciales lo entregan de serie. |
| P2 | Pendiente | Electrodos no cilíndricos | Modelar placas, platinas, anillos curvos y cimentaciones o electrodos en concreto. Validar contra fórmulas cerradas (placa, anillo) y casos publicados. |
| P2 | Pendiente | Simulación de mediciones IEEE 81 | Simular la prueba de caída de potencial con la posición de los electrodos auxiliares y el acoplamiento de los cables de prueba, para comparar la resistencia medida en campo con la calculada. Ayuda a cerrar la recomendación 5 con datos de campo. |
| P2 | Pendiente | Suelo heterogéneo | Capas verticales o inclinadas, volúmenes finitos de distinta resistividad (rellenos, rocas, agua) y tratamientos de suelo. Depende de "Suelo estratificado". |
| P3 | Evaluar | Interferencia AC y protección catódica | Acoplamiento inductivo, conductivo y capacitivo de líneas de transmisión con tuberías y vías férreas. Lo cubren CDEGS y XGSLab; queda fuera del alcance actual hasta que lo pida un proyecto. |
| P2 | Pendiente | Observabilidad y operación | Registrar versión del binario, duración, segmentos/puntos, timeout, fallos y tamaños de salida; incorporar métricas, límites de cola, alertas, runbook y política de retención. |

## Resultado de los P0 (2026-10-04)

- **Validación:** `validation/reference_cases.json` contiene 8 casos y 18 comprobaciones: varilla simple, conductor horizontal, dos varillas unidas, grupos acoplados con inyecciones independientes, varilla flotante (fórmulas de Dwight, IEEE Std 142-2007), mallas IEEE Std 80-2013 Anexo H Grid 1 y Grid 2 (rango CDEGS/ETAP/WinIGS) y Anexo B Ejemplo 1 (EPRI TR-100622). Todas pasan. El paquete para el revisor está en `validation/REVIEW.md`, generado con `validation/review_report.py`. Incluye resultados, fuentes, desviaciones conocidas, convergencia, preguntas abiertas y una tabla de dictamen para firmar. Las mayores desviaciones son −1,5 % en el contacto máximo del Anexo B y +1,9 % en el paso S1 del Grid 1. Esta última está documentada en el caso: el motor converge a 91,24 V, y con segmentos de 3,5–7 m reproduce el rango publicado, así que la referencia probablemente está sub-resuelta en la esquina. Una comprobación de regresión fija ese valor convergido con tolerancia de 0,5 %. **Pendiente:** confirmar con valores por programa. La Tabla 3 del estudio de ELEK los trae, pero su sitio bloquea el acceso automatizado y hay que revisarla manualmente. Cada referencia registra fuente, método y edición. **Pendiente:** firma de tolerancias por un ingeniero competente y cotejo de los valores del Anexo H/B con una copia licenciada de IEEE 80. Los valores se transcribieron del script de validación del repositorio `protectionpro`, porque no se encontró un motor de referencia abierto con licencia adecuada. El paquete `earthing` (GPLv3) se descartó como referencia: su modelo de discos converge lento y da T1 = 327 V cuando el rango publicado es 195–201 V. Ningún caso de referencia cubre todavía una malla con conductor flotante en suelo homogéneo; el Grid 4 del Anexo H usa suelo estratificado (P1).
- **Convergencia:** `validation/convergence.py`. Del penúltimo al último refinamiento, en el Grid 1 la resistencia cambia 0,00 %, T1 0,02 %, el contacto máximo 0,01 % y el paso 0,17 %. En el Grid 2 los cambios son 0,01 %, 0,06 %, 0,06 % y 0,73 %. Con rejillas de búsqueda de 0,5 m a 0,25 m el contacto máximo cambia ≤0,02 %. El paso cerca de varillas y esquinas exige segmentos ≤1 m.
- **Diagnóstico:** error hacia atrás normado, estimación de condición en norma 1 (Hager/Higham), razón de pivotes, error de balance por grupo y dispersión del potencial del grupo. Se rechazan resultados no finitos, con error hacia atrás >1e-10, condición >1e13 o balance >1e-9; se advierte si la condición supera 1e10 o no hay inyección.
- **Trazabilidad:** cada resultado incluye protocolo, versión del solver, método, hipótesis, unidades, SHA-256 de la solicitud y del binario, fecha, duración, geometría discretizada y origen de cada inyección. Desde el 2026-10-04 cada cálculo de un artefacto se guarda en `calculos_potencial_tierras` (migración 0008), ligado a (artefacto, versión), con parámetros, resultado y `trace` completo, incluidos los hashes de cada lote de puntos.
- **Límites:** validación espejo en Python y C++. Medidos con `validation/benchmark.py`: 1500 segmentos, 100 000 puntos, 2e7 puntos × segmentos, timeout de 60 s y 512 MiB en Linux. Re-medidos el 2026-10-04 en la imagen de despliegue (Linux aarch64 en Docker sobre Apple M5 Pro, `validation/benchmark-linux-aarch64.json`): el peor caso permitido (1 200 segmentos, 16 641 puntos) tarda 1,03 s con el límite de 512 MiB activo. **Pendiente:** repetir en la CPU real de producción, que aún no está definida.

## Integración con artefactos (2026-10-04)

- `POST /api/v1/projects/{project_id}/artefactos-diseno-tierras/{artifact_id}/versions/{version}/calculos-potencial` encola un cálculo y responde 202 con su identificador. Parámetros opcionales: radio del conductor (por defecto 2/0 AWG, 5,25 mm), discretización (1 m) y paso de la rejilla superficial (0,25, 0,5 o 1 m).
- `GET .../versions/{version}/calculos-potencial` lista los cálculos de una versión; `GET .../{artifact_id}/calculos-potencial/{id}` devuelve estado, resultado y `trace`; `POST .../{id}/cancelar` cancela un cálculo pendiente o en curso. Si el motor ya estaba corriendo, su resultado se descarta.
- La tarea Celery `spat.calculate_artifact_potential` es idempotente. Una nueva entrega solo ejecuta cálculos pendientes, o en curso si llevan más de 15 minutos sin actualizarse (worker caído). Límite de tiempo: 600 s.
- Estados: `pending`, `running`, `completed`, `failed` (error del motor), `rejected` (modelo no soportado) y `cancelled`. Se rechazan los artefactos con capas de suelo de resistividades distintas y las mallas que superan el límite de segmentos.
- El resultado trae resistencia, GPR, contacto máximo dentro del perímetro (con su ubicación) y paso máximo a 1 m. El paso se busca primero en la rejilla y luego en 16 direcciones alrededor de los 20 puntos más críticos. También incluye el diagnóstico del motor y advertencias del modelo: corriente de falla sin factor de división, sin cercas externas, sin capa superficial ni criterios tolerables.
- **Pendiente:** cola Celery dedicada para no competir con otras tareas (hoy comparte el worker con concurrencia 2), probar la migración 0008 en PostgreSQL (los tests usan SQLite) y exponer los cálculos en el frontend.

## Brechas frente al mercado

Comparación con CDEGS (SES), XGSLab (SINT), SafeGrid (ELEK), ETAP Ground Grid y WinIGS, a partir de la documentación pública de cada producto y sin verificación individual. En suelo homogéneo, el motor queda dentro del rango publicado de esos programas en 7 de las 8 magnitudes de los Grids 1–2 del Anexo H.

| Capacidad del mercado | Estado en SPAT | Fila del backlog |
|---|---|---|
| Suelo de 2 capas y multicapa | No | Suelo estratificado (P1) |
| Interpretación de mediciones de resistividad | No | Modelo de suelo desde mediciones (P1) |
| Validación con suelo estratificado (Anexo H Grids 3–6) | No | Validación de suelo estratificado (P1) |
| Criterios tolerables IEEE 80 / IEC / EN 50522 | No | Verificación de tensiones de seguridad (P1), Capa superficial (P1) |
| Reparto de corriente de falla (cables de guarda, neutros, pantallas) | No | Corriente de falla y reparto de retorno (P1) |
| Impedancia del conductor y caída longitudinal | No | Elementos metálicos con impedancia finita (P1) |
| Importación CAD y segmentación automática | No | Malla y geometría CAD (P1), Segmentación graduada (P1) |
| Mallas de más de 10 000 segmentos | No (límite de 1 500) | Rendimiento de mallas grandes (P1) |
| Respuesta en frecuencia y rayo | No | Impedancia compleja en AC (P2), Transitorios e impulso (P2) |
| Optimización de diseño | No | Barridos paramétricos y optimización (P2) |
| Informe de cálculo | No | Memoria de cálculo (P2) |
| Gráficas 2D/3D de potencial | No | Formatos de salida y visualización (P2) |
| Placas, platinas y cimentaciones | No | Electrodos no cilíndricos (P2) |
| Simulación de pruebas de campo | No | Simulación de mediciones IEEE 81 (P2) |
| Suelo heterogéneo y volúmenes finitos | No | Suelo heterogéneo (P2) |
| Interferencia AC en tuberías | No | Interferencia AC y protección catódica (P3) |
| Diagnóstico numérico expuesto, trazabilidad por hash, código abierto vía API | **Sí** | Ventaja propia; mantenerla en cada feature nueva |

Orden sugerido para alcanzar paridad en diseños reales: suelo estratificado → modelo de suelo desde mediciones → validación con los Grids 3–6 → verificación de seguridad y capa superficial → reparto de corriente de falla. Sin esas cinco filas, el motor no puede reemplazar a un programa comercial en un proyecto.

## Recomendación de ejecución

1. **Desarrollo local:** compilar una vez con `make potential-engine`; el cliente Python invoca el ejecutable por `Popen`. Usar lotes pequeños y homogéneos, y fijar `SPAT_POTENTIAL_ENGINE` si el binario se instala fuera de la ruta predeterminada.
2. **API interactiva:** permitir cálculo síncrono solo para mallas pequeñas cuyo tiempo máximo se haya medido. Aplicar timeout y límite de concurrencia para no agotar workers de FastAPI.
3. **Cálculos de proyecto o mallas grandes:** enviar un job a Celery y ejecutar el binario en un worker aislado con CPU/memoria limitadas. Persistir entradas, versiones, logs técnicos y resultado junto al artefacto versionado. No hacer el cálculo dentro del proceso HTTP.
4. **Producción:** fijar la versión/hash del binario en una imagen reproducible y desplegarlo como worker C++ dedicado si el volumen o la escala lo justifican. El ejecutable actual procesa una solicitud y termina; por eso `Popen` lanza un proceso por cálculo. Un daemon con pipes persistentes o gRPC solo conviene cuando mediciones muestren que el costo de arranque es relevante.
5. **Antes de habilitar decisiones de seguridad:** completar los P0, acordar referencias y tolerancias con un ingeniero competente, y comparar contra mediciones de campo. Los estándares tienen alcance y ediciones específicas; el motor debe guardar la edición elegida por proyecto, no inferirla.
