/* ============================================================
   Udbhab — reusable data-page building blocks.
   Exposed as window.mk.{collection,record,apiForm} factory
   functions so page components can spread & extend them:

     Alpine.data("teacherSearch", () => ({
       ...mk.collection({ endpoint: "/search/teachers/" }),
       extraThing: 1,
     }));

   Also registered directly as Alpine.data("collection" | "record" |
   "apiForm") for the no-extension case.
   ============================================================ */
(function () {
  "use strict";

  function collection(cfg) {
    return {
      _endpoint: cfg.endpoint,
      params: cfg.params ? { ...cfg.params } : {},
      _baseParams: cfg.params ? { ...cfg.params } : {},
      items: [],
      meta: {},
      page: 1,
      state: "loading",
      errorMsg: "",
      _seq: 0,
      _cfg: cfg,

      // NOTE: methods (not getters) so this object survives {...spread}
      initCollection() {
        this.load();
        this.$watch("params", window.debounce(() => { this.page = 1; this.load(); }, 350));
      },
      init() { this.initCollection(); },

      pageSize() { return this._cfg.pageSize || 20; },
      totalPages() { return Math.max(1, Math.ceil((this.meta.count || this.items.length || 0) / this.pageSize())); },
      hasNext() { return !!this.meta.next; },
      hasPrev() { return this.page > 1; },
      rangeLabel() {
        const total = this.meta.count;
        if (!total) return "";
        const from = (this.page - 1) * this.pageSize() + 1;
        const to = Math.min(this.page * this.pageSize(), total);
        return `${from}–${to} of ${total}`;
      },

      async load() {
        const seq = ++this._seq;
        this.state = "loading";
        this.notFound = false;
        try {
          const data = await api.get(this._endpoint, { params: { ...this.params, page: this.page } });
          if (seq !== this._seq) return;
          let list, meta;
          if (Array.isArray(data)) {
            list = data;
            meta = data._meta ? { ...data._meta } : {};
          } else if (data && Array.isArray(data.results)) {
            // standard DRF pagination object nested under `data`
            list = data.results;
            meta = { count: data.count, next: data.next, previous: data.previous };
          } else {
            list = [];
            meta = data && data._meta ? { ...data._meta } : {};
          }
          this.items = list;
          this.meta = meta;
          if (this.meta.count === undefined) this.meta.count = list.length;
          this.state = list.length ? "ready" : "empty";
          if (this._cfg.onLoad) this._cfg.onLoad(list, this);
        } catch (e) {
          if (seq !== this._seq) return;
          // A 404 on a collection almost always means "nothing yet" or a
          // missing prerequisite (e.g. teacher profile not created) — show
          // the friendly empty state, not a hard error.
          if (e.status === 404) {
            this.items = [];
            this.notFound = true;
            this.state = "empty";
            return;
          }
          this.errorMsg = e.message || "We couldn't load this.";
          this.state = "error";
        }
      },
      reload() { this.load(); },
      next() { if (this.hasNext()) { this.page++; this.load(); this._top(); } },
      prev() { if (this.hasPrev()) { this.page--; this.load(); this._top(); } },
      _top() { window.scrollTo({ top: 0, behavior: "smooth" }); },
      setParam(k, v) { this.params = { ...this.params, [k]: v === "" || v == null ? undefined : v }; },
      clearParams() { this.params = { ...this._baseParams }; },
      activeFilterCount() {
        return Object.keys(this.params).filter((k) => this.params[k] && this.params[k] !== this._baseParams[k]).length;
      },
      removeFromList(pred) { this.items = this.items.filter((x) => !pred(x)); if (!this.items.length) this.state = "empty"; },
    };
  }

  function record(cfg) {
    return {
      _endpoint: cfg.endpoint,
      obj: null,
      state: "loading",
      errorMsg: "",
      _cfg: cfg,
      init() { this.load(); },
      async load() {
        this.state = "loading";
        try {
          this.obj = await api.get(this._endpoint);
          this.state = "ready";
          if (this._cfg.onLoad) this._cfg.onLoad(this.obj, this);
        } catch (e) {
          this.errorMsg = e.message;
          this.state = e.status === 404 ? "missing" : "error";
        }
      },
      reload() { this.load(); },
    };
  }

  function apiForm(cfg) {
    return {
      _endpoint: cfg.endpoint,
      _method: (cfg.method || "post").toLowerCase(),
      model: cfg.initial ? JSON.parse(JSON.stringify(cfg.initial)) : {},
      errors: {},
      nonField: "",
      submitting: false,
      saved: false,
      _cfg: cfg,

      setModel(obj) { this.model = { ...this.model, ...(obj || {}) }; },
      fieldError(n) { return this.errors[n] || ""; },
      hasError(n) { return !!this.errors[n]; },
      clearError(n) { if (this.errors[n]) { const e = { ...this.errors }; delete e[n]; this.errors = e; } },

      async submit(endpointOverride, methodOverride) {
        if (this.submitting) return;
        this.submitting = true;
        this.errors = {};
        this.nonField = "";
        try {
          const payload = this._cfg.transform ? this._cfg.transform(this.model) : this.model;
          const method = (methodOverride || this._method);
          const fn = api[method === "delete" ? "del" : method];
          const res = await fn(endpointOverride || this._endpoint, payload);
          this.saved = true;
          window.toast("success", this._cfg.successMessage || "Saved.");
          if (this._cfg.onSuccess) this._cfg.onSuccess(res, this);
          return res;
        } catch (e) {
          if (e.fieldErrors) {
            this.errors = e.fieldErrors;
            this.nonField = e.fieldErrors.non_field_errors || e.fieldErrors.detail || "";
          } else {
            this.nonField = e.message;
          }
          window.toast("error", e.fieldErrors ? "Please fix the highlighted fields." : e.message);
          throw e;
        } finally {
          this.submitting = false;
        }
      },
    };
  }

  window.mk = { collection, record, apiForm };

  document.addEventListener("alpine:init", () => {
    window.Alpine.data("collection", (cfg) => collection(cfg || {}));
    window.Alpine.data("record", (cfg) => record(cfg || {}));
    window.Alpine.data("apiForm", (cfg) => apiForm(cfg || {}));
  });
})();
