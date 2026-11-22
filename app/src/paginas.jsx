// Entry of the public text pages (paginas.html): /ayuda, /terminos and /privacidad, on the landing and app hosts.
import React from "react";
import { createRoot } from "react-dom/client";
import { DocsPage, pageFromPath } from "./components/DocsPage.jsx";

const page = pageFromPath(window.location.pathname);
const titles = { ayuda: "Documentación", terminos: "Términos y condiciones", privacidad: "Política de privacidad" };
document.title = `${titles[page]} — Allectricity`;
createRoot(document.getElementById("root")).render(<DocsPage page={page} />);
