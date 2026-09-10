/* ============================================================
   Taxonomy picker — shared by the landing hero and the sign-up flow.

   The subject and language lists come from the database, so their length
   is unknown and changes whenever a Super Admin adds a row. No single
   control is right across that range, so the picker renders by count:

       0 rows      -> a free-text box (an empty chip row reads as broken)
       1-12 rows   -> every option as a chip, nothing hidden
       13+ rows    -> the most-taught options as chips, plus a
                      type-to-filter combobox over the full list

   Thresholds follow current selection-control guidance: keep frequently
   used options permanently visible, and only reach for a filter once a
   list is genuinely long.

   The combobox implements the W3C APG "editable combobox with list
   autocomplete, manual selection" contract: role=combobox,
   aria-autocomplete=list, aria-expanded, aria-controls,
   aria-activedescendant; Down/Up move and wrap, Enter selects, Escape
   closes, printable characters filter. DOM focus never leaves the input.
   ============================================================ */
(function () {
  "use strict";

  var CHIP_LIMIT = 12; // at or below this, every option is a chip
  var CHIP_HEAD = 8; // above it, this many chips lead the filter
  var MAX_RESULTS = 50; // never paint an unbounded listbox

  function norm(s) {
    return String(s == null ? "" : s).trim().toLowerCase();
  }

  window.taxonomyMixin = function (tax) {
    var SUBJECTS = Array.isArray(tax && tax.subjects) ? tax.subjects : [];
    var LANGUAGES = Array.isArray(tax && tax.languages) ? tax.languages : [];

    return {
      SUBJECTS: SUBJECTS,
      LANGUAGES: LANGUAGES,

      /* ---- selection state -------------------------------------- */
      // `subject` holds a real taxonomy name, or the sentinel "__other"
      // when the visitor is typing something we don't have a row for.
      subject: null,
      subjectCustom: "",
      // `language` null means "Any language", which is the default: most
      // students have no preference and shouldn't be charged a decision.
      language: null,

      get resolvedSubject() {
        if (this.subject === "__other") return this.subjectCustom.trim() || null;
        return this.subject;
      },
      get resolvedLanguage() {
        return this.language || null;
      },

      listFor: function (field) {
        return field === "language" ? this.LANGUAGES : this.SUBJECTS;
      },

      /* ---- which control this list deserves ---------------------- */
      modeFor: function (field) {
        var n = this.listFor(field).length;
        if (!n) return "text";
        if (n <= CHIP_LIMIT) return "chips";
        return "hybrid";
      },
      chipsFor: function (field) {
        var list = this.listFor(field);
        return list.length <= CHIP_LIMIT ? list : list.slice(0, CHIP_HEAD);
      },

      /* ---- picking ---------------------------------------------- */
      pick: function (field, value) {
        this[field] = this[field] === value ? null : value;
        if (field === "subject" && this.subject !== "__other") {
          this.subjectCustom = "";
        }
        this.cbClose();
      },
      isPicked: function (field, value) {
        return this[field] === value;
      },
      // True when the current value came from the filter rather than a
      // visible chip — so the template can show it as an extra chip
      // instead of the selection silently vanishing off-screen.
      pickedOffList: function (field) {
        var v = this[field];
        if (!v || v === "__other") return false;
        return this.chipsFor(field).indexOf(v) === -1;
      },

      /* ---- combobox (only one open at a time) -------------------- */
      cb: { field: "", query: "", open: false, active: -1 },

      cbOptions: function () {
        var all = this.listFor(this.cb.field);
        var q = norm(this.cb.query);
        if (!q) return all.slice(0, MAX_RESULTS);
        var starts = [];
        var contains = [];
        for (var i = 0; i < all.length; i++) {
          var n = norm(all[i]);
          if (n.indexOf(q) === 0) starts.push(all[i]);
          else if (n.indexOf(q) !== -1) contains.push(all[i]);
        }
        return starts.concat(contains).slice(0, MAX_RESULTS);
      },

      cbId: function (field) {
        return "cb-" + field;
      },
      cbActiveId: function () {
        if (!this.cb.open || this.cb.active < 0) return null;
        return this.cbId(this.cb.field) + "-opt-" + this.cb.active;
      },

      cbInput: function (field) {
        this.cb.field = field;
        this.cb.open = true;
        this.cb.active = -1;
      },
      cbShow: function (field) {
        this.cb.field = field;
        this.cb.open = true;
      },
      cbClose: function () {
        this.cb.open = false;
        this.cb.active = -1;
      },
      cbMove: function (delta) {
        var n = this.cbOptions().length;
        if (!n) return;
        if (!this.cb.open) {
          this.cb.open = true;
          this.cb.active = delta > 0 ? 0 : n - 1;
          return;
        }
        var next = this.cb.active + delta;
        if (next < 0) next = n - 1;
        if (next >= n) next = 0;
        this.cb.active = next;
      },
      cbChoose: function (value) {
        if (value == null) return;
        this[this.cb.field] = value;
        if (this.cb.field === "subject") this.subjectCustom = "";
        this.cb.query = "";
        this.cbClose();
      },
      cbEnter: function () {
        var opts = this.cbOptions();
        if (this.cb.open && this.cb.active >= 0 && opts[this.cb.active]) {
          this.cbChoose(opts[this.cb.active]);
          return true;
        }
        // Nothing highlighted: if exactly one option matches, take it.
        if (opts.length === 1) {
          this.cbChoose(opts[0]);
          return true;
        }
        this.cbClose();
        return false;
      },
      cbEscape: function () {
        // APG: Escape closes the listbox; a second Escape clears the field.
        if (this.cb.open) this.cbClose();
        else this.cb.query = "";
      },
    };
  };
})();
