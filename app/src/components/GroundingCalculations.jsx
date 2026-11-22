import React, { useEffect, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  File,
  FileImage,
  FileSpreadsheet,
  FolderOpen,
  GitBranch,
  History,
  Layers,
  LayoutGrid,
  MapPin,
  MessageCircle,
  Minus,
  Maximize2,
  Mic,
  Network,
  Paperclip,
  Plus,
  Pencil,
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  X,
  Trash2,
  Zap,
} from "lucide-react";
import { MeasurementTemplates } from "./MeasurementTemplates.jsx";
import { VerdictCallout } from "./ResultBlocks.jsx";
import { HelpLabel } from "./HelpTip.jsx";

const FIELD_HELP = { current_a: "fault_current", clearing_time_s: "clearing_time", surface_resistivity_ohm_m: "surface_resistivity", surface_thickness_m: "surface_thickness", body_weight_kg: "body_weight" };
import { IconMeasurements, IconParameters, IconResult, IconSoil } from "../icons.jsx";
import { awaitJob } from "../asyncJobs.js";


// Fallback until the backend catalog (/api/v1/perfiles-termicos) loads: the original IEEE 80-2013 choices.
const FALLBACK_THERMAL_PROFILES = [
  {
    profile: "IEEE 80-2013",
    label: "IEEE 80-2013",
    modes: [
      {
        voltage_level: null,
        temperature_inputs: "ambient_and_maximum",
        max_duration_s: null,
        note: "",
        materials: [
          { id: "copper_hard_drawn", name: "Cobre comercial duro" },
          { id: "copper_annealed", name: "Cobre recocido" },
          { id: "copper_clad_40", name: "Acero recubierto de cobre 40 %" },
          { id: "copper_clad_30", name: "Acero recubierto de cobre 30 %" },
          { id: "copper_clad_rod_17", name: "Varilla de acero recubierta de cobre 17 %" },
          { id: "aluminum_clad_steel", name: "Acero recubierto de aluminio" },
          { id: "steel_1020", name: "Acero 1020" },
          { id: "stainless_clad_rod", name: "Varilla de acero inoxidable revestida" },
          { id: "zinc_coated_steel_rod", name: "Varilla de acero galvanizada" },
          { id: "stainless_304", name: "Acero inoxidable 304" },
        ],
      },
    ],
  },
];
const VOLTAGE_LEVEL_LABELS = {
  medium_high_extra_high: "Media, alta y extra alta tensión",
  low: "Baja tensión",
};

// El motor entrega las tensiones máximas como {value, x_m, y_m}; datos antiguos pueden traer el número plano.
const quantityValue = (quantity) =>
  quantity !== null && typeof quantity === "object" ? quantity.value : quantity;

// Fields the safety form needs, said in engineering words and with where they are filled in.
const DESIGN_FIELD_LABELS = {
  length_m: ["Largo de la malla", "plano"], width_m: ["Ancho de la malla", "plano"], burial_depth_m: ["Profundidad de la malla", "plano"],
  conductor_spacing_m: ["Retícula de la malla", "plano"], rod_length_m: ["Longitud de las varillas", "plano"],
  current_a: ["Corriente de falla", "falla"], clearing_time_s: ["Tiempo de despeje", "falla"],
  surface_resistivity_ohm_m: ["Resistividad superficial", "falla"], surface_thickness_m: ["Espesor superficial", "falla"],
  body_weight_kg: ["Peso corporal", "falla"], conductor_section_mm2: ["Sección del conductor", "conductor"],
  conductor_maximum_temperature_c: ["Temperatura máxima", "conductor"], thermal_duration_s: ["Duración térmica", "conductor"],
  ambient_temperature_c: ["Temperatura ambiente", "conductor"],
};
const positive = (value) => value !== "" && value != null && Number.isFinite(Number(value)) && Number(value) > 0;

// Everything that keeps «Calcular» disabled, so the form can say it instead of graying the button out.
function designGaps(design, { drawnConductors = false } = {}) {
  const gaps = [];
  for (const [key, [label, where]] of Object.entries(DESIGN_FIELD_LABELS)) {
    if (key === "conductor_spacing_m" && drawnConductors) continue;          // a drawn grid has no single spacing
    if (key === "rod_length_m" && !(Number(design.rods_count) > 0)) continue; // no rods, no rod length
    if (!positive(design[key])) gaps.push({ key, text: `${label}: falta`, where });
  }
  if (design.rods_count === "" || design.rods_count == null || !(Number(design.rods_count) >= 0)) gaps.push({ key: "rods_count", text: "Número de varillas: falta (puede ser 0)", where: "plano" });
  if (!design.conductor_material_id) gaps.push({ key: "conductor_material_id", text: "Material del conductor: elige uno", where: "conductor" });
  if (!design.conductor_joint_type) gaps.push({ key: "conductor_joint_type", text: "Tipo de unión: elige uno", where: "conductor" });
  if (positive(design.body_weight_kg) && (Number(design.body_weight_kg) < 50 || Number(design.body_weight_kg) > 70))
    gaps.push({ key: "body_weight_kg", text: "Peso corporal: IEEE 80 solo admite valores entre 50 y 70 kg", where: "falla" });
  if (design.split_factor !== "" && design.split_factor != null && !(Number(design.split_factor) > 0 && Number(design.split_factor) <= 1))
    gaps.push({ key: "split_factor", text: "Factor de reparto S_f: debe estar entre 0 y 1 (o déjalo vacío)", where: "avanzados" });
  return gaps;
}

function SoilFitChart({ readings, fit }) {
  const points = readings
    .map((reading, index) => ({
      x: Number(reading.spacing_m),
      observed: Number(reading.apparent_resistivity_ohm_m),
      fitted:
        Number(reading.apparent_resistivity_ohm_m) *
        (1 + Number(fit.residuals_percent?.[index] || 0) / 100),
    }))
    .filter((point) => point.x > 0 && point.observed > 0 && point.fitted > 0)
    .sort((a, b) => a.x - b.x);
  if (!points.length) return null;
  const minX = Math.log10(Math.min(...points.map((p) => p.x)));
  const maxX = Math.log10(Math.max(...points.map((p) => p.x)));
  const values = points.flatMap((p) => [p.observed, p.fitted]);
  const minY = Math.min(...values),
    maxY = Math.max(...values);
  const x = (value) =>
    42 + ((Math.log10(value) - minX) / (maxX - minX || 1)) * 430;
  const y = (value) => 168 - ((value - minY) / (maxY - minY || 1)) * 132;
  return (
    <div className="soil-fit-chart">
      <svg
        viewBox="0 0 490 210"
        role="img"
        aria-label="Gráfica de resistividad aparente medida y curva del modelo ajustado"
      >
        <text x="245" y="13" textAnchor="middle">
          Resistividad aparente (Ω·m)
        </text>
        <path d="M42 20V168H474" fill="none" stroke="#9aaca5" />
        <polyline
          points={points.map((p) => `${x(p.x)},${y(p.fitted)}`).join(" ")}
          fill="none"
          stroke="#328a7c"
          strokeWidth="3"
        />
        {points.map((p, i) => (
          <g key={`${p.x}-${i}`}>
            <circle cx={x(p.x)} cy={y(p.observed)} r="4.5" fill="#d28d43" />
            <circle cx={x(p.x)} cy={y(p.fitted)} r="2.5" fill="#328a7c" />
          </g>
        ))}
        <text x="258" y="198" textAnchor="middle">
          Espaciamiento (m, escala logarítmica)
        </text>
        <g fontSize="10" fill="#61766e">
          <text x="44" y="184">
            {points[0].x}
          </text>
          <text x="470" y="184" textAnchor="end">
            {points.at(-1).x}
          </text>
          <text x="38" y="30" textAnchor="end">
            {maxY.toPrecision(3)}
          </text>
          <text x="38" y="166" textAnchor="end">
            {minY.toPrecision(3)}
          </text>
        </g>
      </svg>
      <div className="soil-chart-legend">
        <span>
          <i className="measured" /> Mediciones
        </span>
        <span>
          <i className="fitted" /> Modelo ajustado
        </span>
      </div>
    </div>
  );
}

