import React from "react";

export const mimeByExtension = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  csv: "text/csv",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  dxf: "application/dxf",
};
export const uploadableMimeTypes = new Set(Object.values(mimeByExtension));
export const uploadStatusLabels = {
  uploading: "Cargando a cuarentena…",
  pending: "En cola para procesar",
  scanning: "Analizando y extrayendo…",
  available: "Procesado y listo",
  rejected: "Rechazado · el archivo no pasó la validación",
  failed: "Falló el procesamiento",
  expired: "Carga incompleta · vuelve a subir el archivo",
};
export const defaults = {
  length: 40,
  width: 30,
  spacing: 5,
  rods: 12,
  depth: 0.6,
  resistivity: 120,
  soilDepth: 2.5,
  current: 12500,
  time: 0.5,
  copperPrice: 12.8,
};
export const initialMessages = [
  {
    role: "user",
    text: "Create a grounding mesh for the north substation using the site layout and soil measurements.",
  },
  {
    role: "assistant",
    text: "Here is a starting point for your grounding design. The reference layout combines a rectangular copper mesh with perimeter ground rods.",
    card: true,
  },
];
export const IconButton = ({ title, children, ...props }) => (
  <button className="icon-button" title={title} aria-label={title} {...props}>
    {children}
  </button>
);
export function download(name, text, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function recordFeatureUse(userId, feature, projectName) {
  if (!userId) return;
  const key = `terra_recent_features:${userId}`;
  try {
    const existing = JSON.parse(localStorage.getItem(key) || "[]");
    const next = [{ feature, projectName, usedAt: Date.now() }, ...existing].slice(0, 20);
    localStorage.setItem(key, JSON.stringify(next));
  } catch { /* Keep feature navigation available if local storage is unavailable. */ }
}
