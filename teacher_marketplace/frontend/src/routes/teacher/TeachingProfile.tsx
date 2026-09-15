import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Named, TeacherProfile } from "@/lib/types";
import { toast } from "@/lib/ui";
import { PhotoCropModal } from "@/components/PhotoCropModal";

/**
 * The teaching profile.
 *
 * This was one 471-line form that saved everything at once. It is now five
 * sections that each save on their own, because a wall of fields is the
 * thing people abandon — and because the data genuinely lives in two places:
 * /teachers/me/ holds the person (bio, experience, qualification) and
 * /teachers/profile/ holds the marketplace listing (headline, rate,
 * subjects, languages, cities). One button saving two endpoints hid that and
 * made a partial failure impossible to explain.
 *
 * Completeness is framed as reach, not as a chore: an incomplete profile
 * ranks lower and matches fewer students, which is a real consequence rather
 * than a nag.
 *
 * Verification is deliberately NOT ported. It handles document and selfie
 * uploads and drives whether a teacher is visible at all; it is left on the
 * Django page until it can be moved on its own.
 */

const QUALIFICATIONS = [
  { id: "high_school", label: "High school" },
  { id: "diploma", label: "Diploma" },
  { id: "bachelors", label: "Bachelor's degree" },
  { id: "masters", label: "Master's degree" },
  { id: "doctorate", label: "PhD" },
  { id: "professional_certification", label: "Professional certification" },
  { id: "other", label: "Something else" },
] as const;

interface Listing {
  headline: string;
  teaching_mode: "online" | "offline" | "both";
  hourly_rate: string;
  monthly_rate: string;
  monthly_rate_max: string;
  subjects: string[];
  languages: string[];
  cities: string[];
}

interface About {
  bio: string;
  experience_years: string;
  qualification_level: string;
  qualification_detail: string;
}

export function TeachingProfile() {
  const qc = useQueryClient();

  const profile = useQuery({
    queryKey: ["my-teacher-profile"],
    queryFn: async () => {
      try {
        return await api.get<TeacherProfile>("/teachers/profile/", { silent: true });
      } catch (e) {
        if ((e as ApiError).status === 404) return null;
        throw e;
      }
    },
    retry: false,
  });

  const base = useQuery({
    queryKey: ["my-teacher-base"],
    queryFn: async () => {
      try {
        return await api.get<Record<string, unknown>>("/teachers/me/", { silent: true });
      } catch (e) {
        if ((e as ApiError).status === 404) return null;
        throw e;
      }
    },
    retry: false,
  });

  const subjects = useQuery({
    queryKey: ["subjects"],
    queryFn: () => api.list<Named>("/subjects/", { params: { page_size: 300 } }),
    staleTime: 10 * 60_000,
  }).data?.items ?? [];
  const languages = useQuery({
    queryKey: ["languages"],
    queryFn: () => api.list<Named>("/languages/", { params: { page_size: 300 } }),
    staleTime: 10 * 60_000,
  }).data?.items ?? [];
  const cities = useQuery({
    queryKey: ["cities"],
    queryFn: () => api.list<Named>("/location/cities/", { params: { page_size: 500 } }),
    staleTime: 10 * 60_000,
  }).data?.items ?? [];

  const p = profile.data;
  const b = base.data;

  const [listing, setListing] = useState<Listing>({
    headline: "", teaching_mode: "online", hourly_rate: "", monthly_rate: "", monthly_rate_max: "", subjects: [], languages: [], cities: [],
  });
  const [about, setAbout] = useState<About>({
    bio: "", experience_years: "", qualification_level: "", qualification_detail: "",
  });
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!p) return;
    setListing({
      headline: p.headline ?? "",
      teaching_mode: (p.teaching_mode as Listing["teaching_mode"]) ?? "online",
      hourly_rate: p.hourly_rate ?? "",
      monthly_rate: p.monthly_rate ?? "",
      monthly_rate_max: p.monthly_rate_max ?? "",
      subjects: (p.subjects ?? []).map((s) => s.id),
      languages: (p.languages ?? []).map((l) => l.id),
      cities: (p.cities ?? []).map((c) => c.id),
    });
  }, [p]);

  useEffect(() => {
    if (!b) return;
    setAbout({
      bio: String(b.bio ?? ""),
      experience_years: b.experience_years == null ? "" : String(b.experience_years),
      qualification_level: String(b.qualification_level ?? ""),
      qualification_detail: String(b.qualification_detail ?? ""),
    });
    setPhotoUrl((b.profile_photo as string) || null);
  }, [b]);

  const loading = profile.isLoading || base.isLoading;
  if (loading) return <div className="h-96 animate-pulse rounded-2xl bg-ink-100" />;

  // What is missing, in the order it costs them reach.
  const gaps: string[] = [];
  if (!photoUrl) gaps.push("a profile photo");
  if (!listing.subjects.length) gaps.push("subjects you teach");
  if (!listing.languages.length) gaps.push("languages you teach in");
  if (!listing.hourly_rate && !listing.monthly_rate) gaps.push("your rate");
  if (!listing.headline) gaps.push("a headline");
  if (!about.bio) gaps.push("a short bio");

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      {p && !p.is_verified && (
        <div className="u-card u-card-pad border-marigold-400 bg-marigold-50">
          <h2 className="u-h3">You're not in search results yet</h2>
          <p className="u-body mt-1.5 text-ink-700">
            Students only see verified teachers. Verification is still on the old page while we move it across.
          </p>
          <a href="/teacher/profile/?legacy=1" className="u-btn-secondary u-btn-sm mt-3">Go to verification</a>
        </div>
      )}

      {gaps.length > 0 && (
        <div className="u-card u-card-pad border-pine-300 bg-pine-50">
          <h2 className="u-h3">Add {gaps.length === 1 ? gaps[0] : `${gaps.length} things`}</h2>
          <p className="u-body mt-1.5 text-ink-700">
            Students are matched on what's here. Missing {gaps.slice(0, 2).join(" and ")} means fewer of them reach you.
          </p>
        </div>
      )}

      <PhotoSection
        photoUrl={photoUrl}
        exists={Boolean(b)}
        onSaved={(url) => { setPhotoUrl(url); qc.invalidateQueries({ queryKey: ["my-teacher-base"] }); }}
      />

      <ListingSection
        value={listing}
        onChange={setListing}
        subjects={subjects}
        languages={languages}
        cities={cities}
        exists={Boolean(p)}
        onSaved={() => qc.invalidateQueries({ queryKey: ["my-teacher-profile"] })}
      />

      <AboutSection
        value={about}
        onChange={setAbout}
        exists={Boolean(b)}
        onSaved={() => qc.invalidateQueries({ queryKey: ["my-teacher-base"] })}
      />
    </div>
  );
}

