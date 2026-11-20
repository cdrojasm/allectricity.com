import React, { useEffect, useRef, useState } from "react";
import { CircleAlert, CreditCard, Gift, ShieldCheck, X, Zap } from "lucide-react";

// Plan y facturación: the user's tier, its token balance, Mercado Pago checkout (Card Payment Brick: the card
// never touches Terra, only a single-use token) and license codes. The charge is asynchronous: the API answers
// 202 and this page polls /billing/subscription until the billing worker settles it.

const SDK_URL = "https://sdk.mercadopago.com/js/v2";
let sdkPromise = null;
function loadMercadoPago() {
  if (window.MercadoPago) return Promise.resolve();
  if (!sdkPromise) {
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = SDK_URL;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => { sdkPromise = null; reject(new Error("No se pudo cargar Mercado Pago. Revisa tu conexión.")); };
      document.head.appendChild(script);
    });
  }
  return sdkPromise;
}

const statusLabels = {
  authorized: "Activo", past_due: "Pago pendiente", cancelled: "Cancelado", suspended: "Suspendido",
  pending: "Procesando pago…", failed: "Pago no completado", expired: "Vencido", replaced: "Reemplazado",
};

async function request(token, url, options = {}) {
  const response = await fetch(url, { ...options, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.[0]?.msg || `La operación falló (${response.status}).`);
  }
  return body;
}

