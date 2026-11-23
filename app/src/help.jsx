import React from "react";

// Help cards for the design forms. Equations follow IEEE 80-2013; each card says what the value means,
// how it enters the calculation and where the number usually comes from.

const S = ({ children }) => <sub>{children}</sub>;
const P = ({ children }) => <sup>{children}</sup>;

// ── Small figures ──────────────────────────────────────────────────────────────────────────────────────
const fig = (children, label) => <svg viewBox="0 0 300 120" role="img" aria-label={label}>{children}</svg>;
const ground = <><rect x="0" y="78" width="300" height="42" fill="#efe7da"/><path d="M0 78h300" stroke="#b8a687" strokeWidth="1.5"/></>;
const person = (x, y = 78, arm = null) => <g stroke="#33433d" strokeWidth="2.2" fill="none" strokeLinecap="round"><circle cx={x} cy={y - 50} r="6" fill="#fff"/><path d={`M${x} ${y - 44}v22M${x} ${y - 22}l-7 22M${x} ${y - 22}l7 22`}/>{arm || <path d={`M${x} ${y - 38}l-9 10M${x} ${y - 38}l9 10`}/>}</g>;

const FIG_TOUCH_STEP = fig(<>{ground}
  <rect x="40" y="22" width="10" height="56" fill="#c9d6d0" stroke="#7d8e86"/><path d="M45 78v22H150" stroke="#287f70" strokeWidth="2" strokeDasharray="4 3" fill="none"/>
  {person(78, 78, <path d="M78 40 51 34M78 40l9 10" />)}
  <text x="62" y="16" fontSize="10" fill="#a8443c" fontWeight="700">contacto</text><path d="M52 34c10-18 20-18 26 40" stroke="#a8443c" strokeWidth="1.5" fill="none" strokeDasharray="3 3"/>
  {person(220)}<path d="M213 100h14" stroke="#6c3483" strokeWidth="2"/><text x="200" y="114" fontSize="10" fill="#6c3483" fontWeight="700">paso · 1 m</text>
  <text x="120" y="112" fontSize="9" fill="#287f70">malla enterrada</text></>, "Tensión de contacto: mano en la estructura y pies en el suelo. Tensión de paso: entre los dos pies.");

const FIG_SURFACE = fig(<><rect x="0" y="70" width="300" height="50" fill="#efe7da"/><rect x="0" y="62" width="300" height="12" fill="#d9dcd6"/>
  {Array.from({ length: 30 }, (_, i) => <circle key={i} cx={5 + i * 10} cy={66 + (i % 3) * 2} r="2" fill="#9ea39a"/>)}
  {person(150, 62)}<path d="M240 62v12" stroke="#33433d"/><path d="M236 62h8M236 74h8" stroke="#33433d"/><text x="250" y="71" fontSize="10" fill="#33433d">h<tspan fontSize="7" dy="2">s</tspan></text>
  <text x="12" y="58" fontSize="10" fill="#5f6d66">grava · ρ<tspan fontSize="7" dy="2">s</tspan></text><text x="12" y="100" fontSize="10" fill="#8a7450">suelo natural · ρ</text></>, "Capa superficial de grava de espesor hs sobre el suelo natural.");

const FIG_SPLIT = fig(<>{ground}
  <path d="M30 20h240" stroke="#7d8e86" strokeWidth="2"/><text x="200" y="14" fontSize="10" fill="#5f6d66">cable de guarda / neutro</text>
  <path d="M150 20v40" stroke="#a8443c" strokeWidth="3"/><path d="M150 60 150 78" stroke="#a8443c" strokeWidth="3"/><text x="156" y="48" fontSize="10" fill="#a8443c">3I<tspan fontSize="7" dy="2">0</tspan></text>
  <path d="M150 30H60" stroke="#a8443c" strokeWidth="2" strokeDasharray="4 3"/><text x="62" y="42" fontSize="10" fill="#7d8e86">(1 − S<tspan fontSize="7" dy="2">f</tspan>) vuelve por los cables</text>
  <path d="M110 92h80" stroke="#287f70" strokeWidth="3"/><path d="M150 78v14" stroke="#a8443c" strokeWidth="3"/><text x="196" y="96" fontSize="10" fill="#287f70">S<tspan fontSize="7" dy="2">f</tspan>·3I<tspan fontSize="7" dy="2">0</tspan> a la malla</text></>, "Solo una fracción Sf de la corriente de falla entra al suelo por la malla.");

