/** Browser calls. Empty base means same-origin `/v1`, proxied by Next. */

const SESSION_KEY = "hilatv.session";
let opening: Promise<string> | null = null;

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

export function withSession(url: string, token: string): string {
  const hashAt = url.indexOf("#");
  const base = hashAt >= 0 ? url.slice(0, hashAt) : url;
  const hash = hashAt >= 0 ? url.slice(hashAt) : "";
  const join = base.includes("?") ? "&" : "?";
  return `${base}${join}session=${encodeURIComponent(token)}${hash}`;
}

export async function ensureSession(): Promise<string> {
  if (typeof window === "undefined") return "";
  const existing = window.localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  if (!opening) {
    opening = fetch(apiUrl("/v1/session"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await errorMessage(response));
        const body = (await response.json()) as { token?: string };
        if (!body.token) throw new Error("没有拿到登录会话");
        window.localStorage.setItem(SESSION_KEY, body.token);
        return body.token;
      })
      .finally(() => {
        opening = null;
      });
  }
  return opening;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Authorization")) {
    const token = await ensureSession();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(apiUrl(path), { ...init, headers });
  if (response.status !== 401 || typeof window === "undefined" || headers.get("X-HiLatv-Retried")) {
    return response;
  }
  window.localStorage.removeItem(SESSION_KEY);
  const fresh = await ensureSession();
  const retryHeaders = new Headers(init.headers);
  if (fresh) retryHeaders.set("Authorization", `Bearer ${fresh}`);
  retryHeaders.set("X-HiLatv-Retried", "1");
  return fetch(apiUrl(path), { ...init, headers: retryHeaders });
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
