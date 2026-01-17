// lib/api.ts
import { getToken } from "@/lib/auth";

export type PendingAction =
  | {
      type: "calendar_create";
      payload: {
        summary?: string;
        start_iso?: string;
        end_iso?: string;
        conflicts?: Array<{ start?: string; end?: string }>;
        attendees?: any;
        description?: string;
      };
    }
  | {
      type: "gmail_send";
      payload: { to_email: string; subject?: string; body?: string };
    }
  | {
      type: "memory_upsert";
      payload: { key: string; value: string };
    }
  | { type: string; payload?: any };

export type PendingIntent =
  | {
      original_request?: string;
      last_question?: string;
      updated_at_iso?: string;
    }
  | null;

export type ChatResponse = {
  reply: string;
  pending_action: PendingAction | null;
  pending_intent?: PendingIntent;
};

export type GoogleStatusResponse = {
  connected: boolean;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

/** Try to parse useful error messages (FastAPI often returns JSON {detail: ...}) */
async function readError(r: Response): Promise<string> {
  const ct = r.headers.get("content-type") || "";
  try {
    if (ct.includes("application/json")) {
      const j: any = await r.json();
      if (typeof j?.detail === "string") return j.detail;
      if (Array.isArray(j?.detail)) return JSON.stringify(j.detail);
      if (typeof j?.message === "string") return j.message;
      return JSON.stringify(j);
    }
    const t = await r.text();
    return t || `HTTP ${r.status}`;
  } catch {
    return `HTTP ${r.status}`;
  }
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function requestJSON<T>(
  path: string,
  init: RequestInit & { json?: any } = {}
): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;

  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
    ...authHeaders(),
  };

  const hasBody = init.json !== undefined;
  if (hasBody) headers["Content-Type"] = "application/json";

  const r = await fetch(url, {
    ...init,
    headers,
    body: hasBody ? JSON.stringify(init.json) : init.body,
  });

  if (!r.ok) throw new Error(await readError(r));

  if (r.status === 204) return undefined as unknown as T;

  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) return r.json() as Promise<T>;

  const text = await r.text();
  return text as unknown as T;
}

export async function postChat(user_id: string, message: string): Promise<ChatResponse> {
  return requestJSON<ChatResponse>("/chat", {
    method: "POST",
    json: { user_id, message },
  });
}

export async function postConfirm(
  user_id: string,
  confirmation: "yes" | "no",
  instruction?: string
): Promise<ChatResponse> {
  return requestJSON<ChatResponse>("/confirm", {
    method: "POST",
    json: { user_id, confirmation, instruction },
  });
}

export async function startGoogleAuth(user_id: string): Promise<{ auth_url: string }> {
  const url = new URL(`${API_BASE}/auth/google/start`);
  url.searchParams.set("user_id", user_id);
  return requestJSON<{ auth_url: string }>(url.toString(), { method: "GET" });
}

export async function getGoogleStatus(user_id: string): Promise<GoogleStatusResponse> {
  const url = new URL(`${API_BASE}/auth/google/status`);
  url.searchParams.set("user_id", user_id);
  return requestJSON<GoogleStatusResponse>(url.toString(), { method: "GET" });
}
