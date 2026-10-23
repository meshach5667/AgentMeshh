import { AI_STATUS_HELP, DEFAULT_LIMITS, MAX_DURATION_HOURS, validateAiRequest } from '../ai';
import type { AiRunStatus } from '@/types';

describe('validateAiRequest', () => {
  const text = 'A small chat model for support questions';

  it('accepts the defaults', () => {
    expect(validateAiRequest(text, DEFAULT_LIMITS)).toEqual([]);
  });

  it('requires a description and a positive budget', () => {
    expect(validateAiRequest('  ', DEFAULT_LIMITS)).toContain('Describe what you want to deploy.');
    expect(validateAiRequest(text, { ...DEFAULT_LIMITS, max_spend: '0' })).toContain('Maximum spend must be more than zero.');
    expect(validateAiRequest(text, { ...DEFAULT_LIMITS, max_spend: 'abc' })).toHaveLength(1);
  });

  it('enforces the platform ceilings the server enforces', () => {
    expect(validateAiRequest(text, { ...DEFAULT_LIMITS, max_duration_hours: MAX_DURATION_HOURS + 1 })).toHaveLength(1);
    expect(validateAiRequest(text, { ...DEFAULT_LIMITS, max_recovery_attempts: 9 })).toHaveLength(1);
    expect(validateAiRequest(text, { ...DEFAULT_LIMITS, max_ram_mb: 100 })).toHaveLength(1);
    expect(validateAiRequest(text, { ...DEFAULT_LIMITS, allowed_runtimes: [] })).toContain('Allow at least one runtime.');
    expect(validateAiRequest(text, { ...DEFAULT_LIMITS, max_duration_hours: NaN })).toHaveLength(1);
  });

  it('explains every run status', () => {
    const statuses: AiRunStatus[] = [
      'PLANNING', 'SUBMITTING', 'DEPLOYING', 'VERIFYING', 'READY', 'RECOVERING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED',
    ];
    for (const s of statuses) expect(AI_STATUS_HELP[s]).toBeTruthy();
  });
});
