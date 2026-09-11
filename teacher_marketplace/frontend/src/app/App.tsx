import { Routes, Route, Navigate } from "react-router-dom";
import { Discover } from "@/routes/student/Discover";
import { Search } from "@/routes/student/Search";
import { TeacherDetail } from "@/routes/student/TeacherDetail";
import { Requirements } from "@/routes/student/Requirements";
import { RequirementDetail } from "@/routes/student/RequirementDetail";
import { Profile } from "@/routes/student/Profile";
import { Notifications } from "@/routes/Notifications";
import { TeacherDashboard } from "@/routes/teacher/Dashboard";
import { Leads } from "@/routes/teacher/Leads";
import { LeadDetail } from "@/routes/teacher/LeadDetail";
import { Assignments } from "@/routes/teacher/Assignments";

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

      <Route path="/teacher/" element={<TeacherDashboard />} />
      <Route path="/teacher/leads/" element={<Leads />} />
      <Route path="/teacher/leads/:id/" element={<LeadDetail />} />
      <Route path="/teacher/assignments/" element={<Assignments />} />
      <Route path="/teacher/notifications/" element={<Notifications />} />

      <Route path="*" element={<Fallback />} />
    </Routes>
  );
}

/**
 * Unknown paths go to the right home for whoever is signed in. The shell
 * template stamps the role on <body>, so the SPA never has to guess and a
 * teacher is never bounced into the student area.
 */
function Fallback() {
  const role = document.body.dataset.role;
  return <Navigate to={role === "teacher" ? "/teacher/" : "/student/"} replace />;
}
