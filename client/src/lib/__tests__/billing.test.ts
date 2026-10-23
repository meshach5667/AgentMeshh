import { hourlyResourcePrice, isFree, isPaystackCheckout, returnedReference, sumAmounts } from '../billing';
import type { Charge, PricingRule } from '@/types';

const rule = (over: Partial<PricingRule> = {}): PricingRule => ({
  id: 'r',
  version: 1,
  currency: 'NGN',
  cpu_core_hour: '10.00000000',
  ram_gb_hour: '20.00000000',
  vram_gb_hour: '0E-8',
  input_tokens_per_million: '1000',
  output_tokens_per_million: '2000',
  platform_fee_rate: '0.1000',
  effective_from: '2026-10-21T00:00:00',
  notes: null,
  created_at: '2026-10-21T00:00:00',
  ...over,
});

describe('billing helpers', () => {
  it('prices a reservation like the server (1 core + 1 GB = 30 NGN/h in tests/test_billing.py)', () => {
    expect(hourlyResourcePrice(rule(), 1, 1024, 0)).toBe(30);
    expect(hourlyResourcePrice(rule({ vram_gb_hour: '50' }), 2, 2048, 4096)).toBe(2 * 10 + 2 * 20 + 4 * 50);
  });

  it('treats a missing or all-zero price list as free', () => {
    expect(isFree(null)).toBe(true);
    expect(isFree(rule({ cpu_core_hour: '0', ram_gb_hour: '0', input_tokens_per_million: '0', output_tokens_per_million: '0' }))).toBe(true);
    expect(isFree(rule())).toBe(false);
  });

  it('accepts only AgentMesh top-up references from the Paystack return URL', () => {
    const ref = 'am-top-' + 'a'.repeat(24);
    expect(returnedReference(new URLSearchParams({ reference: ref, trxref: ref }))).toBe(ref);
    expect(returnedReference(new URLSearchParams({ trxref: ref }))).toBe(ref);
    expect(returnedReference(new URLSearchParams({ reference: '../../admin' }))).toBeNull();
    expect(returnedReference(new URLSearchParams())).toBeNull();
  });

  it('sums decimal-string amounts', () => {
    const c = (amount: string, provider_amount: string) => ({ amount, provider_amount }) as Charge;
    expect(sumAmounts([c('1.5', '1.35'), c('2.25', '2.025')])).toBeCloseTo(3.75);
    expect(sumAmounts([c('1.5', '1.35')], 'provider_amount')).toBeCloseTo(1.35);
  });
});

it('redirects only to Paystack checkout over https', () => {
  expect(isPaystackCheckout('https://checkout.paystack.com/abc')).toBe(true);
  expect(isPaystackCheckout('http://checkout.paystack.com/abc')).toBe(false);
  expect(isPaystackCheckout('https://checkout.paystack.com.evil.example/abc')).toBe(false);
  expect(isPaystackCheckout('javascript:alert(1)')).toBe(false);
  expect(isPaystackCheckout(null)).toBe(false);
});
