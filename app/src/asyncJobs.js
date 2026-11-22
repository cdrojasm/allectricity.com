// Slow requests (LLM answers, plan analysis, soil fits) answer 202 with a background job; this waits for it.

const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const timer = setTimeout(resolve, ms);
  signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
});

/**
 * Poll `/api/v1/jobs/{job_id}` until the job ends. Resolves with its result; a failed job throws its
 * message in the product's language, with `status` set to the HTTP code the endpoint used to answer.
 */
export async function awaitJob(token, accepted, { signal, timeoutMs = 300_000 } = {}) {
  if (!accepted?.job_id) return accepted; // already a final answer
  const started = Date.now();
  let job = accepted;
  while (job.status === "queued" || job.status === "running") {
    if (Date.now() - started > timeoutMs) throw new Error("La tarea está tardando demasiado. Inténtalo de nuevo.");
    await sleep(job.poll_after_ms || 1000, signal);
    const response = await fetch(`/api/v1/jobs/${encodeURIComponent(accepted.job_id)}`, {
      headers: { Authorization: `Bearer ${token}` }, signal,
    });
    if (!response.ok) {
      // A transient error while polling (deploy, network) is retried; a missing job is not.
      if (response.status === 404) throw new Error("La tarea ya no existe.");
      if (response.status === 401) throw Object.assign(new Error("Tu sesión expiró."), { status: 401 });
      continue;
    }
    job = await response.json();
  }
  if (job.status !== "completed") {
    throw Object.assign(new Error(job.error || "No se pudo completar la solicitud."), { status: job.error_code || 500 });
  }
  return job.result;
}