const tokens = (value) => (value >= 1e6 ? `${(value / 1e6).toLocaleString("es-CO", { maximumFractionDigits: 1 })} M` : Number(value || 0).toLocaleString("es-CO"));
const money = (amount, currency) => (amount == null ? "—" : new Intl.NumberFormat("es-CO", { style: "currency", currency: currency || "COP", maximumFractionDigits: 0 }).format(amount));
const date = (seconds) => (seconds ? new Date(seconds * 1000).toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" }) : "—");
const title = (name) => (name ? name.charAt(0).toUpperCase() + name.slice(1) : "");

export function BillingPage({ token, user, onNotice }) {
  const [catalog, setCatalog] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [code, setCode] = useState("");
  const [redeeming, setRedeeming] = useState(false);
  const wasPending = useRef(false);

  async function reloadSummary() {
    const next = await request(token, "/api/v1/billing/subscription");
    setSummary(next);
    return next;
  }
  async function reload() {
    try {
      const [plans, mine] = await Promise.all([request(token, "/api/v1/billing/plans"), request(token, "/api/v1/billing/subscription")]);
      setCatalog(plans); setSummary(mine); setError("");
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { reload(); }, [token]);

  const checkout = summary?.checkout;
  const pending = checkout?.status === "pending";
  useEffect(() => {
    if (!pending) return undefined;
    wasPending.current = true;
    const id = setInterval(() => { reloadSummary().catch(() => {}); }, 2500);
    return () => clearInterval(id);
  }, [pending, token]);
  useEffect(() => {
    if (!wasPending.current || pending || !summary) return;
    wasPending.current = false;
    if (summary.subscription && !summary.checkout) onNotice?.(`Listo: tu plan ${title(summary.subscription.tier)} está activo.`);
  }, [pending, summary]);

  const current = summary?.subscription;
  const plans = [...(catalog?.plans || [])].sort((a, b) => a.rank - b.rank);
  const currentRank = plans.find((plan) => plan.name === current?.tier)?.rank ?? -1;
  const used = current?.tokens?.used || 0;
  const total = current?.tokens?.total || 0;

  async function redeem(event) {
    event.preventDefault();
    setRedeeming(true); setError("");
    try {
      const result = await request(token, "/api/v1/billing/licenses/redeem", { method: "POST", body: JSON.stringify({ code }) });
      setCode("");
      onNotice?.(`Código canjeado: plan ${title(result.subscription?.tier)} activo.`);
      await reloadSummary();
    } catch (e) { setError(e.message); }
    finally { setRedeeming(false); }
  }

  return <section className="projects-page billing-page">
    <div className="projects-topline"><div><div className="eyebrow">TERRA WORKSPACE / PLAN</div><h1>Plan y facturación</h1><p>Tu plan define los tokens mensuales del agente. Los tokens se renuevan en cada cobro y no se acumulan.</p></div></div>
    {error && <div className="project-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Cerrar"><X size={14}/></button></div>}
    {catalog?.mode === "test" && <div className="billing-test-banner"><CircleAlert size={15}/> Modo de prueba de Mercado Pago: usa tarjetas y compradores de prueba.</div>}

    <div className="billing-current" data-testid="billing-current">
      {current ? <>
        <div><div className="eyebrow">TU PLAN</div><h2>{title(current.tier)} <span className={`billing-status ${current.status}`}>{statusLabels[current.status] || current.status}</span></h2>
          <p>{current.provider === "license" ? `Licencia hasta el ${date(current.ends_at)} · se recarga cada mes` : current.status === "cancelled" ? `Cancelado: tienes acceso hasta el ${date(current.ends_at)}` : current.status === "past_due" ? `No pudimos cobrar tu plan. Mercado Pago reintentará; tienes acceso hasta el ${date(current.grace_until)}.` : `Próxima renovación: ${date(current.period_end)}`}</p></div>
        <div className="billing-tokens"><span>{tokens(Math.max(total - used, 0))} disponibles</span><div className="token-bar" aria-label={`${used} de ${total} tokens usados`}><i style={{ width: `${total ? Math.min(100, (used / total) * 100) : 0}%` }}/></div><small>{tokens(used)} de {tokens(total)} usados este período</small></div>
      </> : <div><div className="eyebrow">TU PLAN</div><h2>Sin plan activo</h2><p>Elige un plan o canjea un código de licencia para usar el agente.</p></div>}
    </div>

    {checkout && <div className={`billing-checkout ${checkout.status}`} role="status">
      {checkout.status === "pending" ? <><span className="billing-spinner"/> Procesando el pago del plan {title(checkout.tier)} con Mercado Pago…</>
        : <><CircleAlert size={16}/> {checkout.error || "El pago no se completó."}</>}
    </div>}

    <div className="plan-grid">
      {plans.map((plan) => {
        const isCurrent = plan.name === current?.tier && current;
        const lower = plan.rank <= currentRank;
        const label = isCurrent ? "Tu plan" : lower ? "Incluido en tu plan" : current ? `Subir a ${title(plan.name)}` : "Suscribirme";
        return <article key={plan.name} className={`plan-card ${isCurrent ? "current" : ""}`} data-testid={`plan-${plan.name}`}>
          <div className="eyebrow">{plan.rank === plans.length - 1 ? "MÁXIMA CAPACIDAD" : plan.rank === 0 ? "PARA EMPEZAR" : "EQUIPOS"}</div>
          <h3>{title(plan.name)}</h3>
          <div className="plan-price"><strong>{money(plan.amount, plan.currency)}</strong><span>/mes</span></div>
          <small className="plan-usd">≈ USD {plan.price_usd}</small>
          <ul><li><Zap size={13}/> {tokens(plan.monthly_tokens)} tokens del agente al mes</li><li><ShieldCheck size={13}/> Se renuevan en cada cobro mensual</li></ul>
          <button className={`button ${lower ? "" : "primary"}`} disabled={lower || pending || !plan.available} onClick={() => { setError(""); setSelected(plan); }}>
            <CreditCard size={14}/> {plan.available ? label : "No disponible"}</button>
          {!plan.available && plan.unavailable_reason && <small className="plan-unavailable">{plan.unavailable_reason}</small>}
        </article>;
      })}
      {catalog && !plans.length && <p className="billing-empty">Los planes aún no están configurados.</p>}
    </div>

    <form className="billing-redeem" onSubmit={redeem}>
      <Gift size={17}/><div><strong>¿Tienes un código de licencia?</strong><small>Un código por persona; se usa una sola vez.</small></div>
      <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="TERRA-XXXX-XXXX-XXXX" maxLength={40} aria-label="Código de licencia" required/>
      <button className="button" type="submit" disabled={redeeming || code.length < 6}>{redeeming ? "Canjeando…" : "Canjear"}</button>
    </form>

    {selected && <CheckoutDialog token={token} user={user} catalog={catalog} plan={selected} current={current}
      onClose={() => setSelected(null)}
      onStarted={async () => { setSelected(null); await reloadSummary().catch(() => {}); }}/>}
  </section>;
}

function CheckoutDialog({ token, user, catalog, plan, current, onClose, onStarted }) {
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const containerId = "mp-card-brick";
  useEffect(() => {
    let controller = null;
    let cancelled = false;
    (async () => {
      try {
        await loadMercadoPago();
        if (cancelled) return;
        const mp = new window.MercadoPago(catalog.public_key, { locale: "es-CO" });
        // In test mode the payer must be a Mercado Pago test buyer, so the Brick asks for that email.
        const payer = catalog.mode === "prod" ? { email: user.email } : undefined;
        controller = await mp.bricks().create("cardPayment", containerId, {
          initialization: { amount: Number(plan.amount), ...(payer ? { payer } : {}) },
          customization: { paymentMethods: { maxInstallments: 1 }, visual: { style: { theme: "default" } } },
          callbacks: {
            onReady: () => setReady(true),
            onError: (brickError) => setError(brickError?.message || "Revisa los datos de la tarjeta."),
            onSubmit: async (formData) => {
              setError("");
              try {
                await request(token, "/api/v1/billing/checkout", { method: "POST", body: JSON.stringify({ tier: plan.name, card_token: formData.token, payer_email: formData.payer?.email || user.email }) });
                await onStarted();
              } catch (e) { setError(e.message); throw e; }
            },
          },
        });
        if (cancelled) controller?.unmount();
      } catch (e) { if (!cancelled) setError(e.message); }
    })();
    return () => { cancelled = true; try { controller?.unmount(); } catch { /* already unmounted */ } };
  }, [plan.name]);

  return <div className="modal-backdrop project-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <section className="project-modal billing-modal" role="dialog" aria-modal="true" aria-label={`Pagar plan ${plan.name}`}>
      <div className="project-modal-head"><div><div className="eyebrow">MERCADO PAGO</div><h2>Plan {title(plan.name)} · {money(plan.amount, plan.currency)}/mes</h2></div><button type="button" className="icon-button" aria-label="Cerrar" onClick={onClose}><X size={18}/></button></div>
      <div className="project-form-body">
        {current && <p className="billing-upgrade-note">Al subir de plan se cobra hoy el plan {title(plan.name)} completo, tu fecha de cobro pasa a ser hoy y tu bolsa se reemplaza por {tokens(plan.monthly_tokens)} tokens. El plan {title(current.tier)} se cancela cuando el nuevo quede activo.</p>}
        <p className="map-optional-hint">Cobro mensual recurrente. Los datos de la tarjeta los procesa Mercado Pago; Terra no los ve ni los guarda.</p>
        {!ready && !error && <p className="map-optional-hint">Cargando formulario de pago…</p>}
        <div id={containerId}/>
      </div>
      {error && <div className="project-modal-error" role="alert">{error}</div>}
    </section>
  </div>;
}