/* ---------------- photo: required for verification ---------------- */

function PhotoSection({
  photoUrl, exists, onSaved,
}: {
  photoUrl: string | null;
  exists: boolean;
  onSaved: (url: string) => void;
}) {
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function upload(blob: Blob) {
    setSaving(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("profile_photo", blob, "profile-photo.jpg");
      const resp = exists
        ? await api.patch<Record<string, unknown>>("/teachers/me/", fd, { silent: true })
        : await api.post<Record<string, unknown>>("/teachers/me/", fd, { silent: true });
      onSaved((resp?.profile_photo as string) ?? photoUrl ?? "");
      toast("success", "Profile photo saved.");
    } catch (e) {
      const err = e as ApiError;
      setError(err.fieldErrors?.profile_photo || err.message || "Couldn't upload that photo.");
    } finally {
      setSaving(false);
      setPendingFile(null);
    }
  }

  return (
    <section className="u-card overflow-hidden">
      <div className="border-b border-ink-200 px-5 py-4 sm:px-6">
        <div className="flex items-center gap-2">
          <h2 className="u-h3">Profile photo</h2>
          {photoUrl ? (
            <span className="rounded-full bg-pine-100 px-2 py-0.5 text-[0.6875rem] font-semibold text-pine-800">Added</span>
          ) : (
            <span className="rounded-full bg-marigold-100 px-2 py-0.5 text-[0.6875rem] font-semibold text-marigold-900">Required</span>
          )}
        </div>
        <p className="u-fine mt-0.5">Students only see verified teachers, and a clear photo is required to be verified.</p>
      </div>
      <div className="flex items-center gap-4 p-5 sm:p-6">
        <div className="h-20 w-20 shrink-0 overflow-hidden rounded-full border border-ink-200 bg-ink-100">
          {photoUrl ? (
            <img src={photoUrl} alt="" className="h-full w-full object-cover object-top" />
          ) : (
            <svg className="h-full w-full text-ink-300" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="8" r="4" fill="currentColor" />
              <path d="M4 20c0-4 3.5-7 8-7s8 3 8 7" fill="currentColor" />
            </svg>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <label className="u-btn-secondary u-btn-sm cursor-pointer" data-loading={saving || undefined}>
              <span>{saving ? "Uploading…" : photoUrl ? "Change photo" : "Choose photo"}</span>
              <input type="file" className="hidden" accept="image/jpeg,image/png,image/webp" disabled={saving}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) setPendingFile(f); setError(""); e.target.value = ""; }} />
            </label>
          </div>
          {error && <p className="u-error mt-1.5">{error}</p>}
        </div>
      </div>

      {pendingFile && (
        <PhotoCropModal
          file={pendingFile}
          uploading={saving}
          onCancel={() => setPendingFile(null)}
          onConfirm={upload}
        />
      )}
    </section>
  );
}

