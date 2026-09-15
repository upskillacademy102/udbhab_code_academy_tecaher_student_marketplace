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
        this._go(data && data.user);
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

    _go(user) {
      const role = user ? user.role : null;
      let dest = ROLE_HOME[role] || "/";
      if (this.nextUrl && this.nextUrl.startsWith("/") && !this.nextUrl.startsWith("//")) {
        // only honour `next` when it's inside this user's area
        if (dest === "/" || this.nextUrl.startsWith(dest) || role === "superadmin") dest = this.nextUrl;
      }

      // Dual-role: the portal page they logged in through (?as=) may not
      // match their currently-active role. Rather than silently sending
      // them wherever `role` says (the old behaviour), honour what they
      // asked for — switch straight there if they already have that
      // portal, or offer to set it up if they don't.
      if (this.portal && role && this.portal !== role && (this.portal === "student" || this.portal === "teacher")) {
        const hasPortal = this.portal === "teacher" ? !!(user && user.has_teacher_profile) : !!(user && user.has_student_profile);
        if (hasPortal) {
          this.notice = `Switching you to the ${this.portal} area.`;
          api.post("/auth/switch-role/", { role: this.portal }, { silent: true })
            .then(() => location.assign(ROLE_HOME[this.portal]))
            .catch(() => location.assign(dest));
          return;
        }
        location.assign(`/add-role/?as=${this.portal}`);
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

  // Shown instead of LEVELS when the chosen subject is skill-based (an
  // instrument, a martial art, ...) — "Class 1–5" doesn't mean anything
  // to a 40-year-old learning guitar, but their skill level does.
  const SKILL_LEVELS = ["Novice", "Intermediate", "Expert"];

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

  /*
   * NOTE: defineProperties + getOwnPropertyDescriptors, NOT Object.assign.
   *
   * Object.assign READS every source property, which means it *invokes* any
   * getter and copies the returned value as a plain data property. Every
   * computed below (steps, step, canGoBack, carriedOver, pwRules) would be
   * frozen at its value from definition time — `step` would be the literal
   * string "role" forever, so clicking a role button set the state but never
   * changed the visible step, and the page appeared dead.
   *
   * Copying descriptors keeps getters as getters, which is what Alpine's
   * reactivity needs.
   */
  window.Alpine.data("registerFlow", (portal, nextUrl, tax) =>
    Object.defineProperties(
      // subject / language selection, adaptive picker and combobox
      window.taxonomyMixin(tax || {}),
      Object.getOwnPropertyDescriptors({
        LEVELS, SKILL_LEVELS, DAYS, BANDS,
        SKILL_SUBJECTS: Array.isArray(tax && tax.skillSubjects) ? tax.skillSubjects : [],

        // Whether the chosen subject is learned as a skill (an instrument,
        // a martial art, ...) rather than an academic grade — decides
        // which set the "What level?" step offers.
        get isSkillSubject() {
          return !!this.resolvedSubject && this.SKILL_SUBJECTS.indexOf(this.resolvedSubject) !== -1;
        },
        get levelOptions() {
          return this.isSkillSubject ? SKILL_LEVELS : LEVELS;
        },

        role: portal === "student" || portal === "teacher" ? portal : "",
        nextUrl: nextUrl || "",
        stepIndex: 0,
        prefilled: [],
        minIndex: 0,

        // captured intent — subject / subjectCustom / language come from
        // the mixin, which also owns the picker behaviour
        level: null,
        days: [],
        band: "evening",
        // Teachers pick MULTIPLE languages, in order of how well they teach
        // in them. Order is the data: it is what the first language in the
        // list means. Kept as an ordered array of names, resolved to ids
        // after sign-in (the taxonomy endpoints are unreachable logged out).
        teachLanguages: [],

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

          // Land on the first step the landing page did NOT answer, and
          // remember it as the floor so Back can never walk into a question
          // the visitor has already answered.
          this.stepIndex = this._skipForward(-1);
          this.minIndex = this.stepIndex;
        },

        /* Index of the next step at or after `from` that still needs an
           answer. Never runs past the account step, which is always shown. */
        _skipForward(from) {
          const last = this.steps.length - 1;
          let i = from + 1;
          while (i < last && this.prefilled.indexOf(this.steps[i]) !== -1) i++;
          return Math.min(i, last);
        },

        /* ---- step machinery ---- */
        get steps() {
          if (!this.role) return ["role"];
          if (this.role === "teacher") {
            return ["role", "teaches", "teach-languages", "teach-hours", "account"];
          }
          return ["role", "subject", "language", "level", "when", "account"];
        },
        get step() { return this.steps[this.stepIndex] || "role"; },
        // the role fork is a branch, not progress
        get progressSteps() { return this.steps.slice(1); },

        pickRole(r) {
          this.role = r;
          this.stepIndex = 1;
        },

        // Forward and back both step OVER anything the landing page already
        // answered. Without this a visitor who picked their free hours on the
        // home page gets asked for them a second time here.
        next() {
          // A level picked for one subject category (e.g. "Novice" for
          // guitar) is meaningless for the other (e.g. an academic grade
          // for Mathematics) — drop it if the subject changed category
          // since it was picked, rather than silently submitting a
          // mismatched value.
          if (this.step === "subject" && this.level && this.levelOptions.indexOf(this.level) === -1) {
            this.level = null;
          }
          this.stepIndex = this._skipForward(this.stepIndex);
        },
        back() {
          let i = this.stepIndex - 1;
          while (i > this.minIndex && this.prefilled.indexOf(this.steps[i]) !== -1) i--;
          this.stepIndex = Math.max(i, this.minIndex);
          this.formError = "";
          this.emailTaken = false;
          this.cbClose();
        },
        get canGoBack() { return this.stepIndex > this.minIndex; },

        /* Jump straight to a step — used by the "carried over" summary so an
           answer brought from the home page can still be changed. */
        goToStep(id) {
          const i = this.steps.indexOf(id);
          if (i >= 0) this.stepIndex = i;
        },

        /* What the landing page answered, for the summary at the top of the
           first step. Showing it is the point: an answer that silently
           disappears feels lost even when it was kept. */
        get carriedOver() {
          const out = [];
          const has = (k) => this.prefilled.indexOf(k) !== -1;
          if (has("subject") && this.resolvedSubject) {
            out.push({ step: "subject", value: this.resolvedSubject, icon: "book" });
          }
          if (has("language") && this.resolvedLanguage) {
            out.push({ step: "language", value: this.resolvedLanguage, icon: "globe" });
          }
          if (has("when") && this.days.length) {
            out.push({ step: "when", value: this.scheduleSummary(), icon: "clock" });
          }
          return out;
        },
        // "when" is genuinely optional — but skipping it costs the match
        // score, and the copy says so rather than hiding it.
        skip() { this.next(); },

        toggleDay(n) {
          const i = this.days.indexOf(n);
          if (i === -1) this.days.push(n); else this.days.splice(i, 1);
          this.days.sort((a, b) => a - b);
        },

        /* ---- languages a teacher teaches in, best first ---- */
        toggleTeachLanguage(name) {
          const i = this.teachLanguages.indexOf(name);
          if (i === -1) this.teachLanguages.push(name);
          else this.teachLanguages.splice(i, 1);
        },
        // Order carries meaning here, so it has to be adjustable. Arrows
        // rather than drag-and-drop: this is used on a phone, and dragging a
        // list item on a touchscreen fights the page scroll.
        moveTeachLanguage(i, dir) {
          const j = i + dir;
          if (j < 0 || j >= this.teachLanguages.length) return;
          const arr = this.teachLanguages;
          [arr[i], arr[j]] = [arr[j], arr[i]];
        },
        teachLanguageRank(name) {
          return this.teachLanguages.indexOf(name) + 1;
        },

        // "Monday mornings", "Tuesday & Thursday evenings", "most evenings" —
        // the day stays singular and the part of day takes the plural, which
        // is how people actually say it.
        scheduleSummary() {
          if (!this.days.length) return "";
          const names = this.days.map((n) => (DAYS.find((d) => d.n === n) || {}).full).filter(Boolean);
          const band = ((BANDS.find((b) => b.id === this.band) || {}).label || "").toLowerCase();
          if (names.length >= 5) return "most " + band + "s";
          let dayText;
          if (names.length === 1) dayText = names[0];
          else if (names.length === 2) dayText = names[0] + " & " + names[1];
          else dayText = names.slice(0, -1).join(", ") + " & " + names[names.length - 1];
          return dayText + " " + band + "s";
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
              // Students pick one language; teachers pick several, ranked.
              language: this.resolvedLanguage,
              teachLanguages: this.teachLanguages,
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
      })
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
