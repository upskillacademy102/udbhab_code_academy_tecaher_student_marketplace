import { Routes, Route, Navigate } from "react-router-dom";
import { Discover } from "@/routes/student/Discover";
import { Search } from "@/routes/student/Search";

/**
 * Routes the SPA owns so far.
 *
 * Everything not listed here is still served by Django, so the catch-all
 * sends unknown paths back to Discover rather than painting a blank SPA over
 * a page Django owns. Pages move across one at a time; the remaining student
 * routes and the teacher area follow.
 */
export function App() {
  return (
    <Routes>
      <Route path="/student/" element={<Discover />} />
      <Route path="/student/teachers/" element={<Search />} />
      <Route path="*" element={<Navigate to="/student/" replace />} />
    </Routes>
  );
}
