import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { OnboardingCall } from "@/lib/types";
import { JitsiCallPanel } from "@/routes/admin/support/JitsiCallPanel";

// A call that has ended but not yet been approved/rejected is remembered
// here so a refresh (or navigating away and back) can't dodge the decision.
const PENDING_KEY = "support-onboarding-decision-pending";

function readPending(): string | null {
  try {
    return localStorage.getItem(PENDING_KEY);
  } catch {
    return null;
  }
}
function writePending(teacherId: string | null) {
  try {
    if (teacherId) localStorage.setItem(PENDING_KEY, teacherId);
    else localStorage.removeItem(PENDING_KEY);
  } catch {
    /* private mode / blocked storage - the in-memory state still applies */
  }
}

/**
 * Support-department admin's onboarding-call queue: accept a teacher's
 * request (the call goes live for both sides), run the Jitsi call, and when
 * it ends a MANDATORY approve/reject decision blocks the page - it has no
 * close button and ignores Escape/backdrop clicks, and it re-opens after a
 * refresh until answered. "Yes" verifies only the teacher's video-interview
 * checklist item; "No" rejects it.
 */
export function OnboardingCalls() {
  const qc = useQueryClient();
  const [activeTeacherId, setActiveTeacherId] = useState<string | null>(null);
  const [decisionTeacherId, setDecisionTeacherId] = useState<string | null>(readPending);
  const [actionError, setActionError] = useState("");
  const [decisionError, setDecisionError] = useState("");

  const callsQ = useQuery({
    queryKey: ["support-onboarding-calls"],
    queryFn: () => api.list<OnboardingCall>("/admin/onboarding-calls/"),
    refetchInterval: 10_000,
  });
  const calls = callsQ.data?.items ?? [];

  const meQ = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: { id: string; first_name: string } }>("/auth/me/"),
  });
  const myId = meQ.data?.user.id;

  // A remembered decision for a call that is no longer open (already
  // decided elsewhere) must not trap the admin behind a modal forever.
  useEffect(() => {
    if (!decisionTeacherId || !callsQ.data) return;
    const still = callsQ.data.items.find(
      (c) => c.teacher_id === decisionTeacherId && c.item_status === "submitted",
    );
    if (!still) {
      writePending(null);
      setDecisionTeacherId(null);
    }
  }, [decisionTeacherId, callsQ.data]);

  // Warn on tab close / reload while a decision is outstanding. Best-effort:
  // a browser can't be forced to stay open, which is why the pending state
  // is also persisted above.
  useEffect(() => {
    if (!decisionTeacherId) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [decisionTeacherId]);

  const acceptMutation = useMutation({
    mutationFn: (teacherId: string) => api.post(`/admin/onboarding-calls/${teacherId}/accept/`),
    onSuccess: (_data, teacherId) => {
      setActionError("");
      setActiveTeacherId(teacherId);
      qc.invalidateQueries({ queryKey: ["support-onboarding-calls"] });
    },
    onError: (err) => {
      setActionError(err instanceof ApiError ? err.message : "Couldn't accept that call.");
      qc.invalidateQueries({ queryKey: ["support-onboarding-calls"] });
    },
  });

  const decideMutation = useMutation({
    mutationFn: (vars: { teacherId: string; status: "verified" | "rejected" }) =>
      api.post(`/admin/teacher-profiles/${vars.teacherId}/verification-items/video_interview/`, {
        status: vars.status,
      }),
    onSuccess: () => {
      setDecisionError("");
      writePending(null);
      setDecisionTeacherId(null);
      qc.invalidateQueries({ queryKey: ["support-onboarding-calls"] });
    },
    onError: (err) =>
      setDecisionError(err instanceof ApiError ? err.message : "Couldn't save your decision. Try again."),
  });

  function handleCallEnd(teacherId: string) {
    setActiveTeacherId(null);
    writePending(teacherId);
    setDecisionTeacherId(teacherId);
  }

  const decisionCall = calls.find((c) => c.teacher_id === decisionTeacherId);
  const decisionName = decisionCall?.teacher_name || decisionCall?.teacher_email || "this teacher";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Onboarding Calls</h1>
        <p className="u-fine mt-1">
          Teacher video-interview requests. Accept one to start the call; when it ends you'll be asked
          to approve or reject the teacher.
        </p>
      </div>

      {actionError && <div className="u-alert u-alert-error">{actionError}</div>}

      {!callsQ.isLoading && calls.length === 0 && (
        <div className="u-card u-card-pad text-center text-ink-500">No onboarding calls waiting.</div>
      )}

      <div className="flex flex-col gap-4">
        {calls.map((c) => {
          const live = !!c.call_started_at;
          const mine = live && !!myId && c.assigned_admin_id === myId;
          const inCall = activeTeacherId === c.teacher_id;
          return (
            <div key={c.id} className="u-card u-card-pad flex flex-col gap-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium text-ink-900">{c.teacher_name || c.teacher_email}</p>
                  <p className="u-fine">
                    {c.teacher_email} · requested {new Date(c.created_at).toLocaleString("en-IN")}
                  </p>
                </div>
                <span className="u-badge u-badge-ink capitalize">
                  {live ? (mine ? "Live - yours" : "In progress") : "Waiting"}
                </span>
              </div>

              {!live && (
                <button
                  type="button"
                  className="u-btn-primary u-btn-sm self-start"
                  disabled={acceptMutation.isPending}
                  onClick={() => acceptMutation.mutate(c.teacher_id)}
                >
                  Accept &amp; start call
                </button>
              )}

              {live && !mine && (
                <p className="u-fine">
                  Being handled by {c.assigned_admin_name || c.assigned_admin_email || "another admin"}.
                </p>
              )}

              {mine && !inCall && (
                <button
                  type="button"
                  className="u-btn-secondary u-btn-sm self-start"
                  onClick={() => setActiveTeacherId(c.teacher_id)}
                >
                  Join call
                </button>
              )}

              {mine && inCall && c.room_name && (
                <JitsiCallPanel
                  roomName={c.room_name}
                  displayName="Udbhab Support"
                  onCallEnd={() => handleCallEnd(c.teacher_id)}
                />
              )}
            </div>
          );
        })}
      </div>

      {decisionTeacherId && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 p-4"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="decision-title"
        >
          <div className="u-card u-card-pad flex w-full max-w-md flex-col gap-4 bg-white">
            <div>
              <h2 id="decision-title" className="u-h3">Approve this teacher?</h2>
              <p className="u-fine mt-1">
                The call with {decisionName} has ended. You must approve or reject their onboarding
                video call before you can continue.
              </p>
            </div>
            {decisionError && <div className="u-alert u-alert-error">{decisionError}</div>}
            <div className="flex gap-3">
              <button
                type="button"
                className="u-btn-primary flex-1"
                disabled={decideMutation.isPending}
                onClick={() => decideMutation.mutate({ teacherId: decisionTeacherId, status: "verified" })}
              >
                Yes, approve
              </button>
              <button
                type="button"
                className="u-btn-secondary flex-1"
                disabled={decideMutation.isPending}
                onClick={() => decideMutation.mutate({ teacherId: decisionTeacherId, status: "rejected" })}
              >
                No, reject
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
