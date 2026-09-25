import { describe, expect, it } from 'vitest';

import { nextDynamicOptionValue } from '../dynamicOptions';

const LLAMA_ONLY = [{ value: 'llama3' }, { value: 'llama3:8b' }];

describe('nextDynamicOptionValue', () => {
  it('fills an empty field with the first option', () => {
    expect(nextDynamicOptionValue('', LLAMA_ONLY, false)).toBe('llama3');
    expect(nextDynamicOptionValue(undefined, LLAMA_ONLY, true)).toBe('llama3');
  });

  it('moves off a value the newly chosen parent does not offer', () => {
    // The endpoint changed from one serving qwen2.5 to one serving llama only.
    expect(nextDynamicOptionValue('qwen2.5', LLAMA_ONLY, true)).toBe('llama3');
  });

  it('keeps a value the new list still offers', () => {
    expect(nextDynamicOptionValue('llama3:8b', LLAMA_ONLY, true)).toBeUndefined();
  });

  it('never rewrites a stored value just because the panel opened', () => {
    expect(nextDynamicOptionValue('/api/v1/douyin/web/fetch_one_video', LLAMA_ONLY, false)).toBeUndefined();
  });

  it('leaves an expression alone', () => {
    expect(nextDynamicOptionValue('{{trigger.model}}', LLAMA_ONLY, true)).toBeUndefined();
  });

  it('changes nothing while the loader offers nothing', () => {
    expect(nextDynamicOptionValue('', [], true)).toBeUndefined();
    expect(nextDynamicOptionValue('qwen2.5', [], true)).toBeUndefined();
  });
});
