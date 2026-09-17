import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { PublicTeacherMarketplaceProfile } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

/**
 * "Learn with this teacher" - a student picks ONE specific teacher directly
 * from their profile, skipping the general matching pool entirely.
 *
 * Deliberately scoped to what THIS teacher actually offers - subject,
 * language, and time slot are all picked from their own profile, never
 * freely typed, so the resulting offer is something they can actually
 * deliver (the server re-validates the same way regardless, but there's no
 * reason to let the student pick something doomed to fail).
 */

const DAY_NAMES = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const DURATION_PRESETS = [120, 90, 60, 45, 30];

function durationFor(startTime: string, endTime: string): number | null {
  const [sh = 0, sm = 0] = startTime.split(":").map(Number);
  const [eh = 0, em = 0] = endTime.split(":").map(Number);
  const minutes = eh * 60 + em - (sh * 60 + sm);
  return DURATION_PRESETS.find((d) => d <= minutes) ?? null;
}

function fmtTime(t: string): string {
  const [h = 0, m = 0] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const hour12 = h % 12 || 12;
  return `${hour12}:${String(m).padStart(2, "0")} ${period}`;
}

export function LearnWithTeacherModal({
  teacherId, teacherName, onClose,
}: {
  teacherId: string;
  teacherName: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const { data: profile, isLoading, isError } = useQuery({
    queryKey: ["teacher-marketplace-profile", teacherId],
    queryFn: () => api.get<PublicTeacherMarketplaceProfile>(`/search/teachers/${teacherId}/`),
  });

  const [subjectId, setSubjectId] = useState("");
  const [languageIds, setLanguageIds] = useState<string[]>([]);
  const [slotId, setSlotId] = useState("");
  const [sending, setSending] = useState(false);

  const usableSlots = useMemo(
    () => (profile?.weekly_availability ?? []).filter((s) => durationFor(s.start_time, s.end_time) !== null),
    [profile]
  );

  useEffect(() => {
    if (!profile) return;
    const firstSubject = profile.subjects[0];
    const firstLanguage = profile.languages[0];
    const firstSlot = usableSlots[0];
    if (!subjectId && firstSubject) setSubjectId(firstSubject.id);
    if (!languageIds.length && firstLanguage) setLanguageIds([firstLanguage.id]);
    if (!slotId && firstSlot) setSlotId(firstSlot.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function toggleLanguage(id: string) {
    setLanguageIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function submit() {
    if (!profile) return;
    const slot = usableSlots.find((s) => s.id === slotId);
    if (!subjectId || !languageIds.length || !slot) {
      toast("warning", "Pick a subject, a language, and a time before continuing.");
      return;
    }
    const subjectName = profile.subjects.find((s) => s.id === subjectId)?.name ?? "";
    const languageNames = profile.languages
      .filter((l) => languageIds.includes(l.id))
      .map((l) => l.name)
      .join(", ");
    const ok = await confirmAction({
      title: `Learn with ${teacherName}?`,
      message:
        `${subjectName} · ${languageNames} · ${DAY_NAMES[slot.day_of_week]} ${fmtTime(slot.start_time)}–${fmtTime(slot.end_time)}.\n\n` +
        `This goes straight to ${teacherName} only - it never gets shown to anyone else. Are you sure?`,
      confirmLabel: "Yes, send it",
    });
    if (!ok) return;

    setSending(true);
    try {
      const duration = durationFor(slot.start_time, slot.end_time) ?? 60;
      await api.post("/student-requirements/direct-offer/", {
        offer_teacher_id: teacherId,
        subject_id: subjectId,
        language_ids: languageIds,
        no_language_preference: false,
        teaching_mode: profile.teaching_mode === "both" ? "online" : profile.teaching_mode,
        day_of_week: slot.day_of_week,
        start_time: slot.start_time,
        end_time: slot.end_time,
        timezone: slot.timezone,
        class_duration_minutes: duration,
      });
      toast("success", `Sent to ${teacherName}. They'll get a notification right away.`);
      onClose();
      navigate("/student/requirements/");
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't send that offer.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={`Learn with ${teacherName}`}>
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 top-10 mx-auto flex max-w-lg flex-col overflow-hidden rounded-t-3xl bg-paper shadow-raise sm:inset-y-10 sm:rounded-3xl">
        <div className="flex items-center justify-between border-b border-ink-200 px-5 py-4">
          <h2 className="u-h3">Learn with {teacherName}</h2>
          <button type="button" className="u-btn-ghost u-btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {isLoading && <div className="h-48 animate-pulse rounded-2xl bg-ink-100" />}

          {isError && (
            <div className="u-alert u-alert-error">
              <span>Couldn't load {teacherName}'s profile. Try again in a moment.</span>
            </div>
          )}

          {profile && (
            <div className="flex flex-col gap-4">
              <p className="u-body text-ink-600">
                This goes only to {teacherName} - it's not shown to any other teacher, and it never expires. Pick
                what you want from what they actually offer:
              </p>

              <div className="u-field">
                <label className="u-label" htmlFor="lwt-subject">Subject</label>
                <select id="lwt-subject" className="u-select" value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
                  {profile.subjects.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>

              <div className="u-field">
                <span className="u-label">Language</span>
                <div className="mt-1 flex flex-wrap gap-2">
                  {profile.languages.map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      className={
                        "u-chip u-chip-sm " + (languageIds.includes(l.id) ? "border-pine-500 bg-pine-50 text-pine-900" : "")
                      }
                      aria-pressed={languageIds.includes(l.id)}
                      onClick={() => toggleLanguage(l.id)}
                    >
                      {l.name}
                    </button>
                  ))}
                </div>
              </div>

              <div className="u-field">
                <label className="u-label" htmlFor="lwt-slot">When</label>
                {usableSlots.length === 0 ? (
                  <p className="u-fine mt-1 text-ink-600">
                    This teacher hasn't set any availability yet - try again once they have.
                  </p>
                ) : (
                  <select id="lwt-slot" className="u-select" value={slotId} onChange={(e) => setSlotId(e.target.value)}>
                    {usableSlots.map((s) => (
                      <option key={s.id} value={s.id}>
                        {DAY_NAMES[s.day_of_week]}, {fmtTime(s.start_time)}–{fmtTime(s.end_time)} ({s.timezone})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-ink-200 px-5 py-4">
          <button
            type="button"
            className="u-btn-primary u-btn-lg w-full"
            onClick={submit}
            disabled={sending || !profile || usableSlots.length === 0}
            data-loading={sending || undefined}
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
