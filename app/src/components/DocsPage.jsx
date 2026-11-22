import React, { useEffect, useState } from "react";
import { BrandMark } from "./BrandMark.jsx";
import { ArrowLeft } from "lucide-react";
import { CONTACT_EMAIL, LegalLinks, appOrigin } from "./LandingPage.jsx";
import "../landing.css";

// Public user guide (/ayuda). Plain "we" voice, no jargon beyond the engineering terms the user already knows.
// Keep it in step with what the app really does: if a screen or a limit changes, change the guide too.
const GUIDE = [
  {
    id: "empezar",
    title: "Crear tu cuenta",
    body: [
      "Entra a «Crear cuenta» y continúa con tu cuenta de Google. La cuenta se crea en un clic y es gratis.",
      "Si ya tienes cuenta con correo y contraseña, usa «Iniciar sesión». Si olvidaste la contraseña, pide un enlace para cambiarla desde la misma pantalla.",
      "Puedes crear proyectos sin pagar. Para que el agente trabaje en ellos necesitas un plan activo o un código de licencia.",
    ],
  },
  {
    id: "planes",
    title: "Planes y uso del agente",
    body: [
      "Cada plan es mensual y trae una cantidad de uso del agente, medida en tokens. Lo que hace el agente consume tokens: responder en el chat, leer tus documentos y proponer o cambiar la malla. En «Plan y facturación» ves cuánto te queda.",
      "Compras o cambias de plan en «Plan y facturación». El cobro se hace en pesos colombianos con Mercado Pago; tus datos de tarjeta nunca pasan por nosotros.",
      "Si tienes un código de licencia, lo canjeas en esa misma pantalla. Puedes cancelar cuando quieras y sigues teniendo acceso hasta el final del mes que ya pagaste.",
    ],
  },
  {
    id: "proyecto",
    title: "Crear un proyecto",
    body: [
      "Un proyecto es una puesta a tierra: una subestación, una planta o un edificio. Dale un nombre y, si quieres, ubícalo en el mapa.",
      "Todo lo del proyecto queda en un solo lugar: los documentos, los datos que sacamos de ellos, la malla, los cálculos y los estudios que publiques.",
    ],
  },
  {
    id: "documentos",
    title: "Subir tus documentos",
    body: [
      "Arrastra o adjunta tus archivos en el chat del proyecto: PDF, Word (.docx), Excel (.xlsx), CSV, planos DXF e imágenes (PNG o JPG). Máximo 20 MB por archivo.",
      "Leemos los documentos y sacamos los datos que necesita el diseño. Cada dato muestra de dónde salió (el documento, tú en el chat o un valor supuesto), para que lo revises.",
      "Si falta un dato, usamos un valor razonable, te avisamos y seguimos. Lo confirmas o lo cambias después.",
    ],
  },
  {
    id: "suelo",
    title: "El terreno",
    body: [
      "Con tus mediciones de resistividad armamos el modelo del suelo, de 2 o más capas. Sirven sondeos Wenner o Schlumberger: pégalos en el chat o sube un CSV o XLSX.",
      "Te mostramos la gráfica del ajuste entre tus mediciones y el modelo, para que veas si tiene sentido antes de seguir.",
    ],
  },
  {
    id: "falla",
    title: "Datos de la falla",
    body: [
      "Para revisar la seguridad necesitamos la corriente de falla y el tiempo de despeje. Si hay capa superficial (grava, por ejemplo), también su resistividad y espesor.",
      "Mientras falten, el proyecto te lo dice en el resumen y el estudio queda como borrador.",
    ],
  },
  {
    id: "malla",
    title: "La malla",
    body: [
      "Te sugerimos una malla de conductores y varillas sobre tu plano, con materiales del catálogo.",
      "Puedes cambiarla tú en el editor del plano (mover, agregar o quitar conductores y varillas) o pedir cambios en el chat, por ejemplo «agrega varillas en las esquinas».",
    ],
  },
  {
    id: "seguridad",
    title: "Revisión de seguridad",
    body: [
      "Calculamos las tensiones de toque y de paso y la resistencia de la malla con IEEE 80, y comparamos con los límites de IEEE 80 y RETIE, según la norma que elijas en el proyecto.",
      "Si no cumple, te mostramos en un mapa dónde falla y qué cambiar. El agente puede probar varias versiones de la malla hasta encontrar una que cumpla.",
      "También revisamos que la sección del conductor aguante la corriente de falla sin dañarse.",
    ],
  },
  {
    id: "versiones",
    title: "Versiones",
    body: [
      "Cada cambio, tuyo o del agente, crea una versión nueva del diseño. Nada se borra: puedes ver las anteriores, compararlas y volver a la que prefieras.",
    ],
  },
  {
    id: "estudio",
    title: "Compartir el estudio",
    body: [
      "En «Compartir estudio» armas el informe: eliges qué secciones van, escribes los textos y pones el logo de tu empresa.",
      "Al publicarlo obtienes un enlace. Tú decides quién lo ve: público, solo con el enlace o con contraseña. Desde la página del estudio lo guardas en PDF.",
      "Si quedan datos supuestos sin confirmar, el estudio sale marcado como BORRADOR y dice cuáles son. Si el diseño no cumple, sale marcado como NO CONFORME.",
      "Si después cambias el diseño, publicas una versión nueva; la anterior conserva su enlace.",
    ],
  },
  {
    id: "responsabilidad",
    title: "Quién firma",
    body: [
      "Allectricity te ayuda a diseñar; no reemplaza al ingeniero. Hacemos la parte repetitiva y te mostramos de dónde sale cada número. La revisión final y la firma del estudio son tuyas.",
    ],
  },
];

