/** 本机工具箱：把框选的节点和内部连线存成可复用的组合。 */

export type ToolboxNode = {
  kind: string;
  prompt?: string;
  text?: string;
  dx: number;
  dy: number;
};

export type ToolboxEdge = {
  from: number;
  to: number;
  role: string;
  fromHandle?: string;
  toHandle?: string;
};

export type ToolboxGroup = {
  id: string;
  name: string;
  nodes: ToolboxNode[];
  edges: ToolboxEdge[];
  saved_at: number;
};

const KEY = "hilatv.canvas.toolbox.v1";

export function loadGroups(): ToolboxGroup[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is ToolboxGroup => {
      const group = item as ToolboxGroup;
      return Boolean(group && typeof group.id === "string" && Array.isArray(group.nodes));
    });
  } catch {
    return [];
  }
}

export function persistGroups(groups: ToolboxGroup[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, JSON.stringify(groups.slice(0, 24)));
}

export function addGroup(group: ToolboxGroup): ToolboxGroup[] {
  const groups = [group, ...loadGroups()];
  persistGroups(groups);
  return groups;
}

export function removeGroup(id: string): ToolboxGroup[] {
  const groups = loadGroups().filter((group) => group.id !== id);
  persistGroups(groups);
  return groups;
}