// Index window of the raster: the whole terrain, or the grid outline with a margin ("detail").
function potentialWindow(field, view) {
  const all = { i0: 0, i1: field.nx - 1, j0: 0, j1: field.ny - 1 };
  if (view !== "detail" || !field.grid_width_m) return all;
  const dx = field.spacing_m;
  const pad = Math.max(1, 0.25 * Math.max(field.grid_width_m, field.grid_height_m));
  const clamp = (value, top) => Math.max(0, Math.min(top, value));
  return {
    i0: clamp(Math.floor(((field.grid_x_m || 0) - pad) / dx), field.nx - 1),
    i1: clamp(Math.ceil(((field.grid_x_m || 0) + field.grid_width_m + pad) / dx), field.nx - 1),
    j0: clamp(Math.floor(((field.grid_y_m || 0) - pad) / dx), field.ny - 1),
    j1: clamp(Math.ceil(((field.grid_y_m || 0) + field.grid_height_m + pad) / dx), field.ny - 1),
  };
}

// Surface potential heat map. A terrain taller than wide is turned 90° to read in landscape; «Zona de la malla»
// crops to the grid and rescales the colours to that area, where the contact voltage is evaluated.
function SurfacePotentialMap({ field, action = null, note = null, view: fixedView = null }) {
  const [chosen, setChosen] = useState("general");
  if (!field?.values_v?.length || !field.nx || !field.ny) return null;
  const general = potentialWindow(field, "general"), detail = potentialWindow(field, "detail");
  const worthDetail = (detail.i1 - detail.i0 + 1) * (detail.j1 - detail.j0 + 1) < 0.6 * field.nx * field.ny;
  const view = fixedView || (worthDetail ? chosen : "general");
  const win = view === "detail" ? detail : general;
  const dx = field.spacing_m;
  const cols = win.i1 - win.i0 + 1, rows = win.j1 - win.j0 + 1;
  const rotated = rows > cols * 1.1;
  let min = Infinity, max = -Infinity;
  for (let j = win.j0; j <= win.j1; j += 1) for (let i = win.i0; i <= win.i1; i += 1) { const v = field.values_v[j * field.nx + i]; if (v < min) min = v; if (v > max) max = v; }
  const color = (value) => `hsl(${220 - 220 * ((value - min) / (max - min || 1))} 78% 52%)`;
  const width = (rotated ? rows : cols) * dx, height = (rotated ? cols : rows) * dx;
  // Cell (i, j) → top-left corner on screen; plan y grows upward.
  const cell = (i, j) => rotated ? [(j - win.j0) * dx, (i - win.i0) * dx] : [(i - win.i0) * dx, (win.j1 - j) * dx];
  const cells = [];
  for (let j = win.j0; j <= win.j1; j += 1) for (let i = win.i0; i <= win.i1; i += 1) { const [x, y] = cell(i, j); cells.push(<rect key={`${i}-${j}`} x={x} y={y} width={dx + 0.01} height={dx + 0.01} fill={color(field.values_v[j * field.nx + i])}/>); }
  // Grid outline in raster coordinates (metres from the raster origin).
  const gx0 = field.grid_x_m || 0, gy0 = field.grid_y_m || 0, gx1 = gx0 + (field.grid_width_m || cols * dx), gy1 = gy0 + (field.grid_height_m || rows * dx);
  const outline = rotated
    ? { x: gy0 - win.j0 * dx, y: gx0 - win.i0 * dx, w: gy1 - gy0, h: gx1 - gx0 }
    : { x: gx0 - win.i0 * dx, y: (win.j1 + 1) * dx - gy1, w: gx1 - gx0, h: gy1 - gy0 };
  const volts = (value) => value.toLocaleString("es-CO", { maximumFractionDigits: 1 });
  return (
    <section className="surface-map-panel" aria-label="Mapa de potencial superficial">
      <div className="surface-map-heading">
        <div>
          <strong>Potencial en la superficie{view === "detail" ? " · zona de la malla" : ""}</strong>
          <span>Tensión del suelo respecto a tierra remota durante la falla · {cols} × {rows} puntos{rotated ? " · girado 90°" : ""}</span>
        </div>
        <div className="surface-map-tools">
          {worthDetail && !fixedView && <div className="app-segmented" role="group" aria-label="Zona del mapa">
            <button type="button" className={view === "general" ? "active" : ""} aria-pressed={view === "general"} onClick={() => setChosen("general")}>Terreno completo</button>
            <button type="button" className={view === "detail" ? "active" : ""} aria-pressed={view === "detail"} onClick={() => setChosen("detail")}>Zona de la malla</button>
          </div>}
          {action}
        </div>
      </div>
      <svg className="surface-map" viewBox={`0 0 ${width} ${height}`} role="img" style={{ aspectRatio: `${width} / ${height}` }}
        aria-label={`Mapa de potencial superficial${view === "detail" ? " en la zona de la malla" : ""}, de ${min.toFixed(1)} a ${max.toFixed(1)} voltios${rotated ? ", girado 90°" : ""}`}>
        {cells}
        <rect x={outline.x} y={outline.y} width={outline.w} height={outline.h} fill="none" stroke="#172a25" strokeWidth={Math.max(0.12, dx * 0.035)} strokeDasharray={`${dx * 0.25} ${dx * 0.16}`}/>
      </svg>
      <div className="surface-map-scale">
        <span>{volts(min)} V</span>
        <i />
        <span>{volts(max)} V</span>
      </div>
      <ul className="surface-map-notes">
        <li><i className="dashed" />El contorno punteado es el perímetro de la malla.</li>
        <li><i className="gradient" />Del azul (menor tensión) al rojo (mayor tensión){view === "detail" ? "; la escala se ajusta a esta zona" : ""}.</li>
        {rotated && <li><i className="dot" />El terreno es más largo que ancho: se muestra girado 90° (el eje Y queda horizontal).</li>}
        {note && <li><i className="dot" />{note}</li>}
      </ul>
    </section>
  );
}

