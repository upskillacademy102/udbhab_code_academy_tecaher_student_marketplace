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
import { TeachingProfile } from "@/routes/teacher/TeachingProfile";
import { Availability } from "@/routes/teacher/Availability";
import { Plan } from "@/routes/teacher/Plan";
import { AdminAccountRequests } from "@/routes/superadmin/AdminAccountRequests";
import { Departments } from "@/routes/superadmin/Departments";
import { Dashboard as SuperAdminDashboard } from "@/routes/superadmin/Dashboard";
import { Users as SuperAdminUsers } from "@/routes/superadmin/Users";
import { UserDetail as SuperAdminUserDetail } from "@/routes/superadmin/UserDetail";
import { Sanctions } from "@/routes/superadmin/Sanctions";
import { Dashboard as AdminDashboard } from "@/routes/admin/Dashboard";
import { Users as AdminUsers } from "@/routes/admin/Users";
import { UserDetail as AdminUserDetail } from "@/routes/admin/UserDetail";
import { Subjects as AdminSubjects } from "@/routes/admin/Subjects";
import { Languages as AdminLanguages } from "@/routes/admin/Languages";
import { Subjects as SuperAdminSubjects } from "@/routes/superadmin/Subjects";
import { Languages as SuperAdminLanguages } from "@/routes/superadmin/Languages";
import { FakeLeadReports } from "@/routes/superadmin/FakeLeadReports";
import { LeadsBrowser } from "@/routes/superadmin/LeadsBrowser";
import { AuditLog } from "@/routes/superadmin/AuditLog";

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
      <Route path="/teacher/profile/" element={<TeachingProfile />} />
      <Route path="/teacher/availability/" element={<Availability />} />
      <Route path="/teacher/plan/" element={<Plan />} />
      {/* Old nav split these three; they are one page now. */}
      <Route path="/teacher/subscription/" element={<Navigate to="/teacher/plan/" replace />} />
      <Route path="/teacher/tokens/" element={<Navigate to="/teacher/plan/" replace />} />
      <Route path="/teacher/payments/" element={<Navigate to="/teacher/plan/" replace />} />
      <Route path="/teacher/notifications/" element={<Notifications />} />

      {/* Admin only (Phase 4) - read-only mirror of the Super Admin screens */}
      <Route path="/staff/admin/" element={<AdminDashboard />} />
      <Route path="/staff/admin/users/" element={<AdminUsers />} />
      <Route path="/staff/admin/users/:id/" element={<AdminUserDetail />} />
      <Route path="/staff/admin/subjects/" element={<AdminSubjects />} />
      <Route path="/staff/admin/languages/" element={<AdminLanguages />} />

      {/* Super Admin only - see apps/web/urls.py's "NEW STAFF SPA" section */}
      <Route path="/staff/superadmin/" element={<SuperAdminDashboard />} />
      <Route path="/staff/superadmin/users/" element={<SuperAdminUsers />} />
      <Route path="/staff/superadmin/users/:id/" element={<SuperAdminUserDetail />} />
      <Route path="/staff/superadmin/sanctions/" element={<Sanctions />} />
      <Route path="/staff/superadmin/admin-account-requests/" element={<AdminAccountRequests />} />
      <Route path="/staff/superadmin/departments/" element={<Departments />} />
      <Route path="/staff/superadmin/subjects/" element={<SuperAdminSubjects />} />
      <Route path="/staff/superadmin/languages/" element={<SuperAdminLanguages />} />
      <Route path="/staff/superadmin/fake-lead-reports/" element={<FakeLeadReports />} />
      <Route path="/staff/superadmin/leads/" element={<LeadsBrowser />} />
      <Route path="/staff/superadmin/audit/" element={<AuditLog />} />

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
  if (role === "teacher") return <Navigate to="/teacher/" replace />;
  if (role === "admin") return <Navigate to="/staff/admin/" replace />;
  if (role === "superadmin") return <Navigate to="/staff/superadmin/" replace />;
  return <Navigate to="/student/" replace />;
}
