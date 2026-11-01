let refreshInFlight = null;

const ACCESS_KEY = "spat_access_token";
const REFRESH_KEY = "spat_refresh_token";
const EXPIRED_EVENT = "spat:session-expired";

function signalExpired() {
  window.dispatchEvent(new CustomEvent(EXPIRED_EVENT));
}

async function refreshAccessToken(nativeFetch) {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const refreshToken = localStorage.getItem(REFRESH_KEY);
      if (!refreshToken) throw new Error("Refresh token missing");
      const response = await nativeFetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.access_token || !data.refresh_token) throw new Error("Session refresh failed");
      localStorage.setItem(ACCESS_KEY, data.access_token);
      localStorage.setItem(REFRESH_KEY, data.refresh_token);
      localStorage.setItem("spat_access_expires_at", String(Date.now() + Number(data.expires_in || 900) * 1000));
      return data.access_token;
    })().finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

export function installAuthenticatedFetch() {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, options = {}) => {
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    const authorization = headers.get("Authorization") || headers.get("authorization") || "";
    if (!authorization.startsWith("Bearer ")) return nativeFetch(input, options);

    const usedToken = authorization.slice(7);
    const retryInput = input instanceof Request ? input.clone() : input;
    let response = await nativeFetch(input, options);
    const url = typeof input === "string" ? input : input.url || String(input);
    if (response.status !== 401 || url.includes("/api/v1/auth/refresh")) return response;

    try {
      // Another request may already have rotated this token. Reuse the new token
      // instead of consuming the single-use refresh token a second time.
      let accessToken = localStorage.getItem(ACCESS_KEY);
      if (!accessToken || accessToken === usedToken) accessToken = await refreshAccessToken(nativeFetch);
      const retryHeaders = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
      retryHeaders.set("Authorization", `Bearer ${accessToken}`);
      const retryOptions = { ...options, headers: retryHeaders };
      response = await nativeFetch(retryInput, retryOptions);
      if (response.status === 401) signalExpired();
      return response;
    } catch {
      signalExpired();
      return response;
    }
  };
  return () => { window.fetch = nativeFetch; };
}

export { EXPIRED_EVENT };
