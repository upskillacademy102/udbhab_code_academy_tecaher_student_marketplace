import { Routes, Route, Navigate } from "react-router-dom";
import { Discover } from "@/routes/student/Discover";
import { Search } from "@/routes/student/Search";
import { TeacherDetail } from "@/routes/student/TeacherDetail";
import { Requirements } from "@/routes/student/Requirements";
import { RequirementDetail } from "@/routes/student/RequirementDetail";
import { Profile } from "@/routes/student/Profile";
import { Notifications } from "@/routes/Notifications";

/**
 * Routes the SPA owns.
 *
 * Anything not listed here is still a Django template — Settings and Report
 * an Issue stay there for now, and the whole teacher area follows in stage D.
 * The catch-all sends unknown paths back to Discover rather than painting a
 * blank SPA over a page Django owns.
 */
export function App() {
  return (
    <Routes>
      <Route path="/student/" element={<Discover />} />
      <Route path="/student/teachers/" element={<Search />} />
      <Route path="/student/teachers/:id/" element={<TeacherDetail />} />
      <Route path="/student/requirements/" element={<Requirements />} />
      <Route path="/student/requirements/:id/" element={<RequirementDetail />} />
      <Route path="/student/profile/" element={<Profile />} />
      <Route path="/student/notifications/" element={<Notifications />} />
      <Route path="*" element={<Navigate to="/student/" replace />} />
    </Routes>
  );
}
