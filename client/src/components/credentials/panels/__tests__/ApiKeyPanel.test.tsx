/**
 * ApiKeyPanel for a provider that holds several rows (named OpenAI-compatible
 * endpoints): the form sends every field under its catalogue key, refresh and
 * remove address one endpoint by its reference, and the two requests that
 * probe the server get the probe budget instead of the 30 s default.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const sendWs = vi.fn();
const setFieldValue = vi.fn();
const setError = vi.fn();

vi.mock('../../useCredentialPanel', () => ({
  useCredentialPanel: () => ({
    values: {
      openai_compatible_url: 'http://gpu:8000',
      openai_compatible_label: 'Lab',
      openai_compatible_api_key: 'sk-1',
    },
    loading: null,
    error: null,
    stored: false,
    setError,
    form: { setFieldValue },
    actions: { sendWs, validate: vi.fn(), save: vi.fn(), remove: vi.fn() },
  }),
}));

vi.mock('../../../../assets/icons', () => ({ NodeIcon: () => null }));

import ApiKeyPanel from '../ApiKeyPanel';
import { CREDENTIAL_PROBE_REQUEST_TIMEOUT } from '@/contexts/WebSocketContext';
import type { ProviderConfig } from '../../types';

const LAB = {
  ref: 'openai_compatible:lab',
  label: 'Lab',
  base_url: 'http://gpu:8000/v1',
  kind: 'generic',
  model_count: 1,
};

const CONFIG: ProviderConfig = {
  id: 'openai_compatible',
  name: 'OpenAI-compatible',
  category: 'ai',
  categoryLabel: 'AI Models',
  color: '',
  kind: 'apiKey',
  iconRef: 'lucide:Plug',
  fields: [
    { key: 'openai_compatible_url', label: 'Base URL' },
    { key: 'openai_compatible_label', label: 'Label' },
    { key: 'openai_compatible_api_key', label: 'API key', secret: true },
  ],
  stored: true,
  endpoints: [LAB],
};

describe('ApiKeyPanel with named endpoints', () => {
  beforeEach(() => {
    sendWs.mockReset();
    setFieldValue.mockReset();
    setError.mockReset();
  });

  it('adds an endpoint with every field under its catalogue key', async () => {
    sendWs.mockResolvedValue({ valid: true });
    render(<ApiKeyPanel config={CONFIG} visible />);

    await userEvent.click(screen.getByRole('button', { name: 'Add endpoint' }));

    expect(sendWs).toHaveBeenCalledWith(
      'validate_api_key',
      {
        provider: 'openai_compatible',
        api_key: 'http://gpu:8000',
        openai_compatible_label: 'Lab',
        openai_compatible_api_key: 'sk-1',
      },
      CREDENTIAL_PROBE_REQUEST_TIMEOUT,
    );
    expect(setFieldValue.mock.calls).toEqual([
      ['openai_compatible_url', ''],
      ['openai_compatible_label', ''],
      ['openai_compatible_api_key', ''],
    ]);
  });

  it("shows the server's reason when a save is refused and keeps the form", async () => {
    sendWs.mockResolvedValue({ valid: false, message: 'No OpenAI-compatible API answered at http://gpu:8000.' });
    render(<ApiKeyPanel config={CONFIG} visible />);

    await userEvent.click(screen.getByRole('button', { name: 'Add endpoint' }));

    expect(setError).toHaveBeenCalledWith('No OpenAI-compatible API answered at http://gpu:8000.');
    expect(setFieldValue).not.toHaveBeenCalled();
  });

  it('refreshes an endpoint by its reference', async () => {
    sendWs.mockResolvedValue({ valid: true });
    render(<ApiKeyPanel config={CONFIG} visible />);

    await userEvent.click(screen.getByRole('button', { name: 'Refresh Lab' }));

    expect(sendWs).toHaveBeenCalledWith(
      'validate_api_key',
      { provider: 'openai_compatible', api_key: 'http://gpu:8000/v1', ref: 'openai_compatible:lab' },
      CREDENTIAL_PROBE_REQUEST_TIMEOUT,
    );
  });

  it('removes an endpoint by its reference', async () => {
    render(<ApiKeyPanel config={CONFIG} visible />);

    await userEvent.click(screen.getByRole('button', { name: 'Remove Lab' }));

    expect(sendWs).toHaveBeenCalledWith('delete_api_key', { provider: 'openai_compatible:lab' });
  });

  it('gives a probing request longer than the default request timeout', () => {
    expect(CREDENTIAL_PROBE_REQUEST_TIMEOUT).toBeGreaterThan(30_000);
  });
});
