import { Routes, Route, Navigate } from "react-router-dom";
import { Discover } from "@/routes/student/Discover";

/**
 * Stage B mounts one route: the student's Discover page.
 *
 * Every other student and teacher page is still served by Django, so the
 * router deliberately does NOT catch everything — an unknown path falls back
 * to Discover rather than rendering a blank SPA over a page Django owns. The
 * remaining routes arrive in stages C and D.
 */
export function App() {
  return (
    <Routes>
      <Route path="/student/" element={<Discover />} />
      <Route path="*" element={<Navigate to="/student/" replace />} />
    </Routes>
  );
}
