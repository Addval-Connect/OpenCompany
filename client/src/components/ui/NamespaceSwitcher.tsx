import { useAuth } from '@/contexts/AuthContext';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';

export function NamespaceSwitcher() {
  const { activeNamespace, userNamespaces, switchNamespace } = useAuth();

  if (!userNamespaces || userNamespaces.length <= 1) return null;

  return (
    <div className="space-y-2">
      <Label htmlFor="namespace-select">Namespace activo</Label>
      <Select
        value={activeNamespace}
        onValueChange={(ns) => {
          if (ns !== activeNamespace) switchNamespace(ns);
        }}
      >
        <SelectTrigger id="namespace-select" className="w-full">
          <SelectValue placeholder="Seleccionar namespace" />
        </SelectTrigger>
        <SelectContent>
          {userNamespaces.map((ns) => (
            <SelectItem
              key={ns.namespace}
              value={ns.namespace}
              disabled={ns.status !== 'ready'}
            >
              {ns.display_name || ns.namespace}
              {ns.role === 'owner' && (
                <span className="ml-2 text-xs text-muted-foreground">(owner)</span>
              )}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs text-muted-foreground">
        Cambiar namespace recarga la sesión completa.
      </p>
    </div>
  );
}