// Terms and privacy describe what the service really does today (Google sign-in, Mercado Pago, OpenRouter for the
// agent, Resend for email, Railway hosting). They are a plain-language baseline: have a lawyer review them.
const UPDATED = "22 de noviembre de 2026";
const TERMS = [
  {
    id: "servicio",
    title: "El servicio",
    body: [
      "Allectricity es una herramienta en línea para diseñar sistemas de puesta a tierra: lee tus documentos, propone una malla, calcula su seguridad y genera un estudio.",
      "Al crear una cuenta o usar el servicio aceptas estos términos. Si no estás de acuerdo, no lo uses.",
    ],
  },
  {
    id: "responsabilidad-tecnica",
    title: "Tú firmas el diseño",
    body: [
      "Allectricity es una ayuda de ingeniería, no un sustituto del ingeniero. Los resultados pueden contener errores, sobre todo cuando los datos de entrada están incompletos o el agente tuvo que suponer valores.",
      "Antes de construir o certificar un diseño, una persona competente y con la matrícula profesional que exija la ley debe revisarlo y firmarlo. Esa revisión y esa decisión son tuyas.",
      "En la medida que la ley lo permita, no respondemos por daños derivados de usar los resultados sin esa revisión.",
    ],
  },
  {
    id: "cuenta",
    title: "Tu cuenta",
    body: [
      "Eres responsable de lo que se haga con tu cuenta. No compartas tu acceso y avísanos si crees que alguien entró sin permiso.",
      "Podemos suspender cuentas que abusen del servicio, intenten vulnerarlo o lo usen para algo ilegal.",
    ],
  },
  {
    id: "contenido",
    title: "Tus documentos y diseños",
    body: [
      "Lo que subes y lo que diseñas es tuyo. Nos das permiso de guardarlo y procesarlo solo para prestarte el servicio: leerlo, calcular, generar tus estudios y darte soporte.",
      "Solo sube documentos que tengas derecho a usar. Si publicas un estudio con enlace público, cualquiera con el enlace puede verlo.",
    ],
  },
  {
    id: "planes-pagos",
    title: "Planes y pagos",
    body: [
      "Crear la cuenta es gratis. Usar el agente requiere un plan mensual o un código de licencia. Cada plan trae una cantidad de uso del agente (tokens) que se renueva con cada cobro mensual; el uso que no gastes no se acumula.",
      "Los pagos se procesan con Mercado Pago en pesos colombianos; el precio en dólares que mostramos es de referencia. No guardamos los datos de tu tarjeta.",
      "Puedes cancelar cuando quieras; conservas el acceso hasta el final del periodo pagado. Si un cobro falla, te damos unos días para resolverlo antes de suspender el plan.",
      "Si crees que hubo un cobro equivocado, escríbenos y lo revisamos.",
    ],
  },
  {
    id: "disponibilidad",
    title: "Disponibilidad y cambios",
    body: [
      "Hacemos lo posible por que el servicio funcione siempre, pero puede tener interrupciones o fallas. Podemos mejorar, cambiar o retirar funciones.",
      "Si cambiamos estos términos de forma importante, te avisaremos por correo o en la app antes de que apliquen.",
    ],
  },
  {
    id: "ley",
    title: "Ley aplicable",
    body: [
      "Estos términos se rigen por las leyes de la República de Colombia.",
    ],
  },
];
const PRIVACY = [
  {
    id: "datos",
    title: "Qué datos guardamos",
    body: [
      "De tu cuenta: nombre, correo y, si entras con Google, tu identificador y foto de perfil de Google. Si usas correo y contraseña, guardamos la contraseña cifrada, nunca en texto plano.",
      "De tu trabajo: los proyectos, los documentos que subes, los datos que sacamos de ellos, las versiones del diseño, los mensajes del chat y los estudios que publicas.",
      "De uso y seguridad: inicios de sesión, sesiones abiertas y un registro de acciones importantes, para proteger tu cuenta y resolver problemas.",
      "De pagos: tu plan, el estado de los cobros y la referencia de Mercado Pago. Los datos de la tarjeta los recibe Mercado Pago directamente; nosotros no los vemos ni los guardamos.",
    ],
  },
  {
    id: "uso",
    title: "Para qué los usamos",
    body: [
      "Para prestarte el servicio: leer tus documentos, diseñar y calcular, generar tus estudios, cobrar tu plan y enviarte correos necesarios (por ejemplo, para cambiar tu contraseña).",
      "Para mejorar el servicio y dar soporte, revisando cómo responde el agente. No vendemos tus datos ni los usamos para publicidad.",
    ],
  },
  {
    id: "terceros",
    title: "Con quién los compartimos",
    body: [
      "Solo con los proveedores que necesitamos para funcionar: Railway (servidores donde vive el servicio), OpenRouter y los modelos de inteligencia artificial a los que da acceso (procesan el texto de tus documentos y mensajes cuando usas el agente), Google (si entras con Google), Mercado Pago (pagos) y Resend (envío de correos).",
      "Algunos de estos proveedores procesan datos fuera de Colombia. También entregaríamos datos si una autoridad competente lo exige conforme a la ley.",
    ],
  },
  {
    id: "navegador",
    title: "Cookies y almacenamiento",
    body: [
      "No usamos cookies de publicidad ni de seguimiento. La app guarda en tu navegador lo necesario para mantener tu sesión abierta y recordar preferencias de pantalla.",
    ],
  },
  {
    id: "seguridad-datos",
    title: "Cómo los protegemos",
    body: [
      "Las conexiones van cifradas, los archivos subidos pasan por un análisis antivirus y el acceso a cada proyecto se controla por permisos. Ningún sistema es infalible: si detectamos un incidente que te afecte, te avisaremos.",
    ],
  },
  {
    id: "derechos",
    title: "Tus derechos",
    body: [
      "Conforme a la Ley 1581 de 2012 de Colombia puedes conocer, actualizar y corregir tus datos, pedir que los borremos o revocar tu autorización, salvo cuando la ley nos obligue a conservarlos (por ejemplo, registros de pagos).",
      `Para ejercerlos escríbenos a ${CONTACT_EMAIL} desde el correo de tu cuenta. Te respondemos en los plazos que fija la ley. También puedes acudir a la Superintendencia de Industria y Comercio.`,
    ],
  },
  {
    id: "conservacion",
    title: "Cuánto tiempo los guardamos",
    body: [
      "Mientras tengas la cuenta. Si nos pides borrarla, eliminamos tus datos en un plazo razonable, salvo lo que la ley nos obligue a conservar.",
    ],
  },
];

