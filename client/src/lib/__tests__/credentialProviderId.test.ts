import { describe, expect, it } from 'vitest';

import { credentialProviderId } from '../credentialProviderId';

describe('credentialProviderId', () => {
  it('uses a plugin credential id as the catalogue provider id', () => {
    expect(credentialProviderId('openai', 'openaiChatModel')).toBe('openai');
    expect(credentialProviderId('openai_compatible', 'openaiCompatibleChatModel')).toBe('openai_compatible');
    expect(credentialProviderId('telegram', 'telegramSend')).toBe('telegram');
  });

  it('maps the legacy credential names', () => {
    expect(credentialProviderId('openaiApi', undefined)).toBe('openai');
    expect(credentialProviderId('googleMapsApi', undefined)).toBe('google_maps');
  });

  it('falls back to Google Maps for location nodes that declare no credential', () => {
    expect(credentialProviderId(undefined, 'gmaps_locations')).toBe('google_maps');
    expect(credentialProviderId(undefined, 'calculatorTool')).toBe('');
  });
});
