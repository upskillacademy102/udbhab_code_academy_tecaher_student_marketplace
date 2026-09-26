import type { LeadUnlockPricing } from "@/lib/types";
import { titleCase } from "@/lib/ui";
import { PricingCatalog } from "@/routes/admin/finance/PricingCatalog";

export function LeadPricing() {
  return (
    <PricingCatalog<LeadUnlockPricing>
      title="Lead Unlock Pricing"
      desc="Current pricing, in tokens. Request a change for Super Admin to approve."
      listPath="/lead-unlock-pricing/"
      targetType="lead_unlock_pricing"
      toItem={(row) => ({
        id: row.id,
        label: titleCase(row.tier),
        currentValue: row.token_cost,
        isCurrency: false,
      })}
    />
  );
}
