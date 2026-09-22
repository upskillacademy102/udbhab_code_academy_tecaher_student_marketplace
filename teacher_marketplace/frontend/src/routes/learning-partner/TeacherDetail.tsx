import { LPUserDetail } from "@/components/LPUserDetail";

export function TeacherDetail() {
  return (
    <LPUserDetail
      endpointBase="/lp/teachers/"
      backTo="/staff/learning-partner/teachers/"
      backLabel="All teachers"
    />
  );
}
