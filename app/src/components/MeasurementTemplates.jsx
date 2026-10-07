import React, { useEffect, useState } from "react";
import { ArrowDownToLine, FileSpreadsheet } from "lucide-react";

// Field templates live in the MinIO templates bucket; the API lists its catalog and signs downloads.
function MeasurementTemplates({ token, method }) {
  const [templates, setTemplates] = useState(null);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState("");
  const auth = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    let live = true;
    fetch("/api/v1/plantillas-medicion", { headers: auth })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "No se pudieron cargar las plantillas.");
        if (live) setTemplates(data.items);
      })
      .catch((e) => { if (live) { setTemplates([]); setError(e.message); } });
    return () => { live = false; };
  }, [token]);

  async function download(template, format) {
    const key = `${template.id}/${format}`;
    setDownloading(key);
    setError("");
    try {
      const response = await fetch(`/api/v1/plantillas-medicion/${encodeURIComponent(template.id)}/${format}`, { headers: auth });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "No se pudo descargar la plantilla.");
      const link = document.createElement("a");
      link.href = data.url;
      link.download = data.filename;
      link.click();
    } catch (e) {
      setError(e.message);
    } finally {
      setDownloading("");
    }
  }

  const ordered = [...(templates || [])].sort((a, b) => (b.method === method) - (a.method === method));
  return <section className="panel calc-panel measurement-templates" aria-label="Plantillas de medición">
    <div className="panel-heading"><div><ArrowDownToLine size={17}/><h2>Plantillas de campo</h2></div>{templates && <span className="count">{templates.length}</span>}</div>
    <p className="calc-help">Descarga la plantilla del método, diligénciala en campo y cárgala en <strong>Archivos del proyecto</strong> para que el agente extraiga las lecturas.</p>
    {error && <p className="calc-help upload-error-text" role="alert">{error}</p>}
    {templates === null ? <p className="calc-help">Cargando plantillas…</p> : <ul className="template-list">{ordered.map((template) => <li key={template.id} className={template.method === method ? "current" : ""}>
      <span className="asset-icon document"><FileSpreadsheet size={17}/></span>
      <span className="template-info"><strong>{template.title}{template.method === method && <em>Método seleccionado</em>}</strong><small>{template.description}</small><code>{template.formula}</code></span>
      <span className="template-actions">{template.files.map((file) => <button key={file.format} className="button" disabled={downloading === `${template.id}/${file.format}`} onClick={() => download(template, file.format)} aria-label={`Descargar ${template.title} en ${file.format.toUpperCase()}`}><ArrowDownToLine size={13}/>{file.format.toUpperCase()}</button>)}</span>
    </li>)}</ul>}
  </section>;
}

export { MeasurementTemplates };
