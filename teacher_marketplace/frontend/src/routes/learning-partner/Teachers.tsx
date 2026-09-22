import { LPUserList } from "@/components/LPUserList";

export function Teachers() {
  return <LPUserList endpoint="/lp/teachers/" basePath="/staff/learning-partner/teachers/" noun="Teachers" />;
}