function ArtifactPanel({ fit = null, calculation = null, design = null }) {
  const result = calculation?.result;
  return (
    <aside className="panel artifact-side-panel">
      <div className="panel-heading">
        <div>
          <Box size={17} />
          <h2>Diseño de puesta a tierra</h2>
        </div>
        <span className="muted-label">{result ? "Calculado" : "Borrador"}</span>
      </div>
      <div className="artifact-preview-empty">
        <Box size={25} />
        <strong>
          {design ? "Geometría del diseño" : "Aún no hay un diseño de malla"}
        </strong>
        <span>
          {design
            ? `${design.length_m} × ${design.width_m} m`
            : "Dibuja el plano desde la pestaña Plano del proyecto."}
        </span>
      </div>
      <div className="artifact-status">
        <strong>Modelo de suelo</strong>
        {fit ? (
          <span>
            {fit.soil_layers
              ?.map(
                (layer, index) =>
                  `C${index + 1}: ${Number(layer.resistivity_ohm_m).toFixed(1)} Ω·m${layer.depth_m == null ? " (semiespacio)" : ` · ${Number(layer.depth_m).toFixed(2)} m`}`,
              )
              .join(" · ") ||
              `${Number(fit.model.upper_resistivity_ohm_m).toFixed(1)} / ${Number(fit.model.lower_resistivity_ohm_m).toFixed(1)} Ω·m · capa superior ${Number(fit.model.upper_thickness_m).toFixed(2)} m`}
          </span>
        ) : (
          <span className="no-information">
            Sin información: ajusta las mediciones para obtener las capas del
            suelo.
          </span>
        )}
      </div>
      <div className="artifact-status">
        <strong>Verificación</strong>
        {result ? (
          <span>
            {result.safety?.[0]?.status || "Resultado disponible"} ·{" "}
            {Number(quantityValue(result.max_touch_v)).toFixed(1)} V contacto ·{" "}
            {Number(quantityValue(result.max_step_v)).toFixed(1)} V paso
          </span>
        ) : (
          <span className="no-information">
            Sin información: ejecuta el cálculo de seguridad para ver
            resultados.
          </span>
        )}
      </div>
    </aside>
  );
}

