import { LPUserList } from "@/components/LPUserList";

export function Students() {
  return <LPUserList endpoint="/lp/students/" basePath="/staff/learning-partner/students/" noun="Students" />;
}
