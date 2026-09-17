/* ============================================================
   Udbhab — global UI plumbing: toasts, confirm dialog, formatters
   ============================================================ */
(function () {
  "use strict";

  /* ---------------- Toasts ---------------- */
  const ICONS = {
    success: "i-check-circle",
    error: "i-x-circle",
    warning: "i-alert-triangle",
    info: "i-info",
  };
  const TONE = {
    success: "border-emerald-200 text-emerald-800",
    error: "border-rose-200 text-rose-800",
    warning: "border-amber-200 text-amber-800",
    info: "border-sky-200 text-sky-800",
  };

  window.toast = function (type, message, { timeout = 4500 } = {}) {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const el = document.createElement("div");
    el.className = `toast ${TONE[type] || TONE.info} animate-slide-up`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.innerHTML = `
      <svg class="h-5 w-5" aria-hidden="true"><use href="#${ICONS[type] || ICONS.info}"></use></svg>
      <p class="flex-1 text-sm text-slate-700"></p>
      <button class="btn-ghost btn-sm -m-1.5 p-1.5" aria-label="Dismiss">
        <svg class="h-4 w-4"><use href="#i-x"></use></svg>
      </button>`;
    el.querySelector("p").textContent = message;
    const close = () => {
      el.style.opacity = "0";
      el.style.transform = "translateY(-6px)";
      setTimeout(() => el.remove(), 180);
    };
    el.querySelector("button").addEventListener("click", close);
    region.appendChild(el);
    if (timeout) setTimeout(close, timeout);
  };

  window.addEventListener("api:error", (e) => {
    window.toast("error", e.detail && e.detail.message ? e.detail.message : "Something went wrong.");
  });

  /* ---------------- Confirm dialog ---------------- */
  let _resolver = null;

  window.confirmAction = function (opts = {}) {
    return new Promise((resolve) => {
      _resolver = resolve;
      window.dispatchEvent(new CustomEvent("confirm:open", { detail: opts }));
    });
  };

  document.addEventListener("alpine:init", () => {
    window.Alpine.data("impersonationBar", () => ({
      active: false,
      targetName: "",
      busy: false,
      init() {
        api.get("/auth/me/", { silent: true }).then((d) => {
          if (d && d.impersonated_by) {
            this.active = true;
            this.targetName = (d.user && (d.user.full_name || d.user.email)) || "user";
          }
        }).catch(() => {});
      },
      async stop() {
        if (this.busy) return;
        this.busy = true;
        try {
          const r = await api.post("/auth/stop-impersonation/", {}, { silent: true });
          const home = { student: "/student/", teacher: "/teacher/", admin: "/admin-portal/", superadmin: "/super-admin/" };
          location.assign((r && r.user && home[r.user.role]) || "/super-admin/");
        } catch (e) {
          window.toast("error", e.message || "Couldn't return to your account. Try logging in again.");
          this.busy = false;
        }
      },
    }));

    // Every teacher must rate every lead they unlock — this blocks the rest
    // of the app (no backdrop-close, no Escape) behind a modal listing
    // whatever they still owe a rating on, until nothing is left. Mounted
    // once in base_app.html so it follows a teacher across every page,
    // React SPA routes included (the shell that renders it wraps both).
    window.Alpine.data("pendingReviewGate", () => ({
      pending: [],
      busy: false,
      path: location.pathname,
      get current() { return this.pending[0] || null; },
      // Suppressed only on the exact lead page that lets them resolve it —
      // everywhere else (including the leads list) it still nags them.
      get suppressed() {
        return !!this.current && this.path === "/teacher/leads/" + this.current.id + "/";
      },
      init() {
        this.refresh();
        setInterval(() => this.refresh(), 60000);
        setInterval(() => { this.path = location.pathname; }, 1000);
        window.addEventListener("focus", () => this.refresh());
      },
      async refresh() {
        try {
          const d = await api.get("/leads/pending-ratings/", { silent: true });
          // api.get() already normalises {count, results} down to the bare
          // results array (see static/js/api.js) - this used to read
          // d.results on that ALREADY-unwrapped array (always undefined),
          // so `pending` silently stayed empty and this gate never once
          // blocked anyone despite being "mandatory". Handle both shapes
          // defensively rather than assuming the client's current
          // normalisation behaviour forever.
          this.pending = Array.isArray(d) ? d : (d && d.results) || [];
        } catch (_) {}
      },
      async rate(verdict) {
        if (this.busy || !this.current) return;
        this.busy = true;
        try {
          await api.post(`/leads/${this.current.id}/rate/`, { verdict });
          this.pending = this.pending.slice(1);
          window.toast("success", "Thanks — that helps keep fake leads out.");
          try { window.Alpine.store("badges").refresh(); } catch (_) {}
        } catch (e) {
          window.toast("error", e.message || "Couldn't save that.");
        } finally {
          this.busy = false;
        }
      },
    }));

    window.Alpine.data("confirmDialog", () => ({
      open: false,
      title: "",
      message: "",
      confirmLabel: "Confirm",
      cancelLabel: "Cancel",
      danger: false,
      init() {
        window.addEventListener("confirm:open", (e) => {
          const o = e.detail || {};
          this.title = o.title || "Are you sure?";
          this.message = o.message || "";
          this.confirmLabel = o.confirmLabel || "Confirm";
          this.cancelLabel = o.cancelLabel || "Cancel";
          this.danger = !!o.danger;
          this.open = true;
        });
      },
      accept() { this.open = false; if (_resolver) _resolver(true); _resolver = null; },
      cancel() { this.open = false; if (_resolver) _resolver(false); _resolver = null; },
    }));
  });

  /* ---------------- Formatters ---------------- */
  const INR = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
  window.fmt = {
    money(v) {
      if (v === null || v === undefined || v === "") return "—";
      const n = Number(v);
      return Number.isFinite(n) ? INR.format(n) : "—";
    },
    // "₹600 – ₹1,000" when there's a real range, else a single "₹600" —
    // most teachers' fees genuinely vary by class size/level.
    moneyRange(min, max) {
      const lo = this.money(min);
      const hi = this.money(max);
      if (lo !== "—" && hi !== "—" && hi !== lo) return `${lo} – ${hi}`;
      return lo !== "—" ? lo : hi;
    },
    number(v) {
      const n = Number(v);
      return Number.isFinite(n) ? n.toLocaleString("en-IN") : "—";
    },
    date(v, opts) {
      if (!v) return "—";
      const d = new Date(v);
      if (isNaN(d)) return "—";
      return d.toLocaleDateString("en-IN", opts || { day: "numeric", month: "short", year: "numeric" });
    },
    dateTime(v) {
      if (!v) return "—";
      const d = new Date(v);
      if (isNaN(d)) return "—";
      return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
    },
    relative(v) {
      if (!v) return "";
      const d = new Date(v);
      const s = (Date.now() - d.getTime()) / 1000;
      if (s < 60) return "just now";
      if (s < 3600) return `${Math.floor(s / 60)}m ago`;
      if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
      if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
      return window.fmt.date(v);
    },
    titleCase(v) {
      return String(v || "").replace(/(^|[\s_-])(\w)/g, (_, p, c) => (p === "_" || p === "-" ? " " : p) + c.toUpperCase()).trim();
    },
    stars(rating) {
      // 5-length array of booleans (filled/empty), rounded to the nearest
      // whole star - a purely visual readout of an existing rating value.
      const n = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
      return Array.from({ length: 5 }, (_, i) => i < n);
    },
    initials(name) {
      const parts = String(name || "").split(/\s+/).filter(Boolean);
      if (!parts.length) return "?";
      if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    },
    list(arr, key = "name", limit) {
      const a = (arr || []).map((x) => (key ? x[key] : x)).filter(Boolean);
      const shown = limit ? a.slice(0, limit) : a;
      return shown.join(", ") + (limit && a.length > limit ? ` +${a.length - limit}` : "");
    },
    weekday(n) {
      return ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][Number(n)] || "—";
    },
    time(t) {
      if (!t) return "—";
      const [h, m] = String(t).split(":");
      const hr = ((+h % 12) || 12);
      return `${hr}:${m} ${+h < 12 ? "AM" : "PM"}`;
    },
  };

  /* ---------------- Small helpers ---------------- */
  window.debounce = function (fn, wait = 300) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  };
})();
