/**
 * The one place the SPA talks to the DRF API.
 *
 * A faithful port of static/js/api.js — same envelope unwrapping, same
 * friendly error messages, same 401 -> /login redirect. Auth still travels on
 * the httpOnly `access` cookie over a same-origin fetch, so there is no token
 * handling here and nothing about the auth model changes by moving to React.
 */

const BASE = (window as { API_BASE_URL?: string }).API_BASE_URL?.replace(/\/$/, "") ?? "/api/v1";

export type FieldErrors = Record<string, string>;

export class ApiError extends Error {
  status: number;
  code: string;
  fieldErrors: FieldErrors | null;

  constructor(
    message: string,
    opts: { status?: number; code?: string; fieldErrors?: FieldErrors | null } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = opts.status ?? 0;
    this.code = opts.code ?? "";
    this.fieldErrors = opts.fieldErrors ?? null;
  }
}

function friendly(status: number, code = "", detail = ""): string {
  if (status === 0) return "We couldn't reach the server. Check your connection and try again.";
  if (code === "CAPTCHA_REQUIRED") return "Please complete the verification challenge and try again.";
  if (status === 401) return "Your session has expired. Please log in again.";
  if (status === 403) return "You don't have permission to do that.";
  if (status === 404) return detail || "We couldn't find what you were looking for.";
  if (status === 409) return detail || "That action conflicts with the current state.";
  if (status === 429) return "You're going a bit fast — please wait a moment and try again.";
  if (status >= 500) return "Something went wrong on our end. Please try again.";
  return detail || "Something went wrong. Please try again.";
}

function toFieldErrors(details: unknown): FieldErrors | null {
  if (!details || typeof details !== "object") return null;
  const out: FieldErrors = {};
  for (const [k, v] of Object.entries(details as Record<string, unknown>)) {
    out[k] = Array.isArray(v) ? v.join(" ") : String(v);
  }
  return Object.keys(out).length ? out : null;
}

function redirectToLogin(expired: boolean) {
  const next = encodeURIComponent(location.pathname + location.search);
  location.assign(`/login/?next=${next}${expired ? "&expired=1" : ""}`);
}

/** Paging info the DRF envelope carries alongside a list. */
export interface Meta {
  count?: number;
  next?: string | null;
  previous?: string | null;
  [k: string]: unknown;
}

export interface RequestOptions {
  body?: unknown;
  params?: Record<string, string | number | null | undefined>;
  /** Don't redirect on 401 / don't broadcast the error. */
  silent?: boolean;
  /** Return the raw envelope instead of unwrapping `data`. */
  raw?: boolean;
  signal?: AbortSignal;
}

export interface ListResult<T> {
  items: T[];
  meta: Meta;
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const { body, params, silent = false, raw = false, signal } = opts;

  let url = BASE + path;
  if (params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.append(k, String(v));
    }
    const s = qs.toString();
    if (s) url += "?" + s;
  }

  const isForm = typeof FormData !== "undefined" && body instanceof FormData;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: "same-origin",
      signal,
      headers: isForm
        ? { Accept: "application/json" }
        : body
          ? { "Content-Type": "application/json", Accept: "application/json" }
          : { Accept: "application/json" },
      body: isForm ? (body as FormData) : body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(friendly(0), { status: 0, code: "NETWORK" });
  }

  if (res.status === 204) return null as T;

  let payload: unknown = null;
  if ((res.headers.get("content-type") ?? "").includes("application/json")) {
    try {
      payload = await res.json();
    } catch {
      payload = null;
    }
  }

  if (res.ok) {
    if (raw) return payload as T;
    if (payload && typeof payload === "object" && "data" in payload) {
      return (payload as { data: T }).data;
    }
    return payload as T;
  }

  const err = ((payload as { error?: Record<string, unknown> })?.error ?? {}) as Record<string, unknown>;
  const code = (err.code as string) ?? "";
  const detail = (err.message as string) ?? ((payload as { detail?: string })?.detail ?? "");
  const fieldErrors = toFieldErrors(err.details);

  if (res.status === 401 && !silent) {
    redirectToLogin(true);
    throw new ApiError(friendly(401), { status: 401, code });
  }

  throw new ApiError(friendly(res.status, code, detail), {
    status: res.status,
    code,
    fieldErrors,
  });
}

/**
 * List endpoints come back either as a bare array or as a nested DRF
 * pagination object. api.js flattened both to an array and hid the paging on a
 * non-enumerable property; here it is an explicit `{ items, meta }` so callers
 * can't forget it exists.
 */
async function list<T>(path: string, opts: RequestOptions = {}): Promise<ListResult<T>> {
  const payload = await request<unknown>("GET", path, { ...opts, raw: true });
  const envelope = (payload ?? {}) as Record<string, unknown>;
  const data = "data" in envelope ? envelope.data : envelope;

  const meta: Meta = {};
  for (const k of Object.keys(envelope)) {
    if (k !== "data" && k !== "success" && k !== "message") meta[k] = envelope[k];
  }

  if (Array.isArray(data)) return { items: data as T[], meta };

  if (data && typeof data === "object" && Array.isArray((data as { results?: unknown }).results)) {
    const d = data as { results: T[]; count?: number; next?: string | null; previous?: string | null };
    return { items: d.results, meta: { ...meta, count: d.count, next: d.next, previous: d.previous } };
  }

  return { items: [], meta };
}

export const api = {
  get: <T>(p: string, o?: RequestOptions) => request<T>("GET", p, o),
  list,
  post: <T>(p: string, body?: unknown, o?: RequestOptions) => request<T>("POST", p, { ...o, body }),
  put: <T>(p: string, body?: unknown, o?: RequestOptions) => request<T>("PUT", p, { ...o, body }),
  patch: <T>(p: string, body?: unknown, o?: RequestOptions) => request<T>("PATCH", p, { ...o, body }),
  del: <T>(p: string, o?: RequestOptions) => request<T>("DELETE", p, o),

  async logout(redirect = "/login/") {
    try {
      await request("POST", "/auth/logout/", { body: {}, silent: true });
    } catch {
      /* logging out locally matters more than the server agreeing */
    }
    location.assign(redirect);
  },
};