const PAGES = {
  ayuda: {
    eyebrow: "Documentación",
    title: "Cómo usar Allectricity",
    lede: "Nos das tus documentos, los entendemos, te sugerimos una malla, revisamos que sea segura y te entregamos el estudio. Esta guía explica cada paso.",
    sections: GUIDE,
    nav: "Docs",
  },
  terminos: {
    eyebrow: "Términos",
    title: "Términos y condiciones",
    lede: `Las reglas para usar Allectricity, dichas en simple. Última actualización: ${UPDATED}.`,
    sections: TERMS,
  },
  privacidad: {
    eyebrow: "Privacidad",
    title: "Política de privacidad",
    lede: `Qué datos tuyos guardamos, para qué y qué puedes hacer con ellos. Última actualización: ${UPDATED}.`,
    sections: PRIVACY,
  },
};

export function pageFromPath(pathname) {
  const key = pathname.replace(/^\/+|\/+$/g, "");
  return PAGES[key] ? key : "ayuda";
}

export function DocsPage({ page = "ayuda" }) {
  const { eyebrow, title, lede, sections } = PAGES[page] || PAGES.ayuda;
  const [active, setActive] = useState(sections[0].id);
  const origin = appOrigin();
  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => { if (entry.isIntersecting) setActive(entry.target.id); });
    }, { rootMargin: "-20% 0px -70% 0px" });
    document.querySelectorAll(".docs-section").forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [page]);
  const home = origin ? "/" : "https://allectricity.com/";
  return (
    <div className="landing docs-page">
      <header className="landing-nav is-scrolled">
        <a className="landing-brand" href={home} aria-label="Allectricity, inicio">
          <BrandMark size={32} tone="dark" className="landing-brand-mark" />
          Allectricity
        </a>
        <nav aria-label="Secciones">
          <a href={`${home}#como-funciona`}>Cómo funciona</a>
          <a href={`${home}#precios`}>Precios</a>
          <a href="/ayuda" aria-current={page === "ayuda" ? "page" : undefined}>Docs</a>
          <a href={`${home}#contacto`}>Contacto</a>
        </nav>
        <div className="landing-nav-actions">
          <a className="landing-button ghost small" href={`${origin}/login`}>Iniciar sesión</a>
          <a className="landing-button primary small" href={`${origin}/login?crear`}>Crear cuenta</a>
        </div>
      </header>

      <main className="docs-layout">
        <aside className="docs-toc" aria-label="Contenido">
          <a className="docs-back" href={home}><ArrowLeft size={14} />Volver al inicio</a>
          <ol>
            {sections.map((section) => (
              <li key={section.id}><a href={`#${section.id}`} className={active === section.id ? "is-active" : ""}>{section.title}</a></li>
            ))}
          </ol>
        </aside>
        <article className="docs-content">
          <p className="landing-eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p className="docs-lede">{lede}</p>
          {sections.map((section) => (
            <section key={section.id} id={section.id} className="docs-section">
              <h2>{section.title}</h2>
              {section.body.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
            </section>
          ))}
          <section id="ayuda" className="docs-section docs-help">
            <h2>¿Necesitas ayuda?</h2>
            <p>Escríbenos a <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. Si es sobre un proyecto, dinos su nombre.</p>
          </section>
        </article>
      </main>

      <footer className="landing-footer">
        <span>© {new Date().getFullYear()} Allectricity</span>
        <LegalLinks />
      </footer>
    </div>
  );
}
