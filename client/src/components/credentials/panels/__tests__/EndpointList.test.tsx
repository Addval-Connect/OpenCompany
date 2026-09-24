/**
 * EndpointList renders the saved rows the catalogue sends and hands the
 * clicked row back; it owns no state and builds no request itself.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import EndpointList from '../EndpointList';
import type { ServerEndpointSummary } from '@/hooks/useCatalogueQuery';

const HOME: ServerEndpointSummary = {
  ref: 'openai_compatible:home-vllm',
  label: 'Home vLLM',
  base_url: 'http://host:8000/v1',
  kind: 'generic',
  model_count: 2,
};
const LAB: ServerEndpointSummary = {
  ref: 'openai_compatible:lab',
  label: 'Lab',
  base_url: 'http://lab:8080',
  kind: 'llamacpp',
  model_count: 1,
};

describe('EndpointList', () => {
  it('renders one row per saved endpoint', () => {
    render(<EndpointList endpoints={[HOME, LAB]} busy={false} onRefresh={vi.fn()} onRemove={vi.fn()} />);

    expect(screen.getByText('Home vLLM')).toBeTruthy();
    expect(screen.getByText('http://host:8000/v1')).toBeTruthy();
    expect(screen.getByText('llamacpp')).toBeTruthy();
    expect(screen.getByText('2 models')).toBeTruthy();
    expect(screen.getByText('1 model')).toBeTruthy();
  });

  it('hands the clicked row back for refresh and remove', async () => {
    const onRefresh = vi.fn();
    const onRemove = vi.fn();
    render(<EndpointList endpoints={[HOME, LAB]} busy={false} onRefresh={onRefresh} onRemove={onRemove} />);

    await userEvent.click(screen.getByRole('button', { name: 'Refresh Lab' }));
    await userEvent.click(screen.getByRole('button', { name: 'Remove Home vLLM' }));

    expect(onRefresh).toHaveBeenCalledWith(LAB);
    expect(onRemove).toHaveBeenCalledWith(HOME);
  });

  it('disables its actions while a request is in flight', () => {
    render(<EndpointList endpoints={[HOME]} busy onRefresh={vi.fn()} onRemove={vi.fn()} />);

    expect((screen.getByRole('button', { name: 'Refresh Home vLLM' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Remove Home vLLM' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('says so when nothing is saved', () => {
    render(<EndpointList endpoints={[]} busy={false} onRefresh={vi.fn()} onRemove={vi.fn()} />);

    expect(screen.getByText('No endpoints saved yet.')).toBeTruthy();
  });
});
