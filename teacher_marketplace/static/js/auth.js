/* Login form logic. Routes by the account's real role after auth. */
document.addEventListener("alpine:init", () => {
  const ROLE_HOME = {
    student: "/student/",
    teacher: "/teacher/",
    admin: "/admin-portal/",
    superadmin: "/super-admin/",
  };

  window.Alpine.data("loginForm", (portal, nextUrl, prefillEmail, justRegistered) => ({
    portal: portal || "",
    nextUrl: nextUrl || "",
    email: prefillEmail || "",
    password: "",
    showPw: false,
    submitting: false,
    error: "",
    conflict: false,
    notice: justRegistered ? "Your account is ready. Log in to continue." : "",

    async doLogin() {
      if (this.submitting) return;
      this.submitting = true;
      this.error = "";
      this.notice = "";
      this.conflict = false;
      try {
        const data = await api.login(this.email.trim(), this.password);
        this._go(data && data.user ? data.user.role : null);
      } catch (e) {
        if (e.status === 409) {
          this.conflict = true;
          this.error = e.message;
        } else if (e.status === 401 || e.status === 400) {
          this.error = "The email or password you entered is incorrect.";
        } else {
          this.error = e.message || "We couldn't sign you in. Please try again.";
        }
      } finally {
        this.submitting = false;
      }
    },

    async logoutAndRetry() {
      this.submitting = true;
      try { await api.post("/auth/logout/", {}, { silent: true }); } catch (_) {}
      this.conflict = false;
      this.error = "";
      await this.doLogin();
    },

    _go(role) {
      let dest = ROLE_HOME[role] || "/";
      if (this.nextUrl && this.nextUrl.startsWith("/") && !this.nextUrl.startsWith("//")) {
        // only honour `next` when it's inside this user's area
        if (dest === "/" || this.nextUrl.startsWith(dest) || role === "superadmin") dest = this.nextUrl;
      }
      if (this.portal && role && this.portal !== role && (role === "student" || role === "teacher")) {
        this.notice = `Signing you in to the ${role} area.`;
        setTimeout(() => location.assign(dest), 650);
        return;
      }
      location.assign(dest);
    },
  }));

  /* ---- Registration (Student / Teacher only) ---- */
  const NAME_RE = /^[A-Za-z][A-Za-z\s'-]*$/;
  const MOBILE_RE = /^[0-9]{10,15}$/;
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  window.Alpine.data("registerForm", (portal, nextUrl) => ({
    step: portal === "student" || portal === "teacher" ? "form" : "role",
    role: portal === "student" || portal === "teacher" ? portal : "",
    nextUrl: nextUrl || "",
    showPw: false,
    submitting: false,
    formError: "",
    emailTaken: false,
    touched: {},
    server: {},
    model: { first_name: "", last_name: "", email: "", mobile: "", password: "", password_confirm: "" },

    get pwRules() {
      const p = this.model.password || "";
      return [
        { key: "len", label: "At least 8 characters", ok: p.length >= 8 },
        { key: "upper", label: "One uppercase letter", ok: /[A-Z]/.test(p) },
        { key: "lower", label: "One lowercase letter", ok: /[a-z]/.test(p) },
        { key: "digit", label: "One number", ok: /\d/.test(p) },
        { key: "special", label: "One special character", ok: /[!@#$%^&*()\-_=+[\]{};:'",.<>/?\\|`~]/.test(p) },
      ];
    },

    pickRole(r) { this.role = r; this.step = "form"; },
    back() {
      if (portal === "student" || portal === "teacher") { location.assign("/register/" + this._qs()); return; }
      this.step = "role"; this.formError = ""; this.emailTaken = false;
    },
    _qs() {
      const q = new URLSearchParams();
      if (this.nextUrl) q.set("next", this.nextUrl);
      const s = q.toString();
      return s ? "?" + s : "";
    },
    loginHref(email) {
      const q = new URLSearchParams();
      if (this.role) q.set("as", this.role);
      if (email) q.set("email", email);
      if (this.nextUrl) q.set("next", this.nextUrl);
      const s = q.toString();
      return "/login/" + (s ? "?" + s : "");
    },

    touch(f) { this.touched[f] = true; delete this.server[f]; },
    useAnotherEmail() {
      this.emailTaken = false; this.model.email = ""; delete this.server.email;
      this.$nextTick(() => document.getElementById("rg-email")?.focus());
    },

    _clientError(f) {
      const m = this.model;
      switch (f) {
        case "first_name":
        case "last_name":
          if (!m[f]) return "Required.";
          return NAME_RE.test(m[f]) ? "" : "Letters only.";
        case "email":
          if (!m.email) return "Required.";
          return EMAIL_RE.test(m.email) ? "" : "Enter a valid email address.";
        case "mobile":
          if (!m.mobile) return "Required.";
          return MOBILE_RE.test(m.mobile) ? "" : "10–15 digits, numbers only.";
        case "password":
          if (!m.password) return "Required.";
          return this.pwRules.every((r) => r.ok) ? "" : "Password doesn't meet the requirements above.";
        case "password_confirm":
          if (!m.password_confirm) return "Required.";
          return m.password_confirm === m.password ? "" : "Passwords do not match.";
        default:
          return "";
      }
    },
    err(f) {
      if (this.server[f]) return this.server[f];
      if (!this.touched[f]) return "";
      return this._clientError(f);
    },
    _valid() {
      return ["first_name", "last_name", "email", "mobile", "password", "password_confirm"]
        .every((f) => { this.touched[f] = true; return !this._clientError(f); });
    },

    async submit() {
      if (this.submitting) return;
      this.formError = "";
      this.emailTaken = false;
      if (!this._valid()) return;
      this.submitting = true;
      try {
        await api.post("/auth/register/", { ...this.model, role: this.role }, { silent: true });
        const q = new URLSearchParams({ as: this.role, registered: "1", email: this.model.email });
        if (this.nextUrl) q.set("next", this.nextUrl);
        location.assign("/login/?" + q.toString());
      } catch (e) {
        const fe = e.fieldErrors || {};
        if (fe.email && /exist/i.test(fe.email)) {
          this.emailTaken = true;
        } else if (Object.keys(fe).length) {
          this.server = fe;
        } else {
          this.formError = e.message || "We couldn't create your account. Please try again.";
        }
      } finally {
        this.submitting = false;
      }
    },
  }));

  /* ---- Staff sign-in: Super Admin direct, Admin -> approval flow ---- */
  window.Alpine.data("staffLogin", () => ({
    email: "",
    password: "",
    showPw: false,
    phase: "form", // form | waiting | denied
    error: "",
    submitting: false,
    _poll: null,
    _req: null,
    elapsed: 0,

    async submit() {
      if (this.submitting) return;
      this.submitting = true;
      this.error = "";
      try {
        const r = await api.post("/auth/admin/login/", { email: this.email.trim(), password: this.password }, { silent: true });
        // r is the unwrapped `data`. Direct sign-in returns tokens+user.
        if (r && r.user) {
          location.assign(ROLE_HOME[r.user.role] || "/admin-portal/");
          return;
        }
        // pending approval
        this._req = r;
        this.phase = "waiting";
        this._startPolling();
      } catch (e) {
        this.error = e.status === 400 || e.status === 401
          ? "Incorrect email or password."
          : (e.message || "Sign-in failed. Please try again.");
      } finally {
        this.submitting = false;
      }
    },

    _startPolling() {
      this.elapsed = 0;
      const tick = async () => {
        this.elapsed += 3;
        try {
          const s = await api.get(`/auth/admin/login/${this._req.request_id}/status/`, {
            params: { token: this._req.poll_token }, silent: true,
          });
          if (s && s.user) { this._stop(); location.assign(ROLE_HOME[s.user.role] || "/admin-portal/"); return; }
          if (s && s.status === "denied") { this._stop(); this.phase = "denied"; return; }
          if (s && s.status === "expired") { this._stop(); this.phase = "form"; this.error = "Your request expired. Please try again."; return; }
        } catch (e) { /* keep polling */ }
      };
      this._poll = setInterval(tick, 3000);
    },
    _stop() { if (this._poll) { clearInterval(this._poll); this._poll = null; } },
    cancel() { this._stop(); this.phase = "form"; this.password = ""; this._req = null; },
    destroy() { this._stop(); },
  }));
});
