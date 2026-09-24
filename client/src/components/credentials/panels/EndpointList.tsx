/**
 * EndpointList — the saved rows of a provider that holds several (named
 * OpenAI-compatible endpoints). Stateless: rows come from the catalogue,
 * which the backend refreshes after every add, refresh and remove, and the
 * `base_url` it shows is already redacted server-side.
 */

import React from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ActionButton } from '@/components/ui/action-button';
import type { ServerEndpointSummary } from '@/hooks/useCatalogueQuery';

interface EndpointListProps {
  endpoints: ServerEndpointSummary[];
  busy: boolean;
  onRefresh: (endpoint: ServerEndpointSummary) => void;
  onRemove: (endpoint: ServerEndpointSummary) => void;
}

const EndpointList: React.FC<EndpointListProps> = ({ endpoints, busy, onRefresh, onRemove }) => {
  if (endpoints.length === 0) {
    return <p className="text-sm text-muted-foreground">No endpoints saved yet.</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      {endpoints.map((endpoint) => (
        <Card key={endpoint.ref}>
          <CardContent className="flex items-center gap-3 pt-4">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="truncate text-sm font-medium">{endpoint.label}</span>
              <span className="truncate font-mono text-xs text-muted-foreground">{endpoint.base_url}</span>
            </div>
            <Badge variant="secondary">{endpoint.kind}</Badge>
            <Badge variant="outline">
              {endpoint.model_count} {endpoint.model_count === 1 ? 'model' : 'models'}
            </Badge>
            <ActionButton
              intent="config"
              onClick={() => onRefresh(endpoint)}
              disabled={busy}
              aria-label={`Refresh ${endpoint.label}`}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </ActionButton>
            <ActionButton
              intent="stop"
              onClick={() => onRemove(endpoint)}
              disabled={busy}
              aria-label={`Remove ${endpoint.label}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </ActionButton>
          </CardContent>
        </Card>
      ))}
    </div>
  );
};

export default EndpointList;
