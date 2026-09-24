/**
 * The toolbar re-fetches its global model list when this signature changes,
 * so it must change for every edit to what the picker offers, including a
 * second endpoint, which leaves the count of stored providers unchanged.
 */

import { describe, expect, it } from 'vitest';

import { storedCredentialSignature, type ServerProviderConfig } from '../useCatalogueQuery';

const provider = (id: string, stored: boolean, endpoints?: ServerProviderConfig['endpoints']): ServerProviderConfig => ({
  id,
  name: id,
  category: 'ai',
  category_label: 'AI',
  color: '',
  kind: 'apiKey',
  stored,
  endpoints,
});

const endpoint = (slug: string, modelCount: number) => ({
  ref: `openai_compatible:${slug}`,
  label: slug,
  base_url: `http://${slug}:8000/v1`,
  kind: 'generic',
  model_count: modelCount,
});

describe('storedCredentialSignature', () => {
  it('changes when a second endpoint is added', () => {
    const one = [provider('openai', true), provider('openai_compatible', true, [endpoint('home', 2)])];
    const two = [provider('openai', true), provider('openai_compatible', true, [endpoint('home', 2), endpoint('lab', 1)])];

    expect(storedCredentialSignature(two)).not.toBe(storedCredentialSignature(one));
  });

  it('changes when a refresh changes an endpoint model count', () => {
    const before = [provider('openai_compatible', true, [endpoint('home', 2)])];
    const after = [provider('openai_compatible', true, [endpoint('home', 3)])];

    expect(storedCredentialSignature(after)).not.toBe(storedCredentialSignature(before));
  });

  it('changes when a provider is stored or removed, and ignores unstored ones', () => {
    const base = [provider('openai', true), provider('anthropic', false)];

    expect(storedCredentialSignature([provider('openai', true), provider('anthropic', true)])).not.toBe(
      storedCredentialSignature(base),
    );
    expect(storedCredentialSignature(base)).toBe(storedCredentialSignature([provider('openai', true)]));
  });

  it('is empty before the catalogue loads', () => {
    expect(storedCredentialSignature(undefined)).toBe('');
  });
});
