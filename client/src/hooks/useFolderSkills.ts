/**
 * Skill metadata queries.
 *
 * `useFolderSkills` wraps the `scan_skill_folder` WebSocket request in
 * TanStack Query so:
 *  - sibling surfaces (MasterSkillEditor, MiddleSection) reading the
 *    same folder share one network call
 *  - SKILL.md frontmatter (icon / color / description) is the single
 *    source of truth -- the frontend no longer maintains a per-skill
 *    icon override table
 *
 * `useAllSkills` wraps `list_all_skills` (flat catalogue across every
 * skill folder) for the MasterSkillEditor "All skills" view.
 *
 * Cache key matches the in-place query MasterSkillEditor used to
 * declare inline, so existing cache hits carry over.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useWebSocket } from '../contexts/WebSocketContext';
import { STALE_TIME } from '../lib/queryConfig';
import { dracula } from '../styles/theme';

export interface AvailableSkill {
  type: string;
  skillName: string;
  displayName: string;
  icon: string;
  color: string;
  description: string;
  /** Top-level folder the skill lives in (set by `useAllSkills` only). */
  folder?: string;
}

export const folderSkillsQueryKey = (folder: string) =>
  ['folderSkills', folder] as const;

interface ScanSkillFolderResponse {
  success: boolean;
  skills?: Array<{
    name: string;
    description: string;
    metadata?: Record<string, any>;
  }>;
  error?: string;
}

const titleCase = (slug: string): string =>
  slug
    .split('-')
    .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');

interface ListAllSkillsResponse {
  success: boolean;
  skills?: Array<{
    name: string;
    description: string;
    metadata?: Record<string, any>;
    folder?: string;
  }>;
  error?: string;
}

export const allSkillsQueryKey = ['allSkills'] as const;

/**
 * Flat catalogue of every filesystem skill across all skill folders,
 * each tagged with its top-level folder. User-created (DB) skills are
 * merged separately by the caller. `enabled` gates the request so the
 * catalogue is only fetched when the "All skills" view is active.
 */
export function useAllSkills(
  enabled: boolean,
): UseQueryResult<AvailableSkill[], Error> {
  const { sendRequest, isReady } = useWebSocket();
  return useQuery<AvailableSkill[], Error>({
    queryKey: allSkillsQueryKey,
    queryFn: async () => {
      const response = await sendRequest<ListAllSkillsResponse>(
        'list_all_skills',
        {},
      );
      if (!response?.success || !response.skills) return [];
      return response.skills.map((s) => ({
        type: s.name,
        skillName: s.name,
        displayName: titleCase(s.name),
        icon: s.metadata?.icon ?? '',
        color: s.metadata?.color ?? dracula.purple,
        description: s.description ?? '',
        folder: s.folder,
      }));
    },
    enabled: enabled && isReady,
    staleTime: STALE_TIME.MEDIUM,
  });
}

export function useFolderSkills(
  folder: string | undefined | null,
): UseQueryResult<AvailableSkill[], Error> {
  const { sendRequest, isReady } = useWebSocket();
  return useQuery<AvailableSkill[], Error>({
    queryKey: folderSkillsQueryKey(folder ?? ''),
    queryFn: async () => {
      if (!folder) return [];
      const response = await sendRequest<ScanSkillFolderResponse>(
        'scan_skill_folder',
        { folder },
      );
      if (!response?.success || !response.skills) return [];
      return response.skills.map((s) => ({
        type: s.name,
        skillName: s.name,
        displayName: titleCase(s.name),
        icon: s.metadata?.icon ?? '',
        color: s.metadata?.color ?? dracula.purple,
        description: s.description ?? '',
      }));
    },
    enabled: !!folder && isReady,
    staleTime: STALE_TIME.MEDIUM,
  });
}
