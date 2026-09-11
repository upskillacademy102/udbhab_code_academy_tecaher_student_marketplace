import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Named, StudentProfile } from "@/lib/types";
import { toast } from "@/lib/ui";

/**
 * The student's own profile.
 *
 * Kept short on purpose. None of this gates anything — matching runs off the
 * requirement, not off here — so it is framed as "helps us aim better",
 * never as a chore that must be completed before the product works.
 */

const LEVELS = [
  { id: "school", label: "School" },
  { id: "high_school", label: "High school" },
  { id: "undergraduate", label: "Undergraduate" },
  { id: "postgraduate", label: "Postgraduate" },
  { id: "competitive_exam", label: "Preparing for an exam" },
  { id: "hobby_other", label: "Learning for myself" },
] as const;

interface Form {
  education_level: string;
  grade_or_year: string;
  city: string;
  state: string;
  country: string;
  preferred_subjects: string;
  bio: string;
}

const EMPTY: Form = {
  education_level: "", grade_or_year: "", city: "", state: "",
  country: "", preferred_subjects: "", bio: "",
};

export function Profile() {
  const [f, setF] = useState<Form>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [nonField, setNonField] = useState("");
  const [saving, setSaving] = useState(false);
  const [exists, setExists] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ["me-student"],
    queryFn: async () => {
      try {
        return await api.get<StudentProfile>("/students/me/", { silent: true });
      } catch (e) {
        // 404 just means the profile has not been created yet — the same
        // form creates it, so this is a normal first-visit state, not an error.
        if ((e as ApiError).status === 404) {
          setExists(false);
          return null;
        }
        throw e;
      }
    },
  });

  const grades = useQuery({
    queryKey: ["grade-levels"],
    queryFn: () => api.list<Named>("/grade-levels/", { params: { page_size: 100 } }),
    staleTime: 10 * 60_000,
  }).data?.items ?? [];

  useEffect(() => {
    if (!data) return;
    setF({
      education_level: data.education_level ?? "",
      grade_or_year: data.grade_or_year ?? "",
      city: data.city ?? "",
      state: data.state ?? "",
      country: data.country ?? "",
      preferred_subjects: data.preferred_subjects ?? "",
      bio: data.bio ?? "",
    });
  }, [data]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setF((p) => ({ ...p, [k]: v }));
    setErrors((e) => {
      const { [k as string]: _drop, ...rest } = e;
      return rest;
    });
  };

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setNonField("");
    setSaving(true);
    try {
      // Send only what has a value: DRF treats "" as an invalid value for
      // these optional fields rather than as "cleared".
      const payload: Record<string, string> = {};
      for (const [k, v] of Object.entries(f)) if (v) payload[k] = v;
      // PATCH updates an existing profile; on a first save there is nothing
      // to patch and the API answers "Student profile not found. Create one
      // first." POST is what creates it.
      if (exists) await api.patch("/students/me/", payload, { silent: true });
      else await api.post("/students/me/", payload, { silent: true });
      setExists(true);
      toast("success", "Saved.");
    } catch (err) {
      const e2 = err as ApiError;
      if (e2.fieldErrors) setErrors(e2.fieldErrors);
      else setNonField(e2.message || "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return <div className="h-96 animate-pulse rounded-2xl bg-ink-100" />;
  }

  return (
    <form className="flex max-w-2xl flex-col gap-5" onSubmit={save}>
      {!exists && (
        <div className="u-alert u-alert-info">
          <span>Tell us a bit about yourself so we can aim better. All of it is optional.</span>
        </div>
      )}
      {nonField && <div className="u-alert u-alert-error">{nonField}</div>}

      <section className="u-card u-card-pad flex flex-col gap-4">
        <h2 className="u-h3">Where you're at</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="u-field">
            <label className="u-label" htmlFor="p-level">Stage</label>
            <select id="p-level" className="u-select" value={f.education_level} onChange={(e) => set("education_level", e.target.value)}>
              <option value="">Not saying</option>
              {LEVELS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
            </select>
            {errors.education_level && <p className="u-error">{errors.education_level}</p>}
          </div>
          <div className="u-field">
            <label className="u-label" htmlFor="p-grade">Class or year</label>
            <select id="p-grade" className="u-select" value={f.grade_or_year} onChange={(e) => set("grade_or_year", e.target.value)}>
              <option value="">Not saying</option>
              {grades.map((g) => <option key={g.id} value={g.name}>{g.name}</option>)}
            </select>
            {errors.grade_or_year && <p className="u-error">{errors.grade_or_year}</p>}
          </div>
        </div>
      </section>

      <section className="u-card u-card-pad flex flex-col gap-4">
        <h2 className="u-h3">Where you are</h2>
        <p className="u-fine -mt-2">Only needed if you want lessons in person.</p>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="u-field">
            <label className="u-label" htmlFor="p-city">City</label>
            <input id="p-city" className="u-input" value={f.city} onChange={(e) => set("city", e.target.value)} />
            {errors.city && <p className="u-error">{errors.city}</p>}
          </div>
          <div className="u-field">
            <label className="u-label" htmlFor="p-state">State</label>
            <input id="p-state" className="u-input" value={f.state} onChange={(e) => set("state", e.target.value)} />
          </div>
          <div className="u-field">
            <label className="u-label" htmlFor="p-country">Country</label>
            <input id="p-country" className="u-input" value={f.country} onChange={(e) => set("country", e.target.value)} />
          </div>
        </div>
      </section>

      <section className="u-card u-card-pad flex flex-col gap-4">
        <h2 className="u-h3">What you want to learn</h2>
        <div className="u-field">
          <label className="u-label" htmlFor="p-subjects">Subjects</label>
          <input id="p-subjects" className="u-input" placeholder="Maths, Physics, Spoken English"
            value={f.preferred_subjects} onChange={(e) => set("preferred_subjects", e.target.value)} />
          <p className="u-hint">Separate them with commas.</p>
          {errors.preferred_subjects && <p className="u-error">{errors.preferred_subjects}</p>}
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="p-bio">Anything else</label>
          <textarea id="p-bio" className="u-textarea" placeholder="What you're working towards, where you get stuck…"
            value={f.bio} onChange={(e) => set("bio", e.target.value)} />
          {errors.bio && <p className="u-error">{errors.bio}</p>}
        </div>
      </section>

      <div className="flex justify-end">
        <button type="submit" className="u-btn-primary u-btn-lg" data-loading={saving || undefined} disabled={saving}>
          Save
        </button>
      </div>
    </form>
  );
}