/* ---------------- listing: what students search on ---------------- */

function ListingSection({
  value, onChange, subjects, languages, cities, exists, onSaved,
}: {
  value: Listing;
  onChange: (v: Listing) => void;
  subjects: Named[];
  languages: Named[];
  cities: Named[];
  exists: boolean;
  onSaved: () => void;
}) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const toggle = (key: "subjects" | "languages" | "cities", id: string) => {
    const cur = value[key];
    onChange({ ...value, [key]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] });
  };

  async function save() {
    setSaving(true);
    setErrors({});
    try {
      const payload: Record<string, unknown> = {
        headline: value.headline || null,
        teaching_mode: value.teaching_mode,
        subjects: value.subjects,
        languages: value.languages,
        cities: value.teaching_mode === "online" ? [] : value.cities,
      };
      if (value.hourly_rate) payload.hourly_rate = Number(value.hourly_rate);
      if (value.monthly_rate) payload.monthly_rate = Number(value.monthly_rate);
      if (value.monthly_rate_max) payload.monthly_rate_max = Number(value.monthly_rate_max);
      // POST creates the marketplace profile the first time; PATCH after.
      if (exists) await api.patch("/teachers/profile/", payload, { silent: true });
      else await api.post("/teachers/profile/", payload, { silent: true });
      toast("success", "Saved.");
      onSaved();
    } catch (e) {
      const err = e as ApiError;
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else toast("error", err.message || "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="What you teach"
      hint="This is what students search on."
      onSave={save}
      saving={saving}
    >
      <div className="u-field">
        <label className="u-label" htmlFor="tp-headline">Headline</label>
        <input id="tp-headline" className="u-input" maxLength={200}
          placeholder="e.g. Chemistry for Class 11–12, organic a speciality"
          value={value.headline} onChange={(e) => onChange({ ...value, headline: e.target.value })} />
        <p className="u-hint">One line students see first.</p>
        {errors.headline && <p className="u-error">{errors.headline}</p>}
      </div>

      <div className="u-field">
        <span className="u-label">How you teach</span>
        <div className="mt-1 flex gap-2">
          {(["online", "offline", "both"] as const).map((m) => (
            <button key={m} type="button" className="u-chip u-chip-sm flex-1" aria-pressed={value.teaching_mode === m}
              onClick={() => onChange({ ...value, teaching_mode: m })}>
              {m === "online" ? "Online" : m === "offline" ? "In person" : "Either"}
            </button>
          ))}
        </div>
      </div>

      <div className="u-field">
        <label className="u-label" htmlFor="tp-rate">Hourly rate (₹)</label>
        <input id="tp-rate" type="number" min={0} className="u-input" placeholder="Optional" value={value.hourly_rate}
          onChange={(e) => onChange({ ...value, hourly_rate: e.target.value })} />
        {errors.hourly_rate && <p className="u-error">{errors.hourly_rate}</p>}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="u-field">
          <label className="u-label" htmlFor="tp-monthly-rate">Monthly rate (₹)</label>
          <input id="tp-monthly-rate" type="number" min={0} className="u-input" placeholder="e.g. 600" value={value.monthly_rate}
            onChange={(e) => onChange({ ...value, monthly_rate: e.target.value })} />
          {errors.monthly_rate && <p className="u-error">{errors.monthly_rate}</p>}
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="tp-monthly-rate-max">Up to (₹)</label>
          <input id="tp-monthly-rate-max" type="number" min={0} className="u-input" placeholder="e.g. 1000" value={value.monthly_rate_max}
            onChange={(e) => onChange({ ...value, monthly_rate_max: e.target.value })} />
          {errors.monthly_rate_max && <p className="u-error">{errors.monthly_rate_max}</p>}
        </div>
      </div>
      <p className="u-hint -mt-2">
        Give a range if your fee depends on class size or level (e.g. ₹600–₹1,000) — leave "Up to" blank for one fixed price. Share either rate, both, or neither.
      </p>

      <Picker label="Subjects" options={subjects} selected={value.subjects} onToggle={(id) => toggle("subjects", id)}
        empty="No subjects have been added to the platform yet." error={errors.subjects} />

      <Picker label="Languages you teach in" options={languages} selected={value.languages}
        onToggle={(id) => toggle("languages", id)}
        empty="No languages have been added to the platform yet." error={errors.languages} />

      {value.teaching_mode !== "online" && (
        <Picker label="Cities you'll travel to" options={cities} selected={value.cities}
          onToggle={(id) => toggle("cities", id)} empty="No cities available." error={errors.cities} />
      )}
    </Section>
  );
}

/* ---------------- about: the person ---------------- */

function AboutSection({
  value, onChange, exists, onSaved,
}: {
  value: About;
  onChange: (v: About) => void;
  exists: boolean;
  onSaved: () => void;
}) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setErrors({});
    try {
      const payload: Record<string, unknown> = {};
      if (value.bio) payload.bio = value.bio;
      if (value.experience_years !== "") payload.experience_years = Number(value.experience_years);
      if (value.qualification_level) payload.qualification_level = value.qualification_level;
      if (value.qualification_detail) payload.qualification_detail = value.qualification_detail;
      if (exists) await api.patch("/teachers/me/", payload, { silent: true });
      else await api.post("/teachers/me/", payload, { silent: true });
      toast("success", "Saved.");
      onSaved();
    } catch (e) {
      const err = e as ApiError;
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else toast("error", err.message || "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="About you" hint="Students read this before they decide." onSave={save} saving={saving}>
      <div className="u-field">
        <label className="u-label" htmlFor="tb-bio">Short bio</label>
        <textarea id="tb-bio" className="u-textarea" rows={4} maxLength={2000}
          placeholder="How you teach, who you've taught, what you're best at."
          value={value.bio} onChange={(e) => onChange({ ...value, bio: e.target.value })} />
        {errors.bio && <p className="u-error">{errors.bio}</p>}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="u-field">
          <label className="u-label" htmlFor="tb-exp">Years teaching</label>
          <input id="tb-exp" type="number" min={0} max={80} className="u-input" value={value.experience_years}
            onChange={(e) => onChange({ ...value, experience_years: e.target.value })} />
          {errors.experience_years && <p className="u-error">{errors.experience_years}</p>}
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="tb-ql">Highest qualification</label>
          <select id="tb-ql" className="u-select" value={value.qualification_level}
            onChange={(e) => onChange({ ...value, qualification_level: e.target.value })}>
            <option value="">Not saying</option>
            {QUALIFICATIONS.map((q) => <option key={q.id} value={q.id}>{q.label}</option>)}
          </select>
        </div>
      </div>

      <div className="u-field">
        <label className="u-label" htmlFor="tb-qd">What in, and where from</label>
        <input id="tb-qd" className="u-input" maxLength={255} placeholder="e.g. M.Sc. Chemistry, University of Madras"
          value={value.qualification_detail} onChange={(e) => onChange({ ...value, qualification_detail: e.target.value })} />
        {errors.qualification_detail && <p className="u-error">{errors.qualification_detail}</p>}
      </div>
    </Section>
  );
}

/* ---------------- shared ---------------- */

function Section({
  title, hint, children, onSave, saving,
}: {
  title: string;
  hint: string;
  children: React.ReactNode;
  onSave: () => void;
  saving: boolean;
}) {
  return (
    <section className="u-card overflow-hidden">
      <div className="border-b border-ink-200 px-5 py-4 sm:px-6">
        <h2 className="u-h3">{title}</h2>
        <p className="u-fine mt-0.5">{hint}</p>
      </div>
      <div className="flex flex-col gap-4 p-5 sm:p-6">{children}</div>
      <div className="flex justify-end border-t border-ink-200 px-5 py-4 sm:px-6">
        <button type="button" className="u-btn-primary" onClick={onSave} data-loading={saving || undefined} disabled={saving}>
          Save this section
        </button>
      </div>
    </section>
  );
}

function Picker({
  label, options, selected, onToggle, empty, error,
}: {
  label: string;
  options: Named[];
  selected: string[];
  onToggle: (id: string) => void;
  empty: string;
  error?: string;
}) {
  return (
    <div className="u-field">
      <span className="u-label">
        {label}
        {selected.length > 0 && <span className="ml-1.5 font-normal text-ink-500">({selected.length})</span>}
      </span>
      {options.length === 0 ? (
        <p className="u-hint">{empty}</p>
      ) : (
        <div className="mt-1 flex flex-wrap gap-2">
          {options.map((o) => (
            <button key={o.id} type="button" className="u-chip u-chip-sm" aria-pressed={selected.includes(o.id)}
              onClick={() => onToggle(o.id)}>
              {o.name}
            </button>
          ))}
        </div>
      )}
      {error && <p className="u-error">{error}</p>}
    </div>
  );
}