const FIG_WENNER = fig(<>{ground}
  {[60, 120, 180, 240].map((x, i) => <g key={x}><path d={`M${x} 60v32`} stroke="#33433d" strokeWidth="3"/><text x={x - 4} y="54" fontSize="11" fill="#33433d" fontWeight="700">{"AMNB"[i]}</text></g>)}
  <path d="M60 30h180" stroke="#287f70" strokeWidth="1.5"/><path d="M60 30v26M240 30v26" stroke="#287f70" strokeWidth="1.5"/><text x="130" y="24" fontSize="10" fill="#287f70">corriente I entre A y B</text>
  {[[60, 120], [120, 180], [180, 240]].map(([a, b]) => <g key={a}><path d={`M${a} 104h${b - a}`} stroke="#8a7450" strokeWidth="1.2"/><text x={(a + b) / 2 - 3} y="116" fontSize="10" fill="#8a7450">a</text></g>)}
  <text x="122" y="74" fontSize="10" fill="#33433d">V medido entre M y N</text></>, "Arreglo Wenner: cuatro electrodos en línea separados una distancia a.");

// ── Cards ──────────────────────────────────────────────────────────────────────────────────────────────
export const HELP = {
  standards: {
    title: "Norma de seguridad",
    text: ["Define cómo se calculan las tensiones que una persona tolera y contra qué se compara el diseño.", "IEEE 80-2013 es la guía de referencia internacional para mallas de subestaciones de corriente alterna: limita las tensiones de contacto y de paso según el tiempo de despeje, el peso corporal y la capa superficial."],
    figure: FIG_TOUCH_STEP,
  },
  evaluated_standards: {
    title: "Estándares a evaluar",
    text: ["Cada alternativa de Matherra debe cumplir todos los estándares marcados; si marcas varios, manda el más exigente en cada criterio.", "IEEE 80-2013: límites de contacto y paso por el método del cuerpo humano. RETIE (Colombia): el reglamento técnico de instalaciones eléctricas; sus límites concretos los fija el perfil normativo fijado al proyecto."],
  },
  normative_profile: {
    title: "Perfil normativo del proyecto",
    text: ["Un conjunto revisado de criterios para una jurisdicción: qué controles de seguridad son obligatorios, cuándo aplican y de qué cláusula salen. Matherra lo usa para decidir si una alternativa es factible.", "La app trae un perfil por cada norma (IEEE 80-2013 y RETIE 2026) y te sugiere el de la norma que elegiste arriba. Si tu caso necesita otro criterio, crea un perfil propio con «Crear perfil con mi criterio». Fijarlo queda guardado en el proyecto y lo usan todas las búsquedas siguientes."],
  },
  exposure_class: {
    title: "Clase de exposición",
    text: ["Quién puede quedar expuesto a las tensiones de la malla durante una falla.", "Público: personas sin entrenamiento que pueden acercarse (cercas perimetrales, vías, zonas accesibles). Ocupacional: personal entrenado y autorizado dentro de la subestación.", "El perfil normativo decide qué límites y qué peso corporal aplica a cada clase; para público suelen ser más estrictos."],
    figure: FIG_TOUCH_STEP,
  },
  fault_current: {
    title: "Corriente de falla",
    text: "Corriente simétrica de falla a tierra (3I₀) en la subestación. La malla solo disipa la parte que entra al suelo por ella; el resto vuelve por cables de guarda y neutros.",
    formula: [<>I<S>G</S> = D<S>f</S> · S<S>f</S> · 3I<S>0</S></>, <>GPR = I<S>G</S> · R<S>g</S></>],
    where: "D_f: factor de decremento (asimetría) · S_f: factor de reparto · R_g: resistencia de malla",
    source: "Estudio de cortocircuito del operador de red o del proyecto, para la falla monofásica a tierra.",
    figure: FIG_SPLIT,
  },
  injection_current: {
    title: "Corriente de falla inyectada",
    text: "La parte de la corriente de falla que entra al suelo por la malla (I_G). Si en Parámetros definiste un factor de reparto S_f, ya viene aplicado.",
    formula: <>I<S>G</S> = D<S>f</S> · S<S>f</S> · 3I<S>0</S></>,
    figure: FIG_SPLIT,
  },
  clearing_time: {
    title: "Tiempo de despeje tₛ",
    text: "Cuánto dura la falla hasta que la protección la despeja. Es el tiempo de exposición de la persona: cuanto más corto, mayor tensión tolera el cuerpo.",
    formula: [<>E<S>contacto,50</S> = (1000 + 1,5·C<S>s</S>·ρ<S>s</S>) · 0,116 / √t<S>s</S></>, <>E<S>paso,50</S> = (1000 + 6·C<S>s</S>·ρ<S>s</S>) · 0,116 / √t<S>s</S></>],
    where: "Para 70 kg se usa 0,157 en lugar de 0,116.",
    typical: "0,1 a 0,5 s con protección primaria; hasta 1 s si se considera la de respaldo.",
    source: "Coordinación de protecciones del proyecto.",
  },
  body_weight: {
    title: "Peso corporal",
    text: "IEEE 80 da la tensión tolerable para personas de 50 kg o de 70 kg. 50 kg es el criterio conservador y el habitual cuando puede haber público.",
    formula: <>k = 0,116 (50 kg) · k = 0,157 (70 kg)</>,
    where: "k multiplica el término de la tensión tolerable: E = (1000 + …·C_s·ρ_s) · k / √t_s",
  },
  surface_resistivity: {
    title: "Resistividad superficial ρₛ",
    text: "La capa de grava o asfalto sobre el terreno aumenta la resistencia entre los pies y el suelo, y con ello la tensión que una persona tolera.",
    formula: <>C<S>s</S> = 1 − 0,09 · (1 − ρ/ρ<S>s</S>) / (2h<S>s</S> + 0,09)</>,
    where: "C_s: factor de reducción · ρ: resistividad del suelo · h_s: espesor de la capa",
    typical: "Grava triturada húmeda: 3.000 a 5.000 Ω·m. Asfalto: 10.000 Ω·m o más. Sin capa: igual a la del suelo.",
    figure: FIG_SURFACE,
  },
  surface_thickness: {
    title: "Espesor superficial hₛ",
    text: "Espesor de la capa de grava o asfalto. Entra en el factor C_s: más espesor, más protección, con rendimientos decrecientes.",
    formula: <>C<S>s</S> = 1 − 0,09 · (1 − ρ/ρ<S>s</S>) / (2h<S>s</S> + 0,09)</>,
    typical: "0,08 a 0,15 m de grava.",
    figure: FIG_SURFACE,
  },
  surface_layer_present: {
    title: "¿Existe capa superficial?",
    text: "Indica si sobre el terreno hay una capa de grava o asfalto. Si no la hay, la resistividad superficial es la del suelo natural y C_s = 1.",
    figure: FIG_SURFACE,
  },
  split_factor: {
    title: "Factor de reparto Sƒ",
    text: "Fracción de la corriente de falla que entra al suelo por la malla. El resto regresa a la fuente por cables de guarda, neutros y pantallas.",
    formula: <>I<S>g</S> = S<S>f</S> · 3I<S>0</S></>,
    typical: "Déjalo vacío para usar 1: toda la corriente entra por la malla, el caso más conservador.",
    source: "Estudio de distribución de corrientes o el método gráfico del anexo C de IEEE 80.",
    figure: FIG_SPLIT,
  },
  x_over_r: {
    title: "Relación X/R",
    text: "Relación entre reactancia y resistencia de la red en el punto de falla. Determina la componente de corriente continua de la falla y con ella el factor de decremento D_f.",
    formula: [<>D<S>f</S> = √(1 + (T<S>a</S>/t<S>f</S>) · (1 − e<P>−2t<S>f</S>/T<S>a</S></P>))</>, <>T<S>a</S> = X / (ω · R)</>],
    typical: "Sin dato se toma D_f = 1.",
    source: "Estudio de cortocircuito.",
  },
  thermal_standard: {
    title: "Norma de dimensionamiento",
    text: "Con qué expresión se calcula la sección mínima del conductor para soportar la falla sin dañarse. Cada norma define sus materiales y temperaturas.",
  },
  conductor_material: {
    title: "Material del conductor",
    text: "Define las constantes térmicas (capacidad calorífica, resistividad y coeficiente de temperatura) con las que se calcula la sección mínima.",
    formula: <>A<S>mm²</S> = I / √( (TCAP · 10<P>−4</P>) / (t<S>c</S> · α<S>r</S> · ρ<S>r</S>) · ln((K<S>0</S> + T<S>m</S>) / (K<S>0</S> + T<S>a</S>)) )</>,
    where: "IEEE 80-2013, ecuación de Onderdonk generalizada",
  },
  joint_type: {
    title: "Tipo de unión",
    text: "Las uniones son el punto débil térmico de la malla: la temperatura máxima admisible la fija la unión, no el conductor.",
    typical: "Soldadura exotérmica: hasta la fusión del cobre (≈ 1.083 °C). Brasada: ≈ 450 °C. Apernada o a presión: ≈ 250 °C.",
  },
  conductor_section: {
    title: "Sección elegida",
    text: "La sección del conductor que vas a instalar. Se compara con la mínima térmica; también conviene revisar la resistencia mecánica (en la práctica, no menos de 2/0 AWG ≈ 67 mm² de cobre).",
  },
  max_temperature: {
    title: "Temperatura máxima Tₘ",
    text: "La temperatura que puede alcanzar el conductor durante la falla sin dañar las uniones. Depende del tipo de unión y del fabricante (IEEE 837).",
    typical: "250 °C para uniones apernadas; 450 °C brasadas; hasta 1.083 °C con soldadura exotérmica.",
  },
  thermal_duration: {
    title: "Duración térmica tᴄ",
    text: "El tiempo durante el que el conductor debe soportar la corriente. Suele tomarse el de la protección de respaldo, por eso es igual o mayor que el tiempo de despeje.",
    typical: "0,5 a 3 s.",
  },
  ambient_temperature: {
    title: "Temperatura ambiente Tₐ",
    text: "Temperatura del conductor antes de la falla (la del suelo o del ambiente). Es el punto de partida del calentamiento.",
    typical: "40 °C es un valor conservador habitual.",
  },
  voltage_level: {
    title: "Nivel de tensión",
    text: "RETIE fija distintas reglas de dimensionamiento según el nivel de tensión de la instalación.",
  },
  soil_layers_fit: {
    title: "Capas del modelo de suelo",
    text: ["El ajuste busca las resistividades y espesores que mejor reproducen tus lecturas de campo. Dos capas describen la mayoría de los suelos; más capas solo si las lecturas lo justifican.", "Cada capa necesita al menos dos lecturas: con pocas mediciones el ajuste se sobreajusta."],
  },
  soil_resistivity: {
    title: "Resistividad del suelo",
    text: "Qué tanto se opone el terreno al paso de la corriente. Es el dato que más pesa en la resistencia de malla y en las tensiones.",
    typical: "Arcilla húmeda 10–100 Ω·m · arena 100–2.500 Ω·m · grava 1.000–10.000 Ω·m · roca más de 1.000 Ω·m.",
  },
  wenner: {
    title: "Método Wenner",
    text: "Cuatro electrodos en línea, separados una misma distancia a. Se inyecta corriente por los extremos y se mide la tensión entre los internos. Aumentar a mide capas más profundas.",
    formula: <>ρ<S>a</S> = 2π · a · R</>,
    where: "R = V / I medido por el telurómetro",
    figure: FIG_WENNER,
  },
  matherra_budget: {
    title: "Presupuesto de evaluaciones",
    text: "Cuántas veces Matherra puede llamar al motor eléctrico para evaluar trazados. Más evaluaciones exploran más alternativas, pero la búsqueda tarda más.",
    typical: "150 es un buen equilibrio; 60 para una prueba rápida.",
  },
  matherra_orthogonal: {
    title: "Solo trazados ortogonales",
    text: "Limita los conductores nuevos a direcciones horizontales y verticales, como se construyen habitualmente. Desmárcalo para permitir diagonales.",
  },
  matherra_redundant: {
    title: "Sin cables sueltos",
    text: "Cada conductor nuevo debe quedar en un lazo cerrado, así un corte nunca deja cobre aislado. Solo se permite una cola recta corta que termina en una varilla. Lo que tu diseño ya tenía se respeta. Desmárcalo para explorar formas libres.",
    typical: "Cola máxima hacia una varilla: 3 m.",
  },
  matherra_rates: {
    title: "Tarifas",
    text: "Precio unitario de cada partida con el que Matherra compara alternativas. Puedes tomarlas del catálogo aprobado o escribirlas con su fuente, que queda en el estudio para trazabilidad.",
    formula: <>Costo = Σ cantidad<S>i</S> · tarifa<S>i</S></>,
  },
  trench_width: {
    title: "Ancho de zanja",
    text: "Con el largo y la profundidad de la malla da el volumen de excavación que se cotiza.",
    formula: <>V<S>excavación</S> = largo de zanja · ancho · profundidad</>,
    typical: "0,3 a 0,5 m.",
  },

  // ── Normative profile editor (super_admin) ───────────────────────────────────────────────────────────
  profile_editor: {
    title: "Crear un perfil con tu criterio",
    text: ["Úsalo cuando los perfiles de norma no se ajustan a tu caso: una norma de tu empresa, una exigencia del cliente, otro país o un alcance distinto.", "Lo más rápido es heredar de la norma que ya elegiste y cambiar solo lo necesario. Se crea en dos pasos: lo guardas como borrador y, cuando revisaste cada regla, lo marcas como revisado. Es tuyo: solo tú lo ves y lo fijas a tus proyectos."],
  },
  profile_suggested: {
    title: "Perfil sugerido",
    text: ["Es el perfil de la norma que marcaste en «Estándares a evaluar». Es lo más común: si evalúas con RETIE, el proyecto usa el perfil RETIE.", "Puedes fijarlo con un clic o elegir otro (por ejemplo, uno propio)."],
  },
  profile_scope: {
    title: "Dónde se publica",
    text: ["Catálogo compartido: lo ven y lo fijan todos los usuarios cuando lo marcas como revisado. Úsalo solo para perfiles revisados por un profesional competente.", "Solo para mí: un perfil propio, como el que crearía cualquier diseñador."],
  },
  profile_inherit: {
    title: "Heredar de norma",
    text: ["Llena el formulario con una norma que ya existe, para no empezar de cero. Después cambias solo lo que tu caso necesita. Aparece primero (★) la norma que elegiste en «Estándares a evaluar».", "Normas: los perfiles IEEE 80 y RETIE que trae la app. Catálogo: los publicados por un administrador. Mis perfiles: los tuyos; si heredas de uno tuyo, lo que guardes será su versión siguiente y la anterior no cambia.", "Personalizado: un formulario en blanco para escribir tu criterio desde cero."],
    typical: "Para Colombia, hereda de «RETIE 2026 · subestaciones» y ajusta lo que tu proyecto necesite.",
  },
  profile_id: {
    title: "Identificador del perfil",
    text: ["Nombre técnico, único y permanente: minúsculas, números, puntos, guiones. Se usa para encontrar el perfil y para versionarlo.", "Si ya existe un perfil con este identificador, guardar crea la versión siguiente de ese perfil. Si no existe, crea un perfil nuevo."],
    typical: "país.norma.tipo, por ejemplo co.retie.substation_ac",
  },
  profile_title: {
    title: "Título",
    text: "El nombre que verán los diseñadores al elegir el perfil en su proyecto. Di la norma, la edición y a qué instalaciones aplica.",
    typical: "Colombia — subestaciones de corriente alterna — RETIE 2026",
  },
  profile_jurisdiction: {
    title: "Jurisdicción",
    text: "El país o región donde rige la norma. Matherra compara este valor con el país del proyecto y no deja optimizar si no coinciden.",
    typical: "Colombia",
  },
  profile_installation: {
    title: "Tipo de instalación",
    text: "A qué instalaciones aplica el perfil. Un perfil para subestaciones no debe usarse, por ejemplo, para una vivienda o una torre de transmisión.",
    typical: "AC substation (subestación de corriente alterna)",
  },
  profile_description: {
    title: "Descripción",
    text: "Alcance, exclusiones y advertencias que el diseñador debe conocer antes de usar el perfil: clase de tensión, tipo de acceso, supuestos.",
  },
  required_criteria: {
    title: "Criterios obligatorios del perfil",
    text: ["Los criterios de seguridad que el perfil se compromete a cubrir. Para poder marcarlo como revisado, cada criterio marcado necesita al menos una regla obligatoria que aplique.", "Contacto: tensión entre la mano y los pies al tocar una estructura. Paso: tensión entre los dos pies. Transferidas: tensión que un elemento metálico lleva fuera de la malla (rieles, tuberías, cercas)."],
    figure: FIG_TOUCH_STEP,
  },
  profile_rule: {
    title: "Reglas",
    text: ["Cada regla es un requisito de la norma: qué controla, si es obligatoria o solo una guía, cuándo aplica, cómo se verifica y de qué cláusula sale.", "Las reglas con ⚠ tienen algo pendiente: abre la tarjeta para ver qué falta."],
  },
  rule_category: {
    title: "Tipo de regla",
    text: ["Obligatoria: la norma la exige; si no se cumple, el diseño no cumple.", "Guía: un valor de referencia o recomendación; se informa pero no bloquea.", "Constructiva y comercial: límites prácticos o de costo (por ejemplo, largo máximo de varilla disponible)."],
  },
  rule_criterion: {
    title: "Criterio o variable",
    text: ["Criterio: el control de seguridad que cubre la regla (contacto, paso o transferidas). Úsalo en reglas obligatorias de seguridad.", "Variable: un dato del diseño que la regla limita, por ejemplo la longitud de varilla o la resistencia de puesta a tierra. Si das mínimo y máximo, Matherra solo explora valores dentro de ese rango."],
  },
  rule_applicability: {
    title: "Aplicabilidad",
    text: ["Aplica: un profesional confirmó que la regla rige para el alcance del perfil.", "No aplica: confirmado que no rige (explica por qué en las condiciones).", "Desconocida: falta confirmarlo. Un perfil con criterios obligatorios cuya regla está en «desconocida» no se puede marcar como revisado: la falta de un dato nunca se convierte en cumplimiento."],
  },
  rule_conditions: {
    title: "Condiciones de aplicabilidad",
    text: "Cuándo rige la regla y qué hay que confirmar, una por línea. Por ejemplo: exposición pública u ocupacional, si hay capa superficial, nivel de tensión, tipo de electrodo.",
  },
  rule_verification: {
    title: "Método de verificación",
    text: "Cómo se comprueba que el diseño cumple: qué valor calculado se compara con qué límite y con qué datos. Así otra persona puede repetir la verificación.",
    typical: "Comparar la tensión de contacto calculada con el límite de la Tabla 3.12.1.a para la exposición y el tiempo de despeje del proyecto.",
  },
  rule_expression: {
    title: "Requisito",
    text: "Lo que dice la norma, en palabras, con sus valores. Es lo que leerá quien revise el estudio.",
  },
  rule_source: {
    title: "Fuente",
    text: ["De dónde sale la regla. Para reglas obligatorias y guías son necesarios el documento, la edición y la cláusula; el enlace al texto oficial ayuda a revisarla.", "Esta fuente aparece en la trazabilidad del estudio."],
    typical: "RETIE, Resolución 40284 de 2026, Libro 3 · 2026-06-23 · Art. 3.12.1 literal g, Tabla 3.12.1.a",
  },
  rule_bounds: {
    title: "Límites de la variable",
    text: "Opcional. Mínimo y máximo permitidos para la variable, con su unidad. Si varias reglas que aplican limitan la misma variable, se usa el rango más estrecho.",
    typical: "Longitud de varilla: 1,5 a 6 m",
  },
  profile_review: {
    title: "Marcar como revisado",
    text: ["Desde ese momento puedes fijar esta versión a tus proyectos (o, si es del catálogo, cualquiera puede) y Matherra la usa para decidir si un diseño cumple.", "Marcarlo dice que revisaste cada regla y respondes por ese criterio en el estudio que firmas. Una versión revisada ya no se edita: los cambios van en una versión nueva."],
  },
  matherra_unit_rates: {
    title: "No conozco los precios",
    text: ["Pone todas las tarifas en 1. Así Matherra busca el diseño que cumple con la menor cantidad de material: más metros de conductor, más varillas o más excavación cuestan más.", "Si el ancho de zanja está vacío, usa 0,4 m (valor típico) y lo anota como supuesto. Sirve para probar y comparar diseños sin una cotización. Los costos que veas serán relativos, no dinero, y el estudio lo dice. Ojo: un metro de conductor pesa igual que una varilla o un m³ de excavación; con precios reales el orden de las alternativas puede cambiar."],
    formula: <>Costo relativo = Σ cantidad<S>i</S> · 1</>,
  },
};
