import { LPUserDetail } from "@/components/LPUserDetail";

export function StudentDetail() {
  return (
    <LPUserDetail
      endpointBase="/lp/students/"
      backTo="/staff/learning-partner/students/"
      backLabel="All students"
    />
  );
}
