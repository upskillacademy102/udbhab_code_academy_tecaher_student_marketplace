import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { AdminSupportTicket } from "@/lib/types";
import { JitsiCallPanel } from "@/routes/admin/support/JitsiCallPanel";

/**
 * Support-department admin's call-only bug-ticket queue - only tickets
 * where the reporter asked for a video or phone call show up here (the
 * general "browse every bug ticket" list was removed for Support; the API
 * side, AdminSupportTicketListView.get_queryset(), does the narrowing).
 */
export function BugCalls() {
  const qc = useQueryClient();
  const [activeCallTicketId, setActiveCallTicketId] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolution, setResolution] = useState("");
  const [actionError, setActionError] = useState("");

  const ticketsQ = useQuery({
    queryKey: ["support-bug-calls"],
    queryFn: () => api.list<AdminSupportTicket>("/admin/support-tickets/"),
    refetchInterval: 15_000,
  });
  const tickets = ticketsQ.data?.items ?? [];

  const meQ = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: { id: string } }>("/auth/me/"),
  });
  const myId = meQ.data?.user.id;

  const acceptMutation = useMutation({
    mutationFn: (id: string) => api.post(`/admin/support-tickets/${id}/accept/`),
    onSuccess: () => {
      setActionError("");
      qc.invalidateQueries({ queryKey: ["support-bug-calls"] });
    },
    onError: (err) => setActionError(err instanceof ApiError ? err.message : "Couldn't accept that ticket."),
  });

  const resolveMutation = useMutation({
    mutationFn: (vars: { id: string; resolution: string }) =>
      api.post(`/admin/support-tickets/${vars.id}/resolve/`, { resolution: vars.resolution }),
    onSuccess: () => {
      setActionError("");
      setResolvingId(null);
      setResolution("");
      setActiveCallTicketId(null);
      qc.invalidateQueries({ queryKey: ["support-bug-calls"] });
    },
    onError: (err) => setActionError(err instanceof ApiError ? err.message : "Couldn't resolve that ticket."),
  });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Bug Calls</h1>
        <p className="u-fine mt-1">Bug reports where the reporter asked for a video or phone call.</p>
      </div>

      {actionError && <div className="u-alert u-alert-error">{actionError}</div>}

      {!ticketsQ.isLoading && tickets.length === 0 && (
        <div className="u-card u-card-pad text-center text-ink-500">No call requests right now.</div>
      )}

      <div className="flex flex-col gap-4">
        {tickets.map((t) => {
          const mine = t.status === "assigned" && !!myId && t.assigned_admin_ids.includes(myId);
          return (
            <div key={t.id} className="u-card u-card-pad flex flex-col gap-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium text-ink-900">{t.subject}</p>
                  <p className="u-fine">
                    {t.reporter_name || t.reporter_email} ({t.reporter_role}) ·{" "}
                    {t.contact_preference === "video_call" ? "Video call requested" : "Phone call requested"}
                  </p>
                </div>
                <span className="u-badge u-badge-ink capitalize">{t.status}</span>
              </div>
              <p className="text-ink-700">{t.description}</p>

              {t.status === "open" && (
                <button
                  type="button"
                  className="u-btn-primary u-btn-sm self-start"
                  disabled={acceptMutation.isPending}
                  onClick={() => acceptMutation.mutate(t.id)}
                >
                  Accept
                </button>
              )}

              {mine && t.contact_preference === "phone_call" && (
                <div className="u-alert">
                  Call the reporter at: <span className="font-mono font-medium">{t.reporter_mobile || "—"}</span>
                </div>
              )}

              {mine && t.contact_preference === "video_call" && activeCallTicketId !== t.id && (
                <button
                  type="button"
                  className="u-btn-secondary u-btn-sm self-start"
                  onClick={() => setActiveCallTicketId(t.id)}
                >
                  Join video call
                </button>
              )}

              {mine && t.contact_preference === "video_call" && activeCallTicketId === t.id && (
                <JitsiCallPanel
                  roomName={`tm-support-ticket-${t.id}`}
                  onCallEnd={() => setActiveCallTicketId(null)}
                />
              )}

              {mine && (
                <div className="flex flex-wrap items-center gap-2">
                  {resolvingId === t.id ? (
                    <>
                      <input
                        className="u-input flex-1"
                        placeholder="Resolution notes (optional)"
                        value={resolution}
                        onChange={(e) => setResolution(e.target.value)}
                      />
                      <button
                        type="button"
                        className="u-btn-primary u-btn-sm"
                        disabled={resolveMutation.isPending}
                        onClick={() => resolveMutation.mutate({ id: t.id, resolution })}
                      >
                        Confirm resolve
                      </button>
                      <button
                        type="button"
                        className="u-btn-ghost u-btn-sm"
                        onClick={() => {
                          setResolvingId(null);
                          setResolution("");
                        }}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="u-btn-secondary u-btn-sm"
                      onClick={() => setResolvingId(t.id)}
                    >
                      Resolve ticket
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
