import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/lib/ui";

/**
 * Notifications — shared by students and teachers.
 *
 * Unread is carried by a left edge and weight rather than a coloured dot on
 * every row: a list where most rows are unread turns a dot-per-row into
 * noise, while an edge reads as a group at a glance.
 */

interface Notification {
  id: string;
  title?: string | null;
  message?: string | null;
  body?: string | null;
  is_read: boolean;
  created_at: string;
  notification_type?: string | null;
}

function when(iso: string): string {
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function Notifications() {
  const qc = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.list<Notification>("/notifications/", { params: { page_size: 50 } }),
  });

  const items = data?.items ?? [];
  const unread = items.filter((n) => !n.is_read);

  async function markRead(ids: string[]) {
    if (!ids.length) return;
    try {
      await api.post("/notifications/mark-read/", { notification_ids: ids }, { silent: true });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't mark those as read.");
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">
          {isLoading ? "Loading…" : unread.length ? `${unread.length} new` : "Notifications"}
        </h1>
        {unread.length > 0 && (
          <button type="button" className="u-btn-secondary" onClick={() => markRead(unread.map((n) => n.id))}>
            Mark all as read
          </button>
        )}
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      )}

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load these."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <section className="u-card flex flex-col items-center gap-3 px-6 py-14 text-center">
          <h2 className="u-h3">Nothing yet</h2>
          <p className="u-body max-w-prose text-ink-600">
            When a teacher gets in touch or something changes on a request, it'll show up here.
          </p>
        </section>
      )}

      {items.length > 0 && (
        <ul className="flex flex-col gap-2">
          {items.map((n) => (
            <li key={n.id}>
              <article
                className={
                  "u-card flex items-start gap-3 p-4 " +
                  (n.is_read ? "" : "border-l-[3px] border-l-pine-600 bg-pine-50")
                }
              >
                <div className="min-w-0 flex-1">
                  {n.title && (
                    <p className={"text-[0.9375rem] leading-snug " + (n.is_read ? "font-medium text-ink-800" : "font-semibold text-ink-900")}>
                      {n.title}
                    </p>
                  )}
                  {(n.message || n.body) && (
                    <p className="u-fine mt-1 text-ink-600">{n.message ?? n.body}</p>
                  )}
                  <p className="mt-1.5 text-[0.6875rem] uppercase tracking-wider text-ink-400">{when(n.created_at)}</p>
                </div>
                {!n.is_read && (
                  <button type="button" className="u-btn-ghost u-btn-sm shrink-0" onClick={() => markRead([n.id])}>
                    Mark read
                  </button>
                )}
              </article>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
