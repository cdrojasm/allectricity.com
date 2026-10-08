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

const REQUIRED_DESIGN_FIELDS = [
  "length_m",
  "width_m",
  "burial_depth_m",
  "conductor_spacing_m",
  "rods_count",
  "rod_length_m",
  "current_a",
  "clearing_time_s",
  "surface_resistivity_ohm_m",
  "surface_thickness_m",
  "body_weight_kg",
  "conductor_section_mm2",
  "conductor_maximum_temperature_c",
  "thermal_duration_s",
  "ambient_temperature_c",
  "split_factor",
];

function isDesignComplete(design) {
  const numericFieldsPresent = REQUIRED_DESIGN_FIELDS.every(
    (key) =>
      design[key] !== "" &&
      design[key] != null &&
      Number.isFinite(Number(design[key])) &&
      Number(design[key]) > 0,
  );
  return (
    numericFieldsPresent &&
    Boolean(design.conductor_material_id && design.conductor_joint_type) &&
    Number(design.body_weight_kg) >= 50 &&
    Number(design.body_weight_kg) <= 70 &&
    Number(design.split_factor) <= 1
  );
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

function SurfacePotentialMap({ field }) {
  if (!field?.values_v?.length || !field.nx || !field.ny) return null;
  const values = field.values_v;
  const min = values.reduce((a, b) => Math.min(a, b), Infinity),
    max = values.reduce((a, b) => Math.max(a, b), -Infinity);
  const color = (value) => {
    const t = (value - min) / (max - min || 1);
    const hue = 220 - 220 * t;
    return `hsl(${hue} 78% 52%)`;
  };
  const dx = field.spacing_m,
    width = field.nx * dx,
    height = field.ny * dx;
  return (
    <section
      className="surface-map-panel"
      aria-label="Mapa de potencial superficial"
    >
      <div className="surface-map-heading">
        <strong>Potencial superficial</strong>
        <span>
          {field.nx} × {field.ny} puntos · V
        </span>
      </div>
      <svg
        className="surface-map"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Mapa de potencial superficial, de ${min.toFixed(1)} a ${max.toFixed(1)} voltios`}
        preserveAspectRatio="none"
      >
        {values.map((value, index) => {
          const col = index % field.nx;
          const row = Math.floor(index / field.nx);
          return (
            <rect
              key={index}
              x={col * dx}
              y={(field.ny - 1 - row) * dx}
              width={dx + 0.01}
              height={dx + 0.01}
              fill={color(value)}
            />
          );
        })}
        <rect
          x={field.grid_x_m || 0}
          y={height - (field.grid_y_m || 0) - (field.grid_height_m || 0)}
          width={field.grid_width_m || width}
          height={field.grid_height_m || height}
          fill="none"
          stroke="#172a25"
          strokeWidth={Math.max(0.12, dx * 0.035)}
          strokeDasharray={`${dx * 0.25} ${dx * 0.16}`}
        />
      </svg>
      <div className="surface-map-scale">
        <span>
          {min.toLocaleString("es-CO", { maximumFractionDigits: 1 })} V
        </span>
        <i />
        <span>
          {max.toLocaleString("es-CO", { maximumFractionDigits: 1 })} V
        </span>
      </div>
      <small>
        El contorno punteado marca el perímetro de la malla; el color representa
        la tensión calculada en la superficie.
      </small>
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
          <h2>Artefacto de puesta a tierra</h2>
        </div>
        <span className="muted-label">{result ? "Calculado" : "Borrador"}</span>
      </div>
      <div className="artifact-preview-empty">
        <Box size={25} />
        <strong>
          {design ? "Geometría del diseño" : "Aún no hay un artefacto de malla"}
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
            {Number(result.max_touch_v).toFixed(1)} V contacto ·{" "}
            {Number(result.max_step_v).toFixed(1)} V paso
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
    conductor_maximum_temperature_c: "",
    thermal_duration_s: "",
    ambient_temperature_c: "",
  });
  const soilLayers = soilSource === "manual" ? manualLayers : fit?.soil_layers;
  const soilReady = Boolean(
    soilLayers?.length &&
    soilLayers.every(
      (layer, index) =>
        Number(layer.resistivity_ohm_m) > 0 &&
        (index === soilLayers.length - 1 || Number(layer.depth_m) > 0),
    ),
  );
  const designReady = isDesignComplete(design);
  const validMeasurementCount = readings.filter(
    (reading) =>
      Number(reading.spacing_m) > 0 &&
      Number.isFinite(Number(reading.spacing_m)) &&
      Number(reading.apparent_resistivity_ohm_m) > 0 &&
      Number.isFinite(Number(reading.apparent_resistivity_ohm_m)),
  ).length;
  const selectedLayerCount = layerCount;
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
      throw new Error(data?.detail || "No se pudo completar la operación.");
    return data;
  };
  const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras`;
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
      const imported = await request(
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
      );
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
        await request(`${root}/mediciones-suelo/ajustar`, {
          method: "POST",
          body: JSON.stringify({
            array: measurementMethod,
            layer_count: Number(selectedLayerCount),
            measurements: readings.map((r) => ({
              spacing_m: Number(r.spacing_m),
              apparent_resistivity_ohm_m: Number(r.apparent_resistivity_ohm_m),
            })),
          }),
        }),
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
      const artifact = await request(root, {
        method: "POST",
        body: JSON.stringify({
          name: design.name,
          geometry: {
            length_m: Number(design.length_m),
            width_m: Number(design.width_m),
            burial_depth_m: Number(design.burial_depth_m),
            conductor_spacing_m: Number(design.conductor_spacing_m),
            rods_count: Number(design.rods_count),
            rod_length_m: Number(design.rod_length_m),
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
            current_a: Number(design.current_a),
            clearing_time_s: Number(design.clearing_time_s),
            surface_resistivity_ohm_m: Number(design.surface_resistivity_ohm_m),
            surface_thickness_m: Number(design.surface_thickness_m),
            body_weight_kg: Number(design.body_weight_kg),
          },
          conductor: {
            material_id: design.conductor_material_id,
            cross_section_mm2: Number(design.conductor_section_mm2),
            joint_type: design.conductor_joint_type,
            maximum_temperature_c: Number(
              design.conductor_maximum_temperature_c,
            ),
            thermal_duration_s: Number(design.thermal_duration_s),
            ambient_temperature_c: Number(design.ambient_temperature_c),
          },
        }),
      });
      onArtifactSaved?.();
      const calculationParameters = {
        surface_spacing_m: 0.5,
        safety_standards: [standard],
        fault_split: {
          split_factor: Number(design.split_factor),
          split_factor_origin: "Factor S_f ingresado por el usuario",
        },
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
                <FileSpreadsheet size={17} />
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
              <Layers size={17} />
              <h2>Modelo de suelo</h2>
            </div>
            {soilLayers?.length > 0 && (
              <span className="muted-label">{soilLayers.length} capas</span>
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
                Capas que quieres ajustar
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
              <button
                className="button primary"
                disabled={busy || !canFitMeasurements}
                onClick={fitSoil}
              >
                {busy
                  ? "Ajustando…"
                  : `Ajustar ${selectedLayerCount} capas con las mediciones`}
              </button>
              {fit && (
                <>
                  <div className="soil-fit-result">
                    <div className="fit-title">
                      <Check size={16} /> Perfil ajustado{" "}
                      <span>RMS {num(fit.rms_error_percent)}%</span>
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
                          Resistividad (Ω·m)
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
                              value={layer.depth_m}
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
                      Resistividad (Ω·m)
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
                className="button"
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
              El perfil se guardará en el artefacto cuando ejecutes el cálculo.
            </p>
          )}
        </section>
      )}
      {section === "safety" && (
        <section className="panel calc-panel safety-panel">
          <div className="panel-heading">
            <div>
              <ShieldCheck size={17} />
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
              Norma de seguridad
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
                  {label}
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
                  {label}
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
                Material
                <select
                  value={design.conductor_material_id}
                  onChange={(e) =>
                    setDesign({
                      ...design,
                      conductor_material_id: e.target.value,
                    })
                  }
                >
                  <option value="copper_hard_drawn">
                    Cobre comercial duro
                  </option>
                  <option value="copper_annealed">Cobre recocido</option>
                  <option value="copper_clad_40">
                    Acero recubierto de cobre 40 %
                  </option>
                  <option value="copper_clad_30">
                    Acero recubierto de cobre 30 %
                  </option>
                  <option value="copper_clad_rod_20">
                    Varilla de acero recubierta de cobre 20 %
                  </option>
                  <option value="aluminum_clad_steel">
                    Acero recubierto de aluminio
                  </option>
                  <option value="steel_1020">Acero 1020</option>
                  <option value="stainless_clad_rod">
                    Varilla de acero inoxidable revestida
                  </option>
                  <option value="zinc_coated_steel_rod">
                    Varilla de acero galvanizada
                  </option>
                  <option value="stainless_304">Acero inoxidable 304</option>
                </select>
              </label>
              <label>
                Unión
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
                Sección elegida (mm²)
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
                Temperatura máxima Tₘ (°C)
                <input
                  type="number"
                  min="-50"
                  step="any"
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
                Duración térmica t꜀ (s)
                <input
                  type="number"
                  min="0.001"
                  step="any"
                  value={design.thermal_duration_s}
                  onChange={(e) =>
                    setDesign({ ...design, thermal_duration_s: e.target.value })
                  }
                />
              </label>
              <label>
                Temperatura ambiente Tₐ (°C)
                <input
                  type="number"
                  min="-50"
                  step="any"
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
                Factor de reparto S<sub>f</sub> (0–1)
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
                Relación X/R (opcional)
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

          <button
            className="button primary calc-run"
            disabled={!soilReady || !designReady || busy}
            onClick={calculate}
          >
            <Activity size={15} />
            {busy ? "Calculando…" : "Calcular tensiones y sección térmica"}
          </button>
          {calculation?.result && (
            <div className="soil-fit-result">
              <div className="fit-title">
                {calculation.result.safety?.[0]?.status ||
                  "Resultado disponible"}
              </div>
              <div className="result-metrics">
                <span>
                  <small>Tensión de contacto</small>
                  <strong>{num(calculation.result.max_touch_v)} V</strong>
                </span>
                <span>
                  <small>Tensión de paso</small>
                  <strong>{num(calculation.result.max_step_v)} V</strong>
                </span>
                <span>
                  <small>GPR</small>
                  <strong>{num(calculation.result.gpr_v)} V</strong>
                </span>
                <span>
                  <small>Sección térmica mínima</small>
                  <strong>
                    {num(
                      calculation.result.conductor_thermal.minimum_section_mm2,
                      2,
                    )}{" "}
                    mm²
                  </strong>
                </span>
              </div>
              <p>
                Sección elegida:{" "}
                {num(
                  calculation.result.conductor_thermal.selected_section_mm2,
                  2,
                )}{" "}
                mm² · margen{" "}
                {num(calculation.result.conductor_thermal.margin_mm2, 2)} mm² (
                {num(calculation.result.conductor_thermal.margin_percent, 1)} %)
                · sección estándar sugerida{" "}
                {calculation.result.conductor_thermal
                  .suggested_standard_section_mm2 ??
                  "supera la tabla orientativa"}{" "}
                mm².
              </p>
              <SurfacePotentialMap
                field={calculation.result.surface_potential}
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
