/** Browser calls. Empty base means same-origin `/v1`, proxied by Next. */

export function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");
}

export function apiUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${apiBase()}${suffix}`;
}

export function wsUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  const base = apiBase();
  if (base) return `${base.replace(/^http/i, "ws")}${suffix}`;
  if (typeof window === "undefined") return suffix;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${suffix}`;
}

export async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  } catch {
    // Not JSON. Fall through to the status text below.
  }
  if (response.status === 413) return "文件太大";
  if (response.status === 415) return "只接收图片或 PDF";
  return "提交没有成功";
}
