/**
 * Which credential-catalogue provider a canvas node's status dot reads its
 * "stored" flag from.
 *
 * A NodeSpec lists its credentials by plugin credential id (`openai`,
 * `telegram`, `openai_compatible`, ...), and those ids are catalogue provider
 * ids themselves. Only a few legacy names predate that and need mapping.
 */
const LEGACY_CREDENTIAL_NAMES: Record<string, string> = {
  googleMapsApi: 'google_maps',
  openaiApi: 'openai',
  anthropicApi: 'anthropic',
  googleAiApi: 'gemini',
};

export function credentialProviderId(credentialName: string | undefined, nodeType: string | undefined): string {
  if (credentialName) return LEGACY_CREDENTIAL_NAMES[credentialName] ?? credentialName;
  if (nodeType?.includes('map') || nodeType?.includes('location')) return 'google_maps';
  return '';
}
