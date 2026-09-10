/* ============================================================
   Auth screens: login, registration, staff sign-in.
   ============================================================ */
document.addEventListener("alpine:init", () => {
  const ROLE_HOME = {
    student: "/student/",
    teacher: "/teacher/",
    admin: "/admin-portal/",
    superadmin: "/super-admin/",
  };

  /* Where the pre-signup answers are parked between "create account" and the
     first authenticated page load. localStorage (not sessionStorage) because
     registration redirects through /login/, which the user may open in a new
     tab. Stage B's Discover page reads this key, replays it into
     PATCH /students/me/ + POST /student-requirements/, then clears it. */
  const INTENT_KEY = "udbhab:intent";
  const INTENT_TTL_MS = 24 * 60 * 60 * 1000;

  function saveIntent(intent) {
    try {
      localStorage.setItem(INTENT_KEY, JSON.stringify({ ...intent, savedAt: Date.now() }));
    } catch (_) {
      /* private mode / storage disabled — the flow still completes, the
         student just starts on an unfiltered Discover page. */
    }
  }

  window.readIntent = function readIntent() {
    try {
      const raw = localStorage.getItem(INTENT_KEY);
      if (!raw) return null;
      const v = JSON.parse(raw);
      if (!v || !v.savedAt || Date.now() - v.savedAt > INTENT_TTL_MS) {
        localStorage.removeItem(INTENT_KEY);
        return null;
      }
      return v;
    } catch (_) {
      return null;
    }
  };

  window.clearIntent = function clearIntent() {
    try { localStorage.removeItem(INTENT_KEY); } catch (_) {}
  };

  /* ---- Login ---- */
  window.Alpine.data("loginForm", (portal, nextUrl, prefillEmail, justRegistered) => ({
    portal: portal || "",
    nextUrl: nextUrl || "",
    email: prefillEmail || "",
    password: "",
    showPw: false,
    submitting: false,
    error: "",
    conflict: false,
    notice: justRegistered ? "Your account is ready. Log in to pick up where you left off." : "",

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

  /* ============================================================
     Registration — intent first, credentials last.

     Asks what the person actually wants BEFORE asking them to work for it
     (goal-gradient + endowed progress), and the answers are not decorative:
     subject, language and free hours are exactly the inputs
     GET /search/teachers/ needs to return a scored match, so the first
     screen after signup can show real results instead of an empty state.

     Student:  role -> subject -> language -> level -> when -> account
     Teacher:  role -> teaches -> account
       (a teacher's languages belong on the teaching profile, where they
        are edited alongside subjects and availability — putting them in
        signup would front-load a form that already exists downstream)

     Any step the URL already answered is skipped, so someone arriving from
     the landing hero has three of five done and sees only level + account.

     No backend change. Subject and language travel as free text because
     /api/v1/subjects/ and /api/v1/languages/ are _ANY_AUTHED and
     unreachable while logged out — and text is what
     SubjectMatchingService / LanguageMatchingService want anyway.
     ============================================================ */
  const NAME_RE = /^[A-Za-z][A-Za-z\s'-]*$/;
  const MOBILE_RE = /^[0-9]{10,15}$/;
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  const LEVELS = [
    "Class 1–5", "Class 6–8", "Class 9–10", "Class 11–12",
    "Undergraduate", "Postgraduate", "Competitive exam", "Adult learner",
  ];

  const DAYS = [
    { n: 1, s: "M", full: "Monday" },
    { n: 2, s: "T", full: "Tuesday" },
    { n: 3, s: "W", full: "Wednesday" },
    { n: 4, s: "T", full: "Thursday" },
    { n: 5, s: "F", full: "Friday" },
    { n: 6, s: "S", full: "Saturday" },
    { n: 7, s: "S", full: "Sunday" },
  ];

  const BANDS = [
    { id: "morning", label: "Morning", hint: "6–12", from: "06:00", to: "12:00" },
    { id: "afternoon", label: "Afternoon", hint: "12–5", from: "12:00", to: "17:00" },
    { id: "evening", label: "Evening", hint: "5–10", from: "17:00", to: "22:00" },
  ];

  window.Alpine.data("registerFlow", (portal, nextUrl, tax) =>
    Object.assign(
      // subject / language selection, adaptive picker and combobox
      window.taxonomyMixin(tax || {}),
      {
        LEVELS, DAYS, BANDS,

        role: portal === "student" || portal === "teacher" ? portal : "",
        nextUrl: nextUrl || "",
        stepIndex: 0,
        prefilled: [],

        // captured intent — subject / subjectCustom / language come from
        // the mixin, which also owns the picker behaviour
        level: null,
        days: [],
        band: "evening",

        // account form
        showPw: false,
        submitting: false,
        formError: "",
        emailTaken: false,
        touched: {},
        server: {},
        model: { first_name: "", last_name: "", email: "", mobile: "", password: "", password_confirm: "" },

        init() {
          // Carry over whatever the visitor already chose on the landing
          // page, so nobody is asked the same question twice.
          const q = new URLSearchParams(location.search);
          const done = [];

          if (this.role) done.push("role");

          const subject = q.get("subject");
          if (subject) {
            if (this.SUBJECTS.indexOf(subject) !== -1) this.subject = subject;
            else { this.subject = "__other"; this.subjectCustom = subject.slice(0, 60); }
            done.push("subject", "teaches");
          }

          const language = q.get("language");
          if (language) {
            this.language = language.slice(0, 60);
            done.push("language");
          }

          const days = q.get("days");
          if (days) {
            this.days = days.split(",").map(Number).filter((n) => n >= 1 && n <= 7);
            if (this.days.length) done.push("when");
          }
          const match = BANDS.find((b) => b.from === q.get("from"));
          if (match) this.band = match.id;

          this.prefilled = done;

          // Skip past any leading step the URL already answered. Only
          // URL-answered steps are skipped — a step with a sensible
          // default (language) is still shown, because a default is not
          // the same as an answer.
          while (
            this.stepIndex < this.steps.length - 1 &&
            this.prefilled.indexOf(this.steps[this.stepIndex]) !== -1
          ) {
            this.stepIndex++;
          }
        },

        /* ---- step machinery ---- */
        get steps() {
          if (!this.role) return ["role"];
          if (this.role === "teacher") return ["role", "teaches", "account"];
          return ["role", "subject", "language", "level", "when", "account"];
        },
        get step() { return this.steps[this.stepIndex] || "role"; },
        // the role fork is a branch, not progress
        get progressSteps() { return this.steps.slice(1); },

        pickRole(r) {
          this.role = r;
          this.stepIndex = 1;
        },

        next() { if (this.stepIndex < this.steps.length - 1) this.stepIndex++; },
        back() {
          if (this.stepIndex > 0) this.stepIndex--;
          this.formError = "";
          this.emailTaken = false;
          this.cbClose();
        },
        // "when" is genuinely optional — but skipping it costs the match
        // score, and the copy says so rather than hiding it.
        skip() { this.next(); },

        toggleDay(n) {
          const i = this.days.indexOf(n);
          if (i === -1) this.days.push(n); else this.days.splice(i, 1);
          this.days.sort((a, b) => a - b);
        },

        scheduleSummary() {
          if (!this.days.length) return "";
          const names = this.days.map((n) => (DAYS.find((d) => d.n === n) || {}).full).filter(Boolean);
          const band = (BANDS.find((b) => b.id === this.band) || {}).label || "";
          let dayText;
          if (names.length === 1) dayText = names[0] + "s";
          else if (names.length === 2) dayText = names[0] + "s & " + names[1] + "s";
          else if (names.length <= 4) dayText = names.slice(0, -1).map((d) => d + "s").join(", ") + " & " + names[names.length - 1] + "s";
          else dayText = names.length + " days a week";
          return dayText + " " + band.toLowerCase() + "s";
        },

        /* ---- account form validation ---- */
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

        loginHref(email) {
          const q = new URLSearchParams();
          if (this.role) q.set("as", this.role);
          if (email) q.set("email", email);
          if (this.nextUrl) q.set("next", this.nextUrl);
          const s = q.toString();
          return "/login/" + (s ? "?" + s : "");
        },

        async submit() {
          if (this.submitting) return;
          this.formError = "";
          this.emailTaken = false;
          if (!this._valid()) return;
          this.submitting = true;
          try {
            await api.post("/auth/register/", { ...this.model, role: this.role }, { silent: true });

            const band = BANDS.find((b) => b.id === this.band);
            saveIntent({
              role: this.role,
              subject: this.resolvedSubject,
              language: this.resolvedLanguage,
              level: this.level,
              days: this.days,
              from: this.days.length && band ? band.from : null,
              to: this.days.length && band ? band.to : null,
            });

            const q = new URLSearchParams({ as: this.role, registered: "1", email: this.model.email });
            if (this.nextUrl) q.set("next", this.nextUrl);
            location.assign("/login/?" + q.toString());
          } catch (e) {
            const fe = e.fieldErrors || {};
            if (fe.email && /exist/i.test(fe.email)) {
              this.emailTaken = true;
            } else if (Object.keys(fe).length) {
              this.server = fe;
              // Server-side field errors always belong to the account step.
              this.stepIndex = this.steps.length - 1;
            } else {
              this.formError = e.message || "We couldn't create your account. Please try again.";
            }
          } finally {
            this.submitting = false;
          }
        },
      }
    )
  );

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
