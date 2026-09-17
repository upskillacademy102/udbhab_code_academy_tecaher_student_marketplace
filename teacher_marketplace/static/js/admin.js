/* ============================================================
   Udbhab — admin: generic resource CRUD + config map.
   Drives templates/web/admin/resource.html and locations.html.
   ============================================================ */
window.RESOURCE_CONFIG = {
  subjects: {
    title: "Subjects", endpoint: "/subjects/", crud: true,
    columns: [
      { key: "name", label: "Name" },
      { key: "description", label: "Description", muted: true },
      { key: "is_active", label: "Status", type: "status" },
    ],
    fields: [
      { key: "name", label: "Name", required: true },
      { key: "description", label: "Description", type: "textarea" },
      { key: "icon", label: "Icon key" },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
  languages: {
    title: "Languages", endpoint: "/languages/", crud: true,
    columns: [
      { key: "name", label: "Name" },
      { key: "code", label: "Code" },
      { key: "is_active", label: "Status", type: "status" },
    ],
    fields: [
      { key: "name", label: "Name", required: true },
      { key: "code", label: "ISO code", hint: "e.g. en, hi, bn" },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
  "grade-levels": {
    title: "Grade Levels", endpoint: "/grade-levels/", crud: true,
    columns: [
      { key: "name", label: "Name" },
      { key: "sort_order", label: "Sort order", type: "number" },
      { key: "is_active", label: "Status", type: "status" },
    ],
    fields: [
      { key: "name", label: "Name", required: true },
      { key: "sort_order", label: "Sort order", type: "number", hint: "Lower numbers show first in the dropdown." },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
  "token-packages": {
    title: "Token Packages", endpoint: "/token-packages/", crud: true,
    columns: [
      { key: "name", label: "Name" },
      { key: "token_count", label: "Tokens", type: "number" },
      { key: "price", label: "Price", type: "money" },
      { key: "final_price", label: "Final", type: "money" },
      { key: "is_active", label: "Status", type: "status" },
    ],
    fields: [
      { key: "name", label: "Name", required: true },
      { key: "token_count", label: "Token count", type: "number", required: true },
      { key: "price", label: "Price (₹)", type: "number", required: true },
      { key: "gst_percentage", label: "GST %", type: "number" },
      { key: "discount_percentage", label: "Discount %", type: "number" },
      { key: "sort_order", label: "Sort order", type: "number" },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
  plans: {
    title: "Subscription Plans", endpoint: "/subscriptions/plans/", crud: true,
    columns: [
      { key: "name", label: "Name" },
      { key: "monthly_price", label: "Price/mo", type: "money" },
      { key: "compare_at_price", label: "Was", type: "money" },
      { key: "free_leads", label: "Free leads", type: "number" },
      { key: "status", label: "Status", type: "status" },
    ],
    fields: [
      { key: "name", label: "Name", required: true },
      { key: "monthly_price", label: "Monthly price (₹)", type: "number", required: true },
      { key: "compare_at_price", label: "Struck-through 'was' price (₹, optional)", type: "number" },
      { key: "free_leads", label: "Free leads / month", type: "number", required: true },
      { key: "priority_rank", label: "Priority rank", type: "number" },
      { key: "lead_multiplier", label: "Lead multiplier", type: "number" },
      { key: "bonus_tokens", label: "Bonus tokens", type: "number" },
      { key: "is_featured_listing", label: "Featured listing", type: "checkbox" },
      { key: "status", label: "Status", type: "select", options: [["active", "Active"], ["inactive", "Inactive"]], default: "active" },
    ],
  },
  "lead-pricing": {
    title: "Lead Unlock Pricing", endpoint: "/lead-unlock-pricing/", crud: true,
    columns: [
      { key: "tier", label: "Tier" },
      { key: "token_cost", label: "Token cost", type: "number" },
      { key: "is_active", label: "Status", type: "status" },
    ],
    fields: [
      { key: "tier", label: "Tier", required: true },
      { key: "token_cost", label: "Token cost", type: "number", required: true },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
  "matching-config": {
    title: "Matching Config", endpoint: "/matching/config/", crud: false, appendOnly: true,
    hint: "Each save creates a new active configuration row.",
    columns: [
      { key: "subject_match_threshold", label: "Subject %", type: "number" },
      { key: "language_match_threshold", label: "Language %", type: "number" },
      { key: "max_location_radius_km", label: "Max radius km", type: "number" },
      { key: "offline_response_window_hours", label: "Offline response hrs", type: "number" },
      { key: "online_tier_window_hours", label: "Online tier hrs", type: "number" },
      { key: "is_active", label: "Status", type: "status" },
      { key: "created_at", label: "Created", type: "date" },
    ],
    fields: [
      { key: "subject_match_threshold", label: "Subject match threshold", type: "number", required: true },
      { key: "language_match_threshold", label: "Language match threshold", type: "number", required: true },
      { key: "time_match_threshold_minutes", label: "Time match threshold (min)", type: "number", required: true },
      { key: "initial_location_radius_km", label: "Initial radius (km)", type: "number", required: true },
      { key: "location_radius_increment_km", label: "Radius increment (km)", type: "number", required: true },
      { key: "max_location_radius_km", label: "Max radius (km)", type: "number", required: true },
      { key: "offline_response_window_hours", label: "Offline response window (hrs)", type: "number", required: true },
      { key: "online_tier_window_hours", label: "Online tier window (hrs)", type: "number", required: true },
      { key: "lead_visibility_window_hours", label: "Lead visibility window (hrs)", type: "number", required: true },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
  "subject-aliases": {
    title: "Subject Aliases", endpoint: "/matching/subject-aliases/", crud: false, appendOnly: true,
    columns: [
      { key: "alias_text", label: "Alias" },
      { key: "subject_name", label: "Maps to subject" },
      { key: "created_at", label: "Added", type: "date" },
    ],
    fields: [
      { key: "subject", label: "Subject", type: "ref", refEndpoint: "/subjects/", required: true },
      { key: "alias_text", label: "Alias text", required: true, hint: "e.g. 'maths' for Mathematics" },
    ],
  },
  "language-aliases": {
    title: "Language Aliases", endpoint: "/matching/language-aliases/", crud: false, appendOnly: true,
    columns: [
      { key: "alias_text", label: "Alias" },
      { key: "language_name", label: "Maps to language" },
      { key: "created_at", label: "Added", type: "date" },
    ],
    fields: [
      { key: "language", label: "Language", type: "ref", refEndpoint: "/languages/", required: true },
      { key: "alias_text", label: "Alias text", required: true },
    ],
  },
  pincodes: {
    title: "Pincode Locations", endpoint: "/matching/pincode-locations/", crud: false, appendOnly: true,
    columns: [
      { key: "pincode", label: "Pincode" },
      { key: "city", label: "City" },
      { key: "state", label: "State" },
      { key: "country", label: "Country" },
    ],
    fields: [
      { key: "pincode", label: "Pincode", required: true },
      { key: "latitude", label: "Latitude", type: "number", required: true, hint: "Decimal degrees, e.g. 22.5726" },
      { key: "longitude", label: "Longitude", type: "number", required: true, hint: "Decimal degrees, e.g. 88.3639" },
      { key: "city", label: "City" },
      { key: "state", label: "State" },
      { key: "country", label: "Country" },
    ],
  },
  // locations sub-resources
  countries: {
    title: "Countries", endpoint: "/location/countries/", crud: true,
    columns: [{ key: "name", label: "Name" }, { key: "code", label: "Code" }, { key: "is_active", label: "Status", type: "status" }],
    fields: [{ key: "name", label: "Name", required: true }, { key: "code", label: "ISO code" }, { key: "is_active", label: "Active", type: "checkbox", default: true }],
  },
  states: {
    title: "States", endpoint: "/location/states/", crud: true,
    columns: [{ key: "name", label: "Name" }, { key: "country_name", label: "Country" }, { key: "is_active", label: "Status", type: "status" }],
    fields: [
      { key: "country", label: "Country", type: "ref", refEndpoint: "/location/countries/", required: true },
      { key: "name", label: "Name", required: true }, { key: "code", label: "Code" },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
  cities: {
    title: "Cities", endpoint: "/location/cities/", crud: true,
    columns: [{ key: "name", label: "Name" }, { key: "state_name", label: "State" }, { key: "country_name", label: "Country" }, { key: "is_active", label: "Status", type: "status" }],
    fields: [
      { key: "state", label: "State", type: "ref", refEndpoint: "/location/states/", required: true },
      { key: "name", label: "Name", required: true },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
  },
};

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("resourceManager", (key) => ({
    ...window.mk.collection({ endpoint: window.RESOURCE_CONFIG[key].endpoint, pageSize: 20 }),
    cfg: window.RESOURCE_CONFIG[key],
    q: "",
    formOpen: false,
    editing: null,
    model: {},
    errors: {},
    nonField: "",
    submitting: false,
    refs: {}, // { fieldKey: [options] }

    init() {
      this.initCollection();
      this.$watch("q", window.debounce(() => { this.setParam("search", this.q); }, 350));
      (this.cfg.fields || []).filter((f) => f.type === "ref").forEach((f) => {
        api.get(f.refEndpoint, { params: { page_size: 300 }, silent: true })
          .then((d) => (this.refs[f.key] = Array.isArray(d) ? d : []))
          .catch(() => (this.refs[f.key] = []));
      });
    },

    blankModel() {
      const m = {};
      (this.cfg.fields || []).forEach((f) => { m[f.key] = f.default !== undefined ? f.default : (f.type === "checkbox" ? false : ""); });
      return m;
    },
    openCreate() { this.editing = null; this.model = this.blankModel(); this.errors = {}; this.nonField = ""; this.formOpen = true; },
    openEdit(row) {
      this.editing = row; this.errors = {}; this.nonField = "";
      const m = {};
      (this.cfg.fields || []).forEach((f) => {
        let v = row[f.key];
        if (f.type === "ref" && v && typeof v === "object") v = v.id;
        m[f.key] = v ?? (f.type === "checkbox" ? false : "");
      });
      this.model = m; this.formOpen = true;
    },
    async save() {
      if (this.submitting) return;
      this.submitting = true; this.errors = {}; this.nonField = "";
      const payload = {};
      Object.entries(this.model).forEach(([k, v]) => { if (v !== "" && v !== null && v !== undefined) payload[k] = v; });
      try {
        if (this.editing && this.cfg.crud) {
          await api.patch(`${this.cfg.endpoint}${this.editing.id}/`, payload);
          window.toast("success", `${this.cfg.title.replace(/s$/, "")} updated.`);
        } else {
          await api.post(this.cfg.endpoint, payload);
          window.toast("success", "Added.");
        }
        this.formOpen = false; this.load();
      } catch (e) {
        if (e.fieldErrors) { this.errors = e.fieldErrors; this.nonField = e.fieldErrors.non_field_errors || e.fieldErrors.detail || ""; window.toast("error", "Please fix the highlighted fields."); }
        else { this.nonField = e.message; window.toast("error", e.message); }
      } finally { this.submitting = false; }
    },
    async remove(row) {
      if (!(await window.confirmAction({ title: `Delete this ${this.cfg.title.replace(/s$/, "").toLowerCase()}?`, message: "This can't be undone.", confirmLabel: "Delete", danger: true }))) return;
      try {
        await api.del(`${this.cfg.endpoint}${row.id}/`);
        window.toast("success", "Deleted.");
        this.removeFromList((x) => x.id === row.id);
      } catch (e) { window.toast("error", e.message); }
    },
    cell(row, col) {
      const v = row[col.key];
      if (col.type === "money") return window.fmt.money(v);
      if (col.type === "number") return window.fmt.number(v);
      if (col.type === "date") return window.fmt.date(v);
      if (col.type === "status") return v === false || v === "inactive" ? "Inactive" : "Active";
      return v ?? "—";
    },
    isInactive(row, col) { return row[col.key] === false || row[col.key] === "inactive"; },
  }));
});
