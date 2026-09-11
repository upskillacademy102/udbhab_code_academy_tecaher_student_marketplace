import { describe, expect, it } from "vitest";
import { teacherRouteId } from "@/components/MatchCard";
import { scheduleText, bandFromTime } from "@/lib/intent";
import type { TeacherProfile } from "@/lib/types";

/**
 * Guards for bugs that actually shipped, not hypothetical ones.
 */

describe("teacherRouteId", () => {
  /**
   * The bug: a search row is a TeacherProfile, so `row.id` is the PROFILE
   * id — but /teachers/{id}/ is keyed on the Teacher id. Linking with the
   * profile id looked fine when clicked (sessionStorage hydrated the page)
   * and 404'd on refresh or a shared link, with the availability checker
   * silently failing too.
   */
  it("routes on the Teacher id, never the TeacherProfile id", () => {
    const row = {
      id: "profile-id",
      teacher: { id: "teacher-id" },
    } as unknown as TeacherProfile;

    expect(teacherRouteId(row)).toBe("teacher-id");
    expect(teacherRouteId(row)).not.toBe(row.id);
  });

  it("falls back to the row id when the nested teacher is missing", () => {
    const row = { id: "only-id" } as unknown as TeacherProfile;
    expect(teacherRouteId(row)).toBe("only-id");
  });
});

describe("scheduleText", () => {
  /**
   * The bug: day names were pluralised AND handed a plural part-of-day,
   * producing "Mondays mornings" on screen.
   */
  it("keeps the day singular and pluralises the part of day", () => {
    expect(scheduleText([1], "morning")).toBe("Monday mornings");
    expect(scheduleText([2, 4], "evening")).toBe("Tuesday & Thursday evenings");
  });

  it("lists three or four days before collapsing", () => {
    expect(scheduleText([1, 3, 5], "afternoon")).toBe("Monday, Wednesday & Friday afternoons");
  });

  /** Five or more used to read "most days evenings". */
  it("collapses five or more days without doubling the noun", () => {
    expect(scheduleText([1, 2, 3, 4, 5], "evening")).toBe("most evenings");
  });

  it("is empty when no days are chosen", () => {
    expect(scheduleText([], "evening")).toBe("");
  });
});

describe("bandFromTime", () => {
  it("maps a stored start time back to its band", () => {
    expect(bandFromTime("06:00")).toBe("morning");
    expect(bandFromTime("12:00")).toBe("afternoon");
    expect(bandFromTime("17:00")).toBe("evening");
  });

  it("defaults to evening for anything unrecognised", () => {
    expect(bandFromTime(null)).toBe("evening");
    expect(bandFromTime("03:00")).toBe("evening");
  });
});
