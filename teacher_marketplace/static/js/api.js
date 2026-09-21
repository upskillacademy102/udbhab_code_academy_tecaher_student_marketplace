/* ============================================================
   Udbhab API client
   The one place the browser talks to the DRF API. Every component
   goes through this so auth failures, permission errors, network
   errors and the {success,data|error} envelope are handled once.
   Auth travels on the httpOnly `access` cookie (same-origin) — no
   token handling in JS.
   ============================================================ */
(function () {
  "use strict";

  const BASE = (window.API_BASE_URL || "/api/v1").replace(/\/$/, "");

  class ApiError extends Error {
    constructor(message, { status = 0, code = "", fieldErrors = null } = {}) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.fieldErrors = fieldErrors; // { field: "message" }
    }
  }

  function friendly(status, code, detail) {
    if (status === 0) return "We couldn't reach the server. Check your connection and try again.";
    if (code === "CAPTCHA_REQUIRED") return "Please complete the verification challenge and try again.";
    if (status === 401) return "Your session has expired. Please log in again.";
    if (status === 403) return "You don't have permission to do that.";
    if (status === 404) return detail || "We couldn't find what you were looking for.";
    if (status === 409) return detail || "That action conflicts with the current state.";
    if (status === 429) return "You're going a bit fast — please wait a moment and try again.";
    // 503 is raised deliberately (e.g. ServiceUnavailableException) with a
    // specific, already-safe-to-show message, like "Online payments are
    // temporarily unavailable" - unlike a genuine unhandled 500, there's a
    // real, more helpful detail here and it shouldn't be thrown away.
    if (status === 503) return detail || "This is temporarily unavailable. Please try again shortly.";
    if (status >= 500) return "Something went wrong on our end. Please try again.";
    return detail || "Something went wrong. Please try again.";
  }

  function toFieldErrors(details) {
    if (!details || typeof details !== "object") return null;
    const out = {};
    for (const [k, v] of Object.entries(details)) {
      out[k] = Array.isArray(v) ? v.join(" ") : String(v);
    }
    return Object.keys(out).length ? out : null;
  }

  function redirectToLogin(expired) {
    const next = encodeURIComponent(location.pathname + location.search);
    location.assign(`/login/?next=${next}${expired ? "&expired=1" : ""}`);
  }

  async function request(method, path, opts = {}) {
    const { body, params, silent = false, raw = false } = opts;
    let url = BASE + path;
    if (params) {
      const qs = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") qs.append(k, v);
      });
      const s = qs.toString();
      if (s) url += "?" + s;
    }

    // File uploads (verification photos, the face-scan capture) pass a
    // FormData body - send it as-is with no Content-Type so the browser
    // can set the multipart boundary itself. Everything else stays JSON.
    const isForm = typeof FormData !== "undefined" && body instanceof FormData;

    let res;
    try {
      res = await fetch(url, {
        method,
        credentials: "same-origin",
        headers: isForm
          ? { Accept: "application/json" }
          : body
          ? { "Content-Type": "application/json", Accept: "application/json" }
          : { Accept: "application/json" },
        body: isForm ? body : body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new ApiError(friendly(0), { status: 0, code: "NETWORK" });
    }

    if (res.status === 204) return null;

    let payload = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      try { payload = await res.json(); } catch (_) { payload = null; }
    }

    if (res.ok) {
      if (raw) return payload;
      if (payload && typeof payload === "object" && "data" in payload) {
        let data = payload.data;
        const meta = {};
        for (const k of Object.keys(payload)) {
          if (k !== "data" && k !== "success" && k !== "message") meta[k] = payload[k];
        }
        // Normalise a nested DRF pagination object to a plain array so
        // every list consumer gets the same shape.
        if (data && !Array.isArray(data) && Array.isArray(data.results)) {
          meta.count = data.count;
          meta.next = data.next;
          meta.previous = data.previous;
          data = data.results;
        }
        if (data && typeof data === "object" && Object.keys(meta).length) {
          try {
            Object.defineProperty(data, "_meta", { value: meta, enumerable: false });
          } catch (_) {}
        }
        return data;
      }
      return payload;
    }

    // ---- error path ----
    const err = (payload && payload.error) || {};
    const code = err.code || "";
    // DRF puts a validation error that isn't about one specific field (e.g.
    // "You already have an open requirement...") under `non_field_errors`
    // inside `details`. Callers treat a non-null fieldErrors as "already
    // rendered next to a field" and skip showing anything else, so leaving
    // non_field_errors in there made those errors display nowhere. Pull it
    // out and let it win as the headline message instead.
    const rawDetails = err.details && typeof err.details === "object" ? { ...err.details } : null;
    let nonFieldDetail = "";
    if (rawDetails && "non_field_errors" in rawDetails) {
      const v = rawDetails.non_field_errors;
      nonFieldDetail = Array.isArray(v) ? v.join(" ") : String(v);
      delete rawDetails.non_field_errors;
    }
    const detail = nonFieldDetail || err.message || (payload && payload.detail) || "";
    const fieldErrors = toFieldErrors(rawDetails);

    if (res.status === 401 && !silent) {
      redirectToLogin(true);
      throw new ApiError(friendly(401), { status: 401, code });
    }

    const apiErr = new ApiError(friendly(res.status, code, detail), {
      status: res.status,
      code,
      fieldErrors,
    });

    if (!silent && res.status !== 400 && res.status !== 409) {
      window.dispatchEvent(new CustomEvent("api:error", { detail: apiErr }));
    }
    throw apiErr;
  }

  const api = {
    ApiError,
    get: (p, o) => request("GET", p, o),
    post: (p, body, o) => request("POST", p, { ...o, body }),
    put: (p, body, o) => request("PUT", p, { ...o, body }),
    patch: (p, body, o) => request("PATCH", p, { ...o, body }),
    del: (p, o) => request("DELETE", p, o),

    async login(email, password) {
      return request("POST", "/auth/login/", { body: { email, password }, silent: true });
    },
    async logout(redirect = "/login/") {
      try { await request("POST", "/auth/logout/", { body: {}, silent: true }); } catch (_) {}
      location.assign(redirect);
    },
  };

  window.api = api;
  window.ApiError = ApiError;
})();
