import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { BroadcastMessage, SupportContactUser } from "@/lib/types";

const ROLES = ["student", "teacher", "learning_partner"] as const;
const ROLE_LABELS: Record<(typeof ROLES)[number], string> = {
  student: "Students",
  teacher: "Teachers",
  learning_partner: "Learning Partners",
};

/**
 * Support-department admin's "circulate a message" panel - compose an
 * email and/or SMS, pick recipients from the same trimmed People lists
 * (Students/Teachers/Learning Partners) Support already has, and send.
 * Below the form: a history of what's been sent.
 */
export function CirculateMessage() {
  const qc = useQueryClient();
  const [role, setRole] = useState<(typeof ROLES)[number]>("student");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Map<string, SupportContactUser>>(new Map());
  const [viaEmail, setViaEmail] = useState(true);
  const [viaSms, setViaSms] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [sendError, setSendError] = useState("");
  const [sendOk, setSendOk] = useState("");

  const peopleQ = useQuery({
    queryKey: ["support-broadcast-people", role, search],
    queryFn: () =>
      api.list<SupportContactUser>("/admin/users/", { params: { role, search: search || undefined } }),
  });
  const people = peopleQ.data?.items ?? [];

  const historyQ = useQuery({
    queryKey: ["support-broadcast-history"],
    queryFn: () => api.list<BroadcastMessage>("/admin/broadcast-messages/"),
  });
  const history = historyQ.data?.items ?? [];

  function toggle(u: SupportContactUser) {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(u.id)) next.delete(u.id);
      else next.set(u.id, u);
      return next;
    });
  }

  const sendMutation = useMutation({
    mutationFn: () =>
      api.post<BroadcastMessage>("/admin/broadcast-messages/", {
        subject,
        body,
        via_email: viaEmail,
        via_sms: viaSms,
        recipient_ids: Array.from(selected.keys()),
      }),
    onSuccess: () => {
      setSendError("");
      setSendOk(`Sent to ${selected.size} recipient(s).`);
      setSubject("");
      setBody("");
      setSelected(new Map());
      qc.invalidateQueries({ queryKey: ["support-broadcast-history"] });
    },
    onError: (err) => {
      setSendOk("");
      setSendError(err instanceof ApiError ? err.message : "Couldn't send that message.");
    },
  });

  function handleSend() {
    setSendError("");
    setSendOk("");
    if (selected.size === 0) {
      setSendError("Select at least one recipient.");
      return;
    }
    if (!viaEmail && !viaSms) {
      setSendError("Choose at least one channel: email or SMS.");
      return;
    }
    if (!subject.trim() || !body.trim()) {
      setSendError("Subject and message are both required.");
      return;
    }
    sendMutation.mutate();
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Circulate a Message</h1>
        <p className="u-fine mt-1">
          Send an email and/or SMS to students, teachers, or learning partners. This is the only
          channel for manual messages - automatic OTP verification is separate.
        </p>
      </div>

      <div className="u-card u-card-pad flex flex-col gap-4">
        <div>
          <h2 className="u-h3">1. Pick recipients</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {ROLES.map((r) => (
              <button
                key={r}
                type="button"
                className={r === role ? "u-btn-primary u-btn-sm" : "u-btn-secondary u-btn-sm"}
                onClick={() => setRole(r)}
              >
                {ROLE_LABELS[r]}
              </button>
            ))}
            <input
              className="u-input ml-auto w-56"
              placeholder="Search name, email, mobile"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="u-card mt-3 max-h-72 overflow-y-auto">
            <table className="w-full text-left text-[0.875rem]">
              <thead className="sticky top-0 bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
                <tr>
                  <th className="px-4 py-2.5" />
                  <th className="px-4 py-2.5">Name</th>
                  <th className="px-4 py-2.5">Email</th>
                  <th className="px-4 py-2.5">Phone</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {people.map((u) => (
                  <tr key={u.id} className="cursor-pointer hover:bg-paper-sunk" onClick={() => toggle(u)}>
                    <td className="px-4 py-2.5">
                      <input type="checkbox" checked={selected.has(u.id)} onChange={() => toggle(u)} />
                    </td>
                    <td className="px-4 py-2.5 font-medium text-ink-900">{u.full_name || "(no name)"}</td>
                    <td className="px-4 py-2.5 text-ink-600">{u.email}</td>
                    <td className="px-4 py-2.5 text-ink-600">{u.mobile || "—"}</td>
                  </tr>
                ))}
                {!peopleQ.isLoading && people.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-ink-500">No matches.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="u-fine mt-2">{selected.size} recipient(s) selected across all sections.</p>
        </div>

        <div>
          <h2 className="u-h3">2. Choose channel(s)</h2>
          <div className="mt-2 flex gap-4">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={viaEmail} onChange={(e) => setViaEmail(e.target.checked)} />
              Email
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={viaSms} onChange={(e) => setViaSms(e.target.checked)} />
              SMS
            </label>
          </div>
        </div>

        <div>
          <h2 className="u-h3">3. Write the message</h2>
          <input
            className="u-input mt-2 w-full"
            placeholder="Subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            maxLength={200}
          />
          <textarea
            className="u-input mt-2 w-full"
            placeholder="Message"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            maxLength={5000}
          />
        </div>

        {sendError && <div className="u-alert u-alert-error">{sendError}</div>}
        {sendOk && <div className="u-alert u-alert-success">{sendOk}</div>}

        <div>
          <button
            type="button"
            className="u-btn-primary"
            disabled={sendMutation.isPending}
            onClick={handleSend}
          >
            {sendMutation.isPending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="u-h3">Send history</h2>
        {history.length === 0 && (
          <div className="u-card u-card-pad text-center text-ink-500">Nothing circulated yet.</div>
        )}
        {history.length > 0 && (
          <div className="u-card overflow-hidden">
            <table className="w-full text-left text-[0.875rem]">
              <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
                <tr>
                  <th className="px-4 py-2.5">Subject</th>
                  <th className="px-4 py-2.5">Channel(s)</th>
                  <th className="px-4 py-2.5">Recipients</th>
                  <th className="px-4 py-2.5">Sent by</th>
                  <th className="px-4 py-2.5">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {history.map((m) => (
                  <tr key={m.id}>
                    <td className="px-4 py-3 font-medium text-ink-900">{m.subject}</td>
                    <td className="px-4 py-3 text-ink-600">
                      {[m.via_email && "Email", m.via_sms && "SMS"].filter(Boolean).join(" + ")}
                    </td>
                    <td className="px-4 py-3 text-ink-600">{m.recipient_count}</td>
                    <td className="px-4 py-3 text-ink-600">{m.sent_by_name || m.sent_by_email || "—"}</td>
                    <td className="px-4 py-3 text-ink-500">{new Date(m.created_at).toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
