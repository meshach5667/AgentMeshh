import type { Charge, PricingRule } from '@/types';

/** Same formula as billing_service.hourly_resource_price (decimal strings are parsed as numbers for display). */
export function hourlyResourcePrice(rule: PricingRule, cpuCores: number, ramMb: number, vramMb: number): number {
  return (
    Number(rule.cpu_core_hour) * cpuCores +
    (Number(rule.ram_gb_hour) * ramMb) / 1024 +
    (Number(rule.vram_gb_hour) * vramMb) / 1024
  );
}

export function isFree(rule: PricingRule | null | undefined): boolean {
  if (!rule) return true;
  return [rule.cpu_core_hour, rule.ram_gb_hour, rule.vram_gb_hour, rule.input_tokens_per_million, rule.output_tokens_per_million].every(
    (v) => Number(v) === 0,
  );
}

export function sumAmounts(charges: Charge[], field: 'amount' | 'provider_amount' = 'amount'): number {
  return charges.reduce((t, c) => t + Number(c[field]), 0);
}

/** Paystack appends ?reference=...&trxref=... when it returns the customer to the callback URL. */
export function returnedReference(params: URLSearchParams): string | null {
  const ref = params.get('reference') || params.get('trxref');
  return ref && /^am-top-[0-9a-f]{24}$/.test(ref) ? ref : null;
}

/** Only send customers to Paystack's own checkout (never to a URL an attacker could have planted). */
export function isPaystackCheckout(url: string | null | undefined): url is string {
  if (!url) return false;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && (u.hostname === 'checkout.paystack.com' || u.hostname.endsWith('.paystack.com'));
  } catch {
    return false;
  }
}
