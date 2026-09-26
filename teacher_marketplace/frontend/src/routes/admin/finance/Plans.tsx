import type { Plan } from "@/lib/types";
import { PricingCatalog } from "@/routes/admin/finance/PricingCatalog";

export function Plans() {
  return (
    <PricingCatalog<Plan>
      title="Subscription Plans"
      desc="Current pricing. Request a change for Super Admin to approve."
      listPath="/subscriptions/plans/"
      targetType="subscription_plan"
      toItem={(plan) => ({
        id: plan.id,
        label: plan.name,
        currentValue: parseFloat(plan.monthly_price ?? "0"),
        isCurrency: true,
      })}
    />
  );
}
