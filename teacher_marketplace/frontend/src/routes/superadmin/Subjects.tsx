import { TaxonomyManager } from "@/components/TaxonomyManager";

export function Subjects() {
  return <TaxonomyManager kind="subjects" canWrite={true} />;
}