function GroundingCalculations({
  project,
  token,
  section,
  files = [],
  onArtifactSaved,
}) {
  const [measurementMethod, setMeasurementMethod] = useState("wenner");
  const [soilSource, setSoilSource] = useState("measurements");
  const [manualLayers, setManualLayers] = useState([
    { material: "", resistivity_ohm_m: "", depth_m: "" },
    { material: "", resistivity_ohm_m: "", depth_m: null },
  ]);
  const [standard, setStandard] = useState("IEEE 80-2013");
  const [readings, setReadings] = useState(
    Array.from({ length: 4 }, () => ({
      spacing_m: "",
      apparent_resistivity_ohm_m: "",
    })),
  );
  const [fit, setFit] = useState(null);
  const [layerCount, setLayerCount] = useState(2);
  const [calculation, setCalculation] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [importConfig, setImportConfig] = useState({
    upload_id: "",
    sheet: "",
    spacing_column: "A",
    value_column: "B",
    potential_column: "",
    first_row: 2,
    last_row: 13,
    decimal: "auto",
    spacing_unit: "m",
    potential_spacing_unit: "m",
    value_unit: "ohm_m",
    value_kind: "apparent_resistivity",
  });
  const [soilFileSource, setSoilFileSource] = useState(null);
  const [thermalProfiles, setThermalProfiles] = useState(FALLBACK_THERMAL_PROFILES);
  // Fallback until the backend table (/api/v1/materiales-suelo) loads.
  const [soilMaterials, setSoilMaterials] = useState([
    { name: "Grava", rho: 3000, range: "1.000–10.000" },
    { name: "Arena", rho: 500, range: "100–2.500" },
    { name: "Arcilla", rho: 50, range: "1–100" },
    { name: "Limo", rho: 150, range: "20–500" },
    { name: "Tierra vegetal", rho: 100, range: "10–1.000" },
    { name: "Roca", rho: 5000, range: "1.000–100.000" },
    { name: "Personalizado", rho: null, range: "definido por el usuario" },
  ]);
  function updateSoilLayer(index, key, value) {
    setFit((current) => {
      if (!current) return current;
      const soil_layers = current.soil_layers.map((layer, i) =>
        i === index
          ? {
              ...layer,
              [key]: key === "resistivity_ohm_m" ? Number(value) : value,
            }
          : layer,
      );
      const model =
        current.layer_count === 2
          ? {
              ...current.model,
              ...(index === 0
                ? {
                    upper_resistivity_ohm_m: soil_layers[0].resistivity_ohm_m,
                    upper_thickness_m: soil_layers[0].depth_m,
                  }
                : {
                    lower_resistivity_ohm_m: soil_layers[1].resistivity_ohm_m,
                  }),
            }
          : { ...current.model, layers: soil_layers };
      return { ...current, soil_layers, model };
    });
  }
  const [design, setDesign] = useState({
    name: `Diseño de tierras · ${project.name}`,
    length_m: "",
    width_m: "",
    burial_depth_m: "",
    conductor_spacing_m: "",
    rods_count: "",
    rod_length_m: "",
    current_a: "",
    clearing_time_s: "",
    surface_resistivity_ohm_m: "",
    surface_thickness_m: "",
    body_weight_kg: "",
    split_factor: "",
    x_over_r: "",
    conductor_material_id: "",
    conductor_section_mm2: "",
    conductor_joint_type: "",
    conductor_thermal_profile: "IEEE 80-2013",
    conductor_voltage_level: "medium_high_extra_high",
    conductor_maximum_temperature_c: "",
    thermal_duration_s: "",
    ambient_temperature_c: "",
  });
  // One source of truth: the form starts from the newest saved version of the project's design (the one the
  // agent edits) and saves new versions of that same design instead of a parallel one.
  const [baseArtifact, setBaseArtifact] = useState(null);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    let live = true;
    fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => {
        const row = rows[0];
        if (!live || !row) return;
        const snap = row.snapshot || {};
        const g = snap.geometry || {}; const f = snap.fault || {}; const c = snap.conductor || {};
        const text = (v) => (v === null || v === undefined ? "" : String(v));
        setBaseArtifact(row);
        setDesign((current) => ({
          ...current,
          name: row.name || current.name,
          length_m: text(g.length_m), width_m: text(g.width_m), burial_depth_m: text(g.burial_depth_m),
          conductor_spacing_m: text(g.conductor_spacing_m ?? g.conductor_spacing_x_m),
          rods_count: text(g.rods_count), rod_length_m: text(g.rod_length_m),
          current_a: text(f.current_a), clearing_time_s: text(f.clearing_time_s),
          surface_resistivity_ohm_m: text(f.surface_resistivity_ohm_m), surface_thickness_m: text(f.surface_thickness_m),
          body_weight_kg: text(f.body_weight_kg),
          conductor_material_id: text(c.material_id) || current.conductor_material_id,
          conductor_section_mm2: text(c.cross_section_mm2), conductor_joint_type: text(c.joint_type),
          conductor_thermal_profile: c.thermal_profile || current.conductor_thermal_profile,
          conductor_voltage_level: c.voltage_level || current.conductor_voltage_level,
          conductor_maximum_temperature_c: text(c.maximum_temperature_c),
          thermal_duration_s: text(c.thermal_duration_s), ambient_temperature_c: text(c.ambient_temperature_c),
        }));
        if (snap.soil_measurements?.measurements?.length) {
          setMeasurementMethod(snap.soil_measurements.array || "wenner");
          setReadings(snap.soil_measurements.measurements.map((m) => ({ ...m, spacing_m: text(m.spacing_m), apparent_resistivity_ohm_m: text(m.apparent_resistivity_ohm_m) })));
        }
        if (snap.soil_layers?.length && snap.soil_measurements?.measurements?.length) {
          setSoilSource("measurements");
          setLayerCount(snap.soil_layers.length);
          setFit({ soil_layers: snap.soil_layers, layer_count: snap.soil_layers.length, ...(snap.soil_model?.fit || {}) });
        } else if (snap.soil_layers?.length) {
          setSoilSource("manual");
          setLayerCount(snap.soil_layers.length);
          setManualLayers(snap.soil_layers.map((l) => ({ material: l.material || "", resistivity_ohm_m: text(l.resistivity_ohm_m), depth_m: l.depth_m ?? null })));
        }
        setHydrated(true);
      }).catch(() => {});
    return () => { live = false; };
  }, [project.id, token]);
  const soilLayers = soilSource === "manual" ? manualLayers : fit?.soil_layers;
  const soilReady = Boolean(
    soilLayers?.length &&
    soilLayers.every(
      (layer, index) =>
        Number(layer.resistivity_ohm_m) > 0 &&
        (index === soilLayers.length - 1 || Number(layer.depth_m) > 0),
    ),
  );
  const drawnConductors = Boolean(baseArtifact?.snapshot?.geometry?.conductors?.length);
  const gaps = designGaps(design, { drawnConductors });
  const designReady = gaps.length === 0;
  const validMeasurementCount = readings.filter(
    (reading) =>
      Number(reading.spacing_m) > 0 &&
      Number.isFinite(Number(reading.spacing_m)) &&
      Number(reading.apparent_resistivity_ohm_m) > 0 &&
      Number.isFinite(Number(reading.apparent_resistivity_ohm_m)),
  ).length;
  // The fit admits 2–8 layers: a homogeneous plan (1 layer) would otherwise ask for an impossible fit.
  const selectedLayerCount = Math.min(8, Math.max(2, Number(layerCount) || 2));
  const canFitMeasurements =
    validMeasurementCount >= Math.max(4, selectedLayerCount * 2) &&
    ["wenner", "schlumberger"].includes(measurementMethod);
  const auth = { Authorization: `Bearer ${token}` };
  const request = async (url, options = {}) => {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...auth,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
    });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok)
      throw new Error(
        typeof data?.detail === "string" ? data.detail
          : Array.isArray(data?.detail) ? data.detail.map((item) => item?.msg).filter(Boolean).join(" · ") || "Los datos enviados no son válidos."
          : data?.detail?.message || "No se pudo completar la operación.",
      );
    return data;
  };
  const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras`;
  const thermalProfile =
    thermalProfiles.find((p) => p.profile === design.conductor_thermal_profile) ||
    thermalProfiles[0];
  const thermalMode =
    thermalProfile.modes.find(
      (m) => m.voltage_level === design.conductor_voltage_level,
    ) || thermalProfile.modes[0];
  const thermalFromTable = thermalMode.temperature_inputs === "table";
  const durationExceeded = Boolean(
    thermalMode.max_duration_s &&
      Number(design.thermal_duration_s) > thermalMode.max_duration_s,
  );
  const thermalInitialFinal = thermalMode.temperature_inputs === "initial_and_final";
  // A standard fixes which materials exist and how the two temperatures are used, so a change of standard,
  // level or material re-aligns the dependent fields.
  function updateThermal(patch) {
    const next = { ...design, ...patch };
    const profile =
      thermalProfiles.find((p) => p.profile === next.conductor_thermal_profile) ||
      thermalProfiles[0];
    const mode =
      profile.modes.find((m) => m.voltage_level === next.conductor_voltage_level) ||
      profile.modes[0];
    if (!mode.materials.some((m) => m.id === next.conductor_material_id))
      next.conductor_material_id = mode.materials[0].id;
    if (mode.temperature_inputs === "table") {
      const row = mode.materials.find((m) => m.id === next.conductor_material_id);
      next.ambient_temperature_c = "40";
      next.conductor_maximum_temperature_c = String(row?.tm_c ?? "");
    }
    if (mode.max_duration_s && Number(next.thermal_duration_s) > mode.max_duration_s)
      next.thermal_duration_s = String(mode.max_duration_s);
    setDesign(next);
  }
  const tableFiles = files.filter(
    (file) =>
      file.status === "available" &&
      [
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ].includes(file.mime_type),
  );
  async function importSoilFile() {
    setBusy(true);
    setError("");
    try {
      const imported = await awaitJob(token, await request(
        `${root}/mediciones-suelo/archivo/ajustar`,
        {
          method: "POST",
          body: JSON.stringify({
            ...importConfig,
            sheet: importConfig.sheet || null,
            potential_column: importConfig.potential_column || null,
            array: measurementMethod,
            layer_count: Number(selectedLayerCount),
          }),
        },
      ));
      setReadings(imported.measurements);
      setFit(imported);
      setSoilFileSource(imported.source);
      setSoilSource("measurements");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function setReading(i, key, value) {
    setFit(null);
    setSoilFileSource(null);
    setReadings((rows) =>
      rows.map((row, index) =>
        index === i ? { ...row, [key]: value, locator: undefined } : row,
      ),
    );
  }
  useEffect(() => {
    let live = true;
    const range = (m) =>
      m.min_ohm_m === m.max_ohm_m
        ? m.min_ohm_m.toLocaleString("es-CO")
        : `${m.min_ohm_m.toLocaleString("es-CO")}–${m.max_ohm_m.toLocaleString("es-CO")}`;
    request("/api/v1/perfiles-termicos")
      .then((catalog) => {
        if (live && catalog.length) setThermalProfiles(catalog);
      })
      .catch(() => {});
    request("/api/v1/materiales-suelo")
      .then((table) => {
        if (live && table.length)
          setSoilMaterials([
            ...table.map((m) => ({
              name: m.name,
              rho: m.typical_ohm_m,
              range: range(m),
              source: m.source,
            })),
            {
              name: "Personalizado",
              rho: null,
              range: "definido por el usuario",
            },
          ]);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [token]);
  async function fitSoil() {
    setBusy(true);
    setError("");
    try {
      setSoilFileSource(null);
      setFit(
        await awaitJob(token, await request(`${root}/mediciones-suelo/ajustar`, {
          method: "POST",
          body: JSON.stringify({
            array: measurementMethod,
            layer_count: Number(selectedLayerCount),
            measurements: readings.map((r) => ({
              spacing_m: Number(r.spacing_m),
              apparent_resistivity_ohm_m: Number(r.apparent_resistivity_ohm_m),
            })),
          }),
        })),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function calculate() {
    setBusy(true);
    setError("");
    setCalculation(null);
    try {
      const base = baseArtifact?.snapshot || {};
      const artifact = await request(baseArtifact ? `${root}/${baseArtifact.artifact_id}/versions` : root, {
        method: "POST",
        body: JSON.stringify({
          name: design.name,
          geometry: {
            ...(base.geometry || {}),
            length_m: Number(design.length_m),
            width_m: Number(design.width_m),
            burial_depth_m: Number(design.burial_depth_m),
            ...(design.conductor_spacing_m !== "" ? { conductor_spacing_m: Number(design.conductor_spacing_m) } : {}),
            rods_count: Number(design.rods_count),
            ...(design.rod_length_m !== "" ? { rod_length_m: Number(design.rod_length_m) } : {}),
          },
          soil_layers: soilLayers.map((layer) => ({
            ...layer,
            resistivity_ohm_m: Number(layer.resistivity_ohm_m),
            depth_m:
              layer.depth_m == null || layer.depth_m === ""
                ? null
                : Number(layer.depth_m),
          })),
          soil_measurements:
            soilSource === "measurements"
              ? {
                  array: measurementMethod,
                  layer_count: Number(selectedLayerCount),
                  measurements: readings.map((r) => ({
                    spacing_m: Number(r.spacing_m),
                    apparent_resistivity_ohm_m: Number(
                      r.apparent_resistivity_ohm_m,
                    ),
                    ...(r.locator ? { locator: r.locator } : {}),
                  })),
                  ...(soilFileSource ? { source: soilFileSource } : {}),
                }
              : null,
          soil_model:
            soilSource === "measurements"
              ? {
                  source: soilFileSource ? "file" : "measurements",
                  layer_count: Number(selectedLayerCount),
                  fit: fit
                    ? {
                        rms_error_percent: fit.rms_error_percent,
                        uniform_rms_error_percent:
                          fit.uniform_rms_error_percent,
                        warnings: fit.warnings,
                        forward_model: fit.forward_model,
                        relative_uncertainty_percent:
                          fit.relative_uncertainty_percent,
                        excluded: fit.excluded,
                      }
                    : null,
                }
              : { source: "materials" },
          fault: {
            ...(base.fault || {}),
            current_a: Number(design.current_a),
            clearing_time_s: Number(design.clearing_time_s),
            surface_resistivity_ohm_m: Number(design.surface_resistivity_ohm_m),
            surface_thickness_m: Number(design.surface_thickness_m),
            body_weight_kg: Number(design.body_weight_kg),
          },
          conductor: {
            ...(base.conductor || {}),
            material_id: design.conductor_material_id,
            cross_section_mm2: Number(design.conductor_section_mm2),
            joint_type: design.conductor_joint_type,
            thermal_profile: design.conductor_thermal_profile,
            ...(design.conductor_thermal_profile === "RETIE 2024"
              ? { voltage_level: design.conductor_voltage_level }
              : {}),
            maximum_temperature_c: Number(
              design.conductor_maximum_temperature_c,
            ),
            thermal_duration_s: Number(design.thermal_duration_s),
            ambient_temperature_c: Number(design.ambient_temperature_c),
          },
        }),
      });
      setBaseArtifact(artifact);
      onArtifactSaved?.();
      const calculationParameters = {
        surface_spacing_m: 0.5,
        safety_standards: [standard],
        // Optional: without S_f the whole fault current enters the grid (conservative).
        ...(design.split_factor !== "" && design.split_factor != null ? { fault_split: {
          split_factor: Number(design.split_factor),
          split_factor_origin: "Factor S_f ingresado por el usuario",
        } } : {}),
      };
      if (design.x_over_r !== "")
        calculationParameters.x_over_r = Number(design.x_over_r);
      const queued = await request(
        `${root}/${artifact.artifact_id}/versions/${artifact.version}/calculos-potencial`,
        { method: "POST", body: JSON.stringify(calculationParameters) },
      );
      setCalculation(queued);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!calculation || !["pending", "running"].includes(calculation.status))
      return undefined;
    const timer = setInterval(async () => {
      try {
        const latest = await request(
          `${root}/${calculation.artifact_id || ""}/calculos-potencial/${calculation.id}`,
        );
        setCalculation(latest);
        if (!["pending", "running"].includes(latest.status)) setBusy(false);
      } catch (e) {
        setError(e.message);
        setBusy(false);
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [calculation?.id, calculation?.status]);
  useEffect(() => {
    if (section !== "safety") return undefined;
    let live = true;
    const refresh = async () => {
      try {
        const artifacts = await request(root);
        const artifact = artifacts[0];
        if (!artifact || !live) return;
        const rows = await request(
          `${root}/${artifact.artifact_id}/versions/${artifact.version}/calculos-potencial`,
        );
        if (
          live &&
          rows.length &&
          (!calculation || rows[0].created_at >= calculation.created_at)
        )
          setCalculation(rows[0]);
      } catch (_) {
        /* The form can still be used if historical results are unavailable. */
      }
    };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [section, project.id, token]);
  // Calculation records are scoped by artifact id; retain it from the newly created artifact.
  const num = (value, digits = 1) =>
    Number(value).toLocaleString("es-CO", { maximumFractionDigits: digits });
  return (
    <div className="grounding-calc-center">
      {section === "measurements" && (
        <>
          <section className="panel calc-panel">
            <div className="panel-heading">
              <div>
                <IconMeasurements size={17} />
                <h2>Resistividad del terreno</h2>
              </div>
              <span className="count">{readings.length} puntos</span>
            </div>
            <label className="layer-count-control">
              Método de medición
              <select
                value={measurementMethod}
                onChange={(e) => {
                  setFit(null);
                  setSoilFileSource(null);
                  setMeasurementMethod(e.target.value);
                }}
              >
                <option value="wenner">Wenner</option>
                <option value="schlumberger">Schlumberger</option>
                <option value="three_point">
                  Tres puntos (caída de potencial)
                </option>
                <option value="pole_dipole">Polo–dipolo</option>
              </select>
            </label>
            <p className="calc-help">
              <strong>Valores de ejemplo:</strong> reemplázalos por las
              mediciones de campo. Registra espaciamiento y resistividad
              aparente. El ajuste automático de capas está disponible para
              Wenner y Schlumberger.
            </p>
            <details className="safety-group soil-file-import">
              <summary>
                <h3>Importar desde CSV o XLSX</h3>
                <ChevronDown size={15} />
              </summary>
              <p>
                Elige un archivo escaneado, indica las columnas y filas con
                lecturas, y confirma las unidades. Los encabezados no se
                interpretan automáticamente.
              </p>
              {tableFiles.length ? (
                <div className="calc-form-grid">
                  <label>
                    Archivo
                    <select
                      value={importConfig.upload_id}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          upload_id: e.target.value,
                        })
                      }
                    >
                      <option value="">Selecciona un archivo disponible</option>
                      {tableFiles.map((file) => (
                        <option key={file.upload_id} value={file.upload_id}>
                          {file.filename}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Hoja (vacío para CSV o primera hoja)
                    <input
                      value={importConfig.sheet}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          sheet: e.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    Columna de espaciamiento
                    <input
                      value={importConfig.spacing_column}
                      maxLength={3}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          spacing_column: e.target.value.toUpperCase(),
                        })
                      }
                    />
                  </label>
                  <label>
                    Columna de valor
                    <input
                      value={importConfig.value_column}
                      maxLength={3}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          value_column: e.target.value.toUpperCase(),
                        })
                      }
                    />
                  </label>
                  {measurementMethod === "schlumberger" && (
                    <label>
                      Columna MN (opcional para resistividad aparente)
                      <input
                        value={importConfig.potential_column}
                        maxLength={3}
                        onChange={(e) =>
                          setImportConfig({
                            ...importConfig,
                            potential_column: e.target.value.toUpperCase(),
                          })
                        }
                      />
                    </label>
                  )}
                  <label>
                    Primera fila
                    <input
                      type="number"
                      min="1"
                      value={importConfig.first_row}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          first_row: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <label>
                    Última fila
                    <input
                      type="number"
                      min={importConfig.first_row}
                      value={importConfig.last_row}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          last_row: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <label>
                    Valor medido
                    <select
                      value={importConfig.value_kind}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          value_kind: e.target.value,
                          value_unit:
                            e.target.value === "resistance" ? "ohm" : "ohm_m",
                        })
                      }
                    >
                      <option value="apparent_resistivity">
                        Resistividad aparente
                      </option>
                      <option value="resistance">Resistencia R (Ω)</option>
                    </select>
                  </label>
                  <label>
                    Unidad del espaciamiento
                    <select
                      value={importConfig.spacing_unit}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          spacing_unit: e.target.value,
                        })
                      }
                    >
                      <option value="m">m</option>
                      <option value="cm">cm</option>
                      <option value="mm">mm</option>
                    </select>
                  </label>
                  {importConfig.value_kind === "apparent_resistivity" && (
                    <label>
                      Unidad de resistividad
                      <select
                        value={importConfig.value_unit}
                        onChange={(e) =>
                          setImportConfig({
                            ...importConfig,
                            value_unit: e.target.value,
                          })
                        }
                      >
                        <option value="ohm_m">Ω·m</option>
                        <option value="ohm_cm">Ω·cm</option>
                      </select>
                    </label>
                  )}
                  {measurementMethod === "schlumberger" &&
                    importConfig.value_kind === "resistance" && (
                      <>
                        <label>
                          Columna MN
                          <input
                            value={importConfig.potential_column}
                            maxLength={3}
                            onChange={(e) =>
                              setImportConfig({
                                ...importConfig,
                                potential_column: e.target.value.toUpperCase(),
                              })
                            }
                          />
                        </label>
                        <label>
                          Unidad de MN
                          <select
                            value={importConfig.potential_spacing_unit}
                            onChange={(e) =>
                              setImportConfig({
                                ...importConfig,
                                potential_spacing_unit: e.target.value,
                              })
                            }
                          >
                            <option value="m">m</option>
                            <option value="cm">cm</option>
                            <option value="mm">mm</option>
                          </select>
                        </label>
                      </>
                    )}
                  <label>
                    Separador decimal
                    <select
                      value={importConfig.decimal}
                      onChange={(e) =>
                        setImportConfig({
                          ...importConfig,
                          decimal: e.target.value,
                        })
                      }
                    >
                      <option value="auto">Automático (sin miles)</option>
                      <option value=",">Coma</option>
                      <option value=".">Punto</option>
                    </select>
                  </label>
                </div>
              ) : (
                <p className="calc-help">
                  Primero carga un CSV o XLSX y espera a que finalice su
                  análisis.
                </p>
              )}
              <button
                className="button primary"
                disabled={
                  busy ||
                  !importConfig.upload_id ||
                  !tableFiles.some(
                    (file) => file.upload_id === importConfig.upload_id,
                  )
                }
                onClick={importSoilFile}
              >
                {busy ? "Importando…" : "Importar y ajustar sondeo"}
              </button>
              {soilFileSource && (
                <small>
                  Origen aplicado: {soilFileSource.filename} ·{" "}
                  {soilFileSource.sheet} · {soilFileSource.rows.length} filas ·
                  SHA-256 {soilFileSource.sha256.slice(0, 12)}…
                </small>
              )}
            </details>
            <div className="measurement-table">
              <div className="measurement-head">
                <span>
                  {measurementMethod === "schlumberger"
                    ? "AB/2 (m)"
                    : measurementMethod === "three_point"
                      ? "Distancia auxiliar (m)"
                      : "Espaciamiento a (m)"}
                </span>
                <span>
                  {measurementMethod === "three_point"
                    ? "Resistencia medida (Ω)"
                    : "Resistividad aparente (Ω·m)"}
                </span>
                <span></span>
              </div>
              {readings.map((r, i) => (
                <div className="measurement-row" key={i}>
                  <input
                    type="number"
                    min="0.01"
                    step="any"
                    placeholder="Falta"
                    value={r.spacing_m}
                    onChange={(e) => setReading(i, "spacing_m", e.target.value)}
                    aria-label={`Espaciamiento lectura ${i + 1}`}
                  />
                  <input
                    type="number"
                    min="0.01"
                    step="any"
                    placeholder="Falta"
                    value={r.apparent_resistivity_ohm_m}
                    onChange={(e) =>
                      setReading(
                        i,
                        "apparent_resistivity_ohm_m",
                        e.target.value,
                      )
                    }
                    aria-label={`${measurementMethod === "three_point" ? "Resistencia" : "Resistividad aparente"} lectura ${i + 1}`}
                  />
                  <button
                    disabled={readings.length <= 4}
                    title="Quitar lectura"
                    onClick={() => {
                      setFit(null);
                      setSoilFileSource(null);
                      setReadings((rows) =>
                        rows.filter((_, index) => index !== i),
                      );
                    }}
                  >
                    <X size={15} />
                  </button>
                </div>
              ))}
            </div>
            <div className="calc-actions">
              <button
                className="button"
                onClick={() => {
                  setFit(null);
                  setSoilFileSource(null);
                  setReadings((rows) => [
                    ...rows,
                    { spacing_m: "", apparent_resistivity_ohm_m: "" },
                  ]);
                }}
              >
                <Plus size={14} /> Agregar medición
              </button>
            </div>
          </section>
          <MeasurementTemplates token={token} method={measurementMethod} />
        </>
      )}
      {section === "soil" && (
        <section className="panel calc-panel">
          <div className="panel-heading">
            <div>
              <IconSoil size={17} />
              <h2>Modelo de suelo</h2>
            </div>
            {soilLayers?.length > 0 && (
              <span className="muted-label">{soilLayers.length} {soilLayers.length === 1 ? "capa" : "capas"}</span>
            )}
          </div>
          <p className="calc-help">
            Define el perfil que usará el cálculo. Puedes ajustarlo con
            mediciones de campo o ingresar las capas directamente.
          </p>
          <div className="calc-actions">
            <button
              className={`button ${soilSource === "measurements" ? "primary" : ""}`}
              onClick={() => setSoilSource("measurements")}
            >
              A partir de mediciones
            </button>
            <button
              className={`button ${soilSource === "manual" ? "primary" : ""}`}
              onClick={() => setSoilSource("manual")}
            >
              Por capas y materiales
            </button>
          </div>
          {soilSource === "measurements" ? (
            <>
              <label className="layer-count-control">
                <HelpLabel text="Capas que quieres ajustar" topic="soil_layers_fit"/>
                <select
                  value={selectedLayerCount}
                  onChange={(e) => {
                    setFit(null);
                    setLayerCount(Number(e.target.value));
                  }}
                >
                  {Array.from({ length: 7 }, (_, i) => i + 2).map((count) => (
                    <option key={count} value={count}>
                      {count} capas
                    </option>
                  ))}
                </select>
              </label>
              <p className="calc-help">
                El ajuste admite de 2 a 8 capas y requiere al menos 2 lecturas
                válidas por capa. Hay {validMeasurementCount} lecturas; para
                ajustar {selectedLayerCount} capas necesitas{" "}
                {selectedLayerCount * 2}. Agrega mediciones en la pestaña
                Mediciones. Wenner y Schlumberger están disponibles.
              </p>
              <div className="calc-actions">
                <button
                  className="button primary"
                  disabled={busy || !canFitMeasurements}
                  onClick={fitSoil}
                >
                  {busy
                    ? "Ajustando…"
                    : `Ajustar ${selectedLayerCount} capas con las mediciones`}
                </button>
              </div>
              {fit && (
                <>
                  <div className="soil-fit-result">
                    <div className="fit-title">
                      <Check size={16} /> Perfil ajustado{" "}
                      {Number.isFinite(Number(fit.rms_error_percent)) && fit.rms_error_percent !== null && (
                        <span>RMS {num(fit.rms_error_percent, 2)}%</span>
                      )}
                    </div>
                    {fit.warnings?.map((warning) => (
                      <small key={warning}>{warning}</small>
                    ))}
                  </div>
                  <div className="soil-material-list">
                    {fit.soil_layers.map((layer, i) => (
                      <div className="soil-material-row" key={i}>
                        <label>
                          Capa {i + 1}
                          <select
                            value={layer.material || "Personalizado"}
                            onChange={(e) => {
                              const material = soilMaterials.find(
                                (item) => item.name === e.target.value,
                              );
                              updateSoilLayer(i, "material", material.name);
                              if (material.rho)
                                updateSoilLayer(
                                  i,
                                  "resistivity_ohm_m",
                                  material.rho,
                                );
                            }}
                          >
                            <option value="Personalizado">Personalizado</option>
                            {soilMaterials
                              .filter((item) => item.rho)
                              .map((item) => (
                                <option key={item.name} value={item.name}>
                                  {item.name} · {item.range} Ω·m
                                </option>
                              ))}
                          </select>
                        </label>
                        <label>
                          <HelpLabel text="Resistividad (Ω·m)" topic="soil_resistivity"/>
                          <input
                            type="number"
                            min="0.01"
                            step="any"
                            value={Number(layer.resistivity_ohm_m).toFixed(2)}
                            onChange={(e) =>
                              updateSoilLayer(
                                i,
                                "resistivity_ohm_m",
                                e.target.value,
                              )
                            }
                          />
                        </label>
                        {i < fit.soil_layers.length - 1 ? (
                          <label>
                            Espesor (m)
                            <input
                              type="number"
                              min="0.01"
                              step="any"
                              value={typeof layer.depth_m === "number" ? Number(layer.depth_m.toFixed(3)) : layer.depth_m}
                              onChange={(e) =>
                                updateSoilLayer(i, "depth_m", e.target.value)
                              }
                            />
                          </label>
                        ) : (
                          <small>Semiespacio inferior</small>
                        )}
                      </div>
                    ))}
                  </div>
                  <SoilFitChart readings={readings} fit={fit} />
                </>
              )}
            </>
          ) : (
            <>
              <p className="calc-help">
                Define cada capa desde la superficie hacia abajo. La última capa
                representa el semiespacio inferior.
              </p>
              <div className="soil-material-list">
                {manualLayers.map((layer, i) => (
                  <div className="soil-material-row" key={i}>
                    <label>
                      Capa {i + 1}
                      <select
                        value={layer.material}
                        onChange={(e) => {
                          const material = soilMaterials.find((item) => item.name === e.target.value);
                          setManualLayers((layers) => layers.map((item, index) => index === i
                            ? { ...item, material: material?.name || "", resistivity_ohm_m: material?.rho || item.resistivity_ohm_m }
                            : item));
                        }}
                      >
                        <option value="">Falta</option>
                        <option value="Personalizado">Personalizado</option>
                        {soilMaterials
                          .filter((item) => item.rho)
                          .map((item) => (
                            <option key={item.name} value={item.name}>
                              {item.name} · {item.range} Ω·m
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      <HelpLabel text="Resistividad (Ω·m)" topic="soil_resistivity"/>
                      <input
                        type="number"
                        min="0.01"
                        step="any"
                        placeholder="Falta"
                        value={layer.resistivity_ohm_m}
                        onChange={(e) =>
                          setManualLayers((layers) =>
                            layers.map((item, index) =>
                              index === i
                                ? {
                                    ...item,
                                    resistivity_ohm_m: e.target.value,
                                    material: "Personalizado",
                                  }
                                : item,
                            ),
                          )
                        }
                      />
                    </label>
                    {i < manualLayers.length - 1 ? (
                      <label>
                        Espesor (m)
                        <input
                          type="number"
                          min="0.01"
                          step="any"
                          placeholder="Falta"
                          value={layer.depth_m}
                          onChange={(e) =>
                            setManualLayers((layers) =>
                              layers.map((item, index) =>
                                index === i
                                  ? { ...item, depth_m: e.target.value }
                                  : item,
                              ),
                            )
                          }
                        />
                      </label>
                    ) : (
                      <small>Semiespacio inferior</small>
                    )}
                    <button
                      className="button"
                      disabled={manualLayers.length <= 1}
                      onClick={() =>
                        setManualLayers((layers) =>
                          layers
                            .filter((_, index) => index !== i)
                            .map((item, index, remaining) =>
                              index === remaining.length - 1
                                ? { ...item, depth_m: null }
                                : item,
                            ),
                        )
                      }
                    >
                      Quitar
                    </button>
                  </div>
                ))}
              </div>
              <button
                className="button soil-add-layer"
                disabled={manualLayers.length >= 8}
                onClick={() =>
                  setManualLayers((layers) => {
                    const last = layers[layers.length - 1];
                    return [
                      ...layers.slice(0, -1),
                      { material: "", resistivity_ohm_m: "", depth_m: "" },
                      { ...last },
                    ];
                  })
                }
              >
                <Plus size={14} /> Agregar capa
              </button>
            </>
          )}
          {soilReady && (
            <p className="calc-help">
              El perfil se guardará en el diseño cuando ejecutes el cálculo.
            </p>
          )}
        </section>
      )}
      {section === "safety" && (
        <section className="panel calc-panel safety-panel">
          <div className="panel-heading">
            <div>
              <IconParameters size={17} />
              <h2>Parámetros eléctricos</h2>
            </div>
            <span className="muted-label">IEEE 80-2013</span>
          </div>
          <p className="calc-help safety-intro">
            Completa las condiciones de falla y seguridad, y define el conductor
            que quieres verificar. La geometría de la malla se configura en
            Plano.
          </p>
          <div className="safety-standard">
            <label>
              <HelpLabel text="Norma de seguridad" topic="standards"/>
              <select
                value={standard}
                onChange={(e) => setStandard(e.target.value)}
              >
                <option value="IEEE 80-2013">IEEE 80-2013</option>
                <option value="EN 50522:2010" disabled>
                  EN 50522:2010 · parámetros pendientes
                </option>
                <option value="RETIE 2013" disabled>
                  RETIE 2013 · parámetros pendientes
                </option>
              </select>
            </label>
          </div>

          <details className="safety-group" open>
            <summary>
              <h3>Falla</h3>
              <ChevronDown size={15} />
            </summary>
            <p>Datos eléctricos del evento que debe soportar la malla.</p>
            <div className="calc-form-grid">
              {[
                ["Corriente de cortocircuito (A)", "current_a"],
                ["Tiempo de despeje (s)", "clearing_time_s"],
              ].map(([label, key]) => (
                <label key={key}>
                  <HelpLabel text={label} topic={FIELD_HELP[key]}/>
                  <input
                    type="number"
                    min="0.01"
                    step="any"
                    placeholder="Falta"
                    value={design[key]}
                    onChange={(e) =>
                      setDesign({ ...design, [key]: e.target.value })
                    }
                  />
                </label>
              ))}
            </div>
          </details>

          <details className="safety-group" open>
            <summary>
              <h3>Seguridad de las personas</h3>
              <ChevronDown size={15} />
            </summary>
            <p>
              Condiciones de la superficie y del cuerpo usadas para evaluar las
              tensiones tolerables.
            </p>
            <div className="calc-form-grid">
              {[
                ["Resistividad superficial (Ω·m)", "surface_resistivity_ohm_m"],
                ["Espesor superficial (m)", "surface_thickness_m"],
                ["Peso corporal (kg)", "body_weight_kg"],
              ].map(([label, key]) => (
                <label key={key}>
                  <HelpLabel text={label} topic={FIELD_HELP[key]}/>
                  <input
                    type="number"
                    min={key === "body_weight_kg" ? "50" : "0.01"}
                    max={key === "body_weight_kg" ? "70" : undefined}
                    step="any"
                    placeholder="Falta"
                    value={design[key]}
                    onChange={(e) =>
                      setDesign({ ...design, [key]: e.target.value })
                    }
                  />
                </label>
              ))}
            </div>
          </details>

          <details className="safety-group" open>
            <summary>
              <h3>Conductor de puesta a tierra</h3>
              <ChevronDown size={15} />
            </summary>
            <p>
              Define la selección que se comparará con la sección térmica mínima
              calculada.
            </p>
            <div className="calc-form-grid">
              <label>
                <HelpLabel text="Norma de dimensionamiento" topic="thermal_standard"/>
                <select
                  value={design.conductor_thermal_profile}
                  onChange={(e) =>
                    updateThermal({ conductor_thermal_profile: e.target.value })
                  }
                >
                  {thermalProfiles.map((p) => (
                    <option key={p.profile} value={p.profile}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              {thermalProfile.modes.length > 1 && (
                <label>
                  <HelpLabel text="Nivel de tensión" topic="voltage_level"/>
                  <select
                    value={thermalMode.voltage_level}
                    onChange={(e) =>
                      updateThermal({ conductor_voltage_level: e.target.value })
                    }
                  >
                    {thermalProfile.modes.map((m) => (
                      <option key={m.voltage_level} value={m.voltage_level}>
                        {VOLTAGE_LEVEL_LABELS[m.voltage_level] || m.voltage_level}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                <HelpLabel text="Material" topic="conductor_material"/>
                <select
                  value={
                    design.conductor_material_id === "copper_clad_rod_20" &&
                    thermalProfile.profile === "IEEE 80-2013"
                      ? "copper_clad_rod_17"
                      : design.conductor_material_id
                  }
                  onChange={(e) =>
                    updateThermal({ conductor_material_id: e.target.value })
                  }
                >
                  {thermalMode.materials.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                      {m.tm_c != null
                        ? ` · Tₘ ${m.tm_c} °C · Kf ${m.kf}`
                        : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <HelpLabel text="Unión" topic="joint_type"/>
                <select
                  value={design.conductor_joint_type}
                  onChange={(e) =>
                    setDesign({
                      ...design,
                      conductor_joint_type: e.target.value,
                    })
                  }
                >
                  <option value="bolted">Apernada</option>
                  <option value="brazed">Brazed / presión</option>
                  <option value="welded">Soldada / exotérmica</option>
                  <option value="other">Otra</option>
                </select>
              </label>
              <label>
                <HelpLabel text="Sección elegida (mm²)" topic="conductor_section"/>
                <input
                  type="number"
                  min="0.01"
                  step="any"
                  value={design.conductor_section_mm2}
                  onChange={(e) =>
                    setDesign({
                      ...design,
                      conductor_section_mm2: e.target.value,
                    })
                  }
                />
              </label>
              <label>
                <HelpLabel text={thermalInitialFinal ? "Temperatura final θf (°C)" : "Temperatura máxima Tₘ (°C)"} topic="max_temperature"/>
                <input
                  type="number"
                  min="-50"
                  step="any"
                  disabled={thermalFromTable}
                  value={design.conductor_maximum_temperature_c}
                  onChange={(e) =>
                    setDesign({
                      ...design,
                      conductor_maximum_temperature_c: e.target.value,
                    })
                  }
                />
              </label>
              <label>
                <HelpLabel text="Duración térmica t꜀ (s)" topic="thermal_duration"/>
                <input
                  type="number"
                  min="0.001"
                  max={thermalMode.max_duration_s ?? undefined}
                  step="any"
                  value={design.thermal_duration_s}
                  onChange={(e) =>
                    setDesign({ ...design, thermal_duration_s: e.target.value })
                  }
                />
              </label>
              <label>
                <HelpLabel text={thermalInitialFinal ? "Temperatura inicial θi (°C)" : "Temperatura ambiente Tₐ (°C)"} topic="ambient_temperature"/>
                <input
                  type="number"
                  min="-50"
                  step="any"
                  disabled={thermalFromTable}
                  value={design.ambient_temperature_c}
                  onChange={(e) =>
                    setDesign({
                      ...design,
                      ambient_temperature_c: e.target.value,
                    })
                  }
                />
              </label>
            </div>
            {thermalMode.note && <p className="muted-label">{thermalMode.note}</p>}
            {durationExceeded && (
              <p className="calc-warning" role="alert">
                {thermalProfile.profile} solo aplica a tiempos de hasta{" "}
                {thermalMode.max_duration_s} s; corrige la duración térmica para calcular.
              </p>
            )}
          </details>

          <details className="safety-advanced">
            <summary>
              Parámetros avanzados <ChevronDown size={15} />
            </summary>
            <p>
              Usa estos valores cuando estén definidos para el sistema eléctrico
              del proyecto.
            </p>
            <div className="calc-form-grid">
              <label>
                <HelpLabel text={<>Factor de reparto S<sub>f</sub> (0–1)</>} topic="split_factor"/>
                <input
                  type="number"
                  min="0.001"
                  max="1"
                  step="any"
                  value={design.split_factor}
                  onChange={(e) =>
                    setDesign({ ...design, split_factor: e.target.value })
                  }
                />
                <small>
                  Fracción de la corriente de falla que entra a la malla.
                </small>
              </label>
              <label>
                <HelpLabel text="Relación X/R (opcional)" topic="x_over_r"/>
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={design.x_over_r}
                  onChange={(e) =>
                    setDesign({ ...design, x_over_r: e.target.value })
                  }
                />
                <small>
                  Relación reactancia/resistencia de la red en el punto de
                  falla.
                </small>
              </label>
            </div>
          </details>

          {(!soilReady || !designReady || durationExceeded) && (
            <div className="missing-inputs calc-missing" data-testid="calc-missing">
              <div className="missing-inputs-head"><div><strong>Para calcular falta</strong><p>El botón se habilita cuando completes esto.</p></div></div>
              <ul>
                {!soilReady && <li><span className="missing-dot"/><div><strong>Modelo de suelo</strong><small>Define las capas en la pestaña Suelo: ajustándolas con mediciones o por materiales.</small></div></li>}
                {gaps.map((gap) => <li key={gap.key}><span className="missing-dot"/><div><strong>{gap.text}</strong><small>{{ plano: "Viene del plano de la malla (Resumen › Editar plano).", falla: "En «Falla» o «Seguridad de las personas», arriba en este formulario.", conductor: "En «Conductor de puesta a tierra».", avanzados: "En «Parámetros avanzados»." }[gap.where]}</small></div></li>)}
                {durationExceeded && <li><span className="missing-dot"/><div><strong>Duración térmica fuera del rango de la norma</strong><small>Redúcela al máximo que admite la norma elegida.</small></div></li>}
              </ul>
            </div>
          )}
          <button
            className="button primary calc-run"
            disabled={!soilReady || !designReady || durationExceeded || busy}
            onClick={calculate}
          >
            <IconResult size={15} />
            {busy ? "Calculando…" : "Calcular tensiones y sección térmica"}
          </button>
          {calculation?.result && (
            <div className="calc-verdict">
              <VerdictCallout
                result={calculation.result}
                footer={
                  <div className="verdict-callout-foot">
                    <p>
                      Sección elegida {num(calculation.result.conductor_thermal.selected_section_mm2, 2)} mm² ·
                      sección estándar sugerida{" "}
                      {calculation.result.conductor_thermal.suggested_standard_section_mm2 != null
                        ? `${calculation.result.conductor_thermal.suggested_standard_section_mm2} mm²`
                        : "fuera de la tabla orientativa"}{" "}
                      · norma {calculation.result.conductor_thermal.profile}.
                    </p>
                    <p>
                      Este es un cálculo rápido con los parámetros del formulario. Para ver el mapa de
                      potencial y las formas de mejorar el diseño, abre la pestaña Resultado.
                    </p>
                    {calculation.result.conductor_thermal.warnings?.map((w) => (
                      <small className="calc-warning" role="note" key={w}>
                        Conductor: {w}
                      </small>
                    ))}
                  </div>
                }
              />
            </div>
          )}
        </section>
      )}
      {error && (
        <div className="project-error calc-error" role="alert">
          {error}
          <button onClick={() => setError("")}>
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

export { ArtifactPanel, GroundingCalculations, SurfacePotentialMap };
