import { Link } from "react-router-dom";

const LINKS = [
  { label: "Students", desc: "Name, email, and phone.", to: "/staff/admin/support/students/" },
  { label: "Teachers", desc: "Name, email, and phone.", to: "/staff/admin/support/teachers/" },
  { label: "Learning Partners", desc: "Name, email, and phone.", to: "/staff/admin/support/learning-partners/" },
  { label: "Onboarding Calls", desc: "Teacher video-interview requests.", to: "/staff/admin/support/onboarding-calls/" },
  { label: "Bug Calls", desc: "Bug reports that asked for a call.", to: "/staff/admin/support/bug-calls/" },
  { label: "Circulate a Message", desc: "Send an email and/or SMS.", to: "/staff/admin/support/circulate-message/" },
];

/**
 * Support-department admin's landing page - a simple set of shortcuts into
 * their restricted panel. The onboarding-call and bug-call queues (below)
 * get live counts here once those queues exist (Phases 3/4).
 */
export function Dashboard() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Support Dashboard</h1>
        <p className="u-fine mt-1">Contact info, calls, and circulated messages - nothing else.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {LINKS.map((l) => (
          <Link key={l.to} to={l.to} className="u-card u-card-pad flex flex-col gap-1 hover:bg-paper-sunk">
            <span className="font-medium text-ink-900">{l.label}</span>
            <span className="u-fine">{l.desc}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
