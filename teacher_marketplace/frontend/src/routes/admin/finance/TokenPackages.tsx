import type { TokenPackage } from "@/lib/types";
import { PricingCatalog } from "@/routes/admin/finance/PricingCatalog";

export function TokenPackages() {
  return (
    <PricingCatalog<TokenPackage>
      title="Token Packages"
      desc="Current pricing. Request a change for Super Admin to approve."
      listPath="/token-packages/"
      targetType="token_package"
      toItem={(pkg) => ({
        id: pkg.id,
        label: pkg.name,
        currentValue: parseFloat(pkg.price),
        isCurrency: true,
      })}
    />
  );
}
