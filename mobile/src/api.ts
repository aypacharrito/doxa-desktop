// Talks to Doxa on your PC through your private Cloudflare link.
import { fetch as streamingFetch } from "expo/fetch";

export type Connection = { base: string; key: string };
export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "status"; text: string }
  | { type: "offer"; task: string; reply: string }
  | { type: "done"; reply: string; note?: string }
  | { type: "error"; error: string };
export type Pending = { id: string; kind: "ask" | "confirm" | "hand_off"; text: string; title: string; body: string };
export type BrowserState = {
  running: boolean; paused: boolean; task: string; log: string[]; pending: Pending | null;
  result: { status: string; message: string } | null;
};
export type Status = { model_loaded: boolean; model: string; pc: string; browser_running: boolean; cloud_available?: boolean; cloud_budget?: {reserved_cents:number;limit_cents:number} };
export type Message = { role: "user" | "assistant"; content: string };

export class DoxaError extends Error {
  constructor(message: string, readonly status = 0) { super(message); }
}

/** Accepts the link from Doxa > Phone access, e.g. https://abc.trycloudflare.com/#k=SECRET */
export function parseLink(raw: string): Connection | null {
  const text = raw.trim();
  const match = text.match(/^(https:\/\/[^\s#/?]+)\/?(?:[?][^#]*)?#k=([A-Za-z0-9_\-]{20,})$/);
  return match ? { base: match[1], key: match[2] } : null;
}

async function call<T>(c: Connection, path: string, body?: unknown, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(c.base + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + c.key },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new DoxaError((data as { error?: string }).error || `Doxa didn't answer (${res.status}).`, res.status);
    return data as T;
  } catch (err) {
    if (err instanceof DoxaError) throw err;
    throw new DoxaError("Can't reach Doxa. Is your PC on with Doxa open?");
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  status: (c: Connection) => call<Status>(c, "/api/status", undefined, 8000),
  history: (c: Connection) => call<{ messages: Message[] }>(c, "/api/history"),
  browser: (c: Connection) => call<BrowserState>(c, "/api/browser", undefined, 8000),
  startTask: (c: Connection, task: string) => call<{ ok: boolean }>(c, "/api/browser/start", { task }),
  respond: (c: Connection, id: string, value: unknown) => call<{ ok: boolean }>(c, "/api/browser/respond", { id, value }),
  stop: (c: Connection) => call<{ ok: boolean }>(c, "/api/stop", {}),
  registerPush: (c: Connection, token: string) => call<{ ok: boolean }>(c, "/api/push/register", { token }),
  transcribe: (c: Connection, audio: string, mime = "audio/mp4") =>
    call<{ text: string }>(c, "/api/transcribe", { audio, mime }, 60000),
  speak: (c: Connection, text: string) => call<{ id: string }>(c, "/api/speak", { text }, 60000),
  /** A photo or document (base64) saved on the PC in Documents\Doxa Inbox; `tag` goes into the chat message. */
  upload: (c: Connection, name: string, data: string) =>
    call<Upload>(c, "/api/upload", { name, data }, 120000),
  chats: (c: Connection) => call<{ chats: ChatSummary[] }>(c, "/api/chats"),
  chat: (c: Connection, id: number) => call<{ messages: Message[] }>(c, `/api/chats/${id}`),
  newChat: (c: Connection) => call<{ ok: boolean }>(c, "/api/chats/new", {}),
  code: (c: Connection) => call<CodeState>(c, "/api/code", undefined, 8000),
  codeStart: (c: Connection, task: string, engine = "auto", fresh = false) =>
    call<{ ok: boolean; note: string }>(c, "/api/code/start", { task, engine, fresh }, 25000),
  codeStop: (c: Connection) => call<{ ok: boolean }>(c, "/api/code/stop", {}),
};

export type CodeJob = {
  engine: string; name: string; task: string; folder: string; status: string; steps: string[]; step_count: number;
  report: string; continued: boolean;
};
export type Upload = { path: string; name: string; size: number; kind: "image" | "document"; tag: string };
export type ChatSummary = { id: number; title: string; updated: string; count: number };
export type CodeState ={ running: boolean; job: CodeJob | null; engines: Record<string, string> };

/** doxa://connect?u=https://….trycloudflare.com&k=KEY (from "Open in the Doxa app" on the phone page). */
export function parseAppLink(raw: string): Connection | null {
  const match = raw.match(/^doxa:\/\/connect\?(.*)$/);
  if (!match) return null;
  const params = new URLSearchParams(match[1]);
  return parseLink(`${params.get("u") || ""}#k=${params.get("k") || ""}`);
}

/** Streams a reply. onEvent fires for every word as Doxa writes it. */
export async function streamChat(c: Connection, message: string, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
  let res: Awaited<ReturnType<typeof streamingFetch>>;
  try {
    res = await streamingFetch(c.base + "/api/chat/stream", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + c.key },
      body: JSON.stringify({ message }),
      signal,
    });
  } catch {
    throw new DoxaError("Can't reach Doxa. Is your PC on with Doxa open?");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new DoxaError((data as { error?: string }).error || `Doxa didn't answer (${res.status}).`, res.status);
  }
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      const event = JSON.parse(line) as ChatEvent;
      if (event.type === "error") throw new DoxaError(event.error);
      onEvent(event);
    }
  }
}
