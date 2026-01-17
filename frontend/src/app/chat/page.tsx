export const dynamic = "force-dynamic";

"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  postChat,
  postConfirm,
  startGoogleAuth,
  getGoogleStatus,
  PendingAction,
} from "@/lib/api";
import { clearAuth, isLoggedIn } from "@/lib/auth";

type Msg = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  ts: number;
};

type Thread = {
  id: string;
  title: string;
  createdAt: number;
  msgs: Msg[];
  // NOTE: we keep this for backwards compat with your saved data,
  // but we will NOT trust it as the source of truth for locking UI.
  pending: PendingAction | null;
};

function uid() {
  return Math.random().toString(16).slice(2) + "-" + Date.now().toString(16);
}

function fmtIso(iso?: string) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function clampTitle(s: string) {
  const t = s.trim().replace(/\s+/g, " ");
  if (!t) return "New chat";
  return t.length > 34 ? t.slice(0, 34) + "…" : t;
}

const LS_GLOBAL_PENDING = "sentellent_pending_action_global";
const LS_THREADS = "sentellent_threads";
const LS_ACTIVE = "sentellent_active_thread";

function readGlobalPending(): PendingAction | null {
  try {
    const raw = localStorage.getItem(LS_GLOBAL_PENDING);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (!obj || typeof obj !== "object") return null;
    if (!("type" in obj)) return null;
    return obj as PendingAction;
  } catch {
    return null;
  }
}

function writeGlobalPending(p: PendingAction | null) {
  try {
    if (!p) localStorage.removeItem(LS_GLOBAL_PENDING);
    else localStorage.setItem(LS_GLOBAL_PENDING, JSON.stringify(p));
  } catch {
    // ignore
  }
}

function PendingCard({
  pending,
  onYes,
  onNo,
  busy,
}: {
  pending: PendingAction;
  onYes: () => void;
  onNo: () => void;
  busy: boolean;
}) {
  const p = pending.payload || {};
  const title =
    pending.type === "calendar_create"
      ? p.summary || "Calendar event"
      : pending.type === "gmail_send"
      ? `Email to ${p.to_email || "(missing)"}`
      : pending.type === "memory_upsert"
      ? `Save preference`
      : pending.type;

  return (
    <div className="sticky top-4 z-20 w-full rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Action waiting for confirmation
          </div>
          <div className="mt-1 text-base font-semibold text-zinc-900 dark:text-zinc-100">
            {title}
          </div>

          {pending.type === "calendar_create" && (
            <div className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
              <div>
                <span className="font-medium">Start:</span> {fmtIso(p.start_iso)}
              </div>
              <div>
                <span className="font-medium">End:</span> {fmtIso(p.end_iso)}
              </div>

              {Array.isArray(p.conflicts) && p.conflicts.length > 0 && (
                <div className="mt-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                  <div className="font-semibold">Conflicts</div>
                  <ul className="mt-1 list-disc pl-5">
                    {p.conflicts.slice(0, 5).map((c: any, i: number) => (
                      <li key={i}>
                        {c?.start || "?"} → {c?.end || "?"}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {pending.type === "gmail_send" && (
            <div className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
              <div>
                <span className="font-medium">To:</span> {p.to_email || "(missing)"}
              </div>
              <div>
                <span className="font-medium">Subject:</span> {p.subject || "(no subject)"}
              </div>
            </div>
          )}

          {pending.type === "memory_upsert" && (
            <div className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
              <div>
                <span className="font-medium">Key:</span> {p.key || "(missing)"}
              </div>
              <div>
                <span className="font-medium">Value:</span> {String(p.value ?? "")}
              </div>
            </div>
          )}

          <div className="mt-3 text-[12px] text-zinc-500 dark:text-zinc-400">
            While this is pending, chat input is locked. Use <b>Confirm</b> or <b>Cancel</b>.
          </div>
        </div>

        <div className="flex shrink-0 flex-col gap-2">
          <button
            onClick={onYes}
            disabled={busy}
            className="rounded-xl bg-black px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800 disabled:opacity-50"
          >
            Confirm
          </button>
          <button
            onClick={onNo}
            disabled={busy}
            className="rounded-xl border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-900 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-900"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function Bubble({ role, text, ts }: { role: Msg["role"]; text: string; ts: number }) {
  const isUser = role === "user";
  const isSystem = role === "system";

  const base =
    "max-w-[92%] rounded-2xl px-4 py-3 text-[13.5px] leading-6 shadow-[0_1px_0_rgba(0,0,0,0.02)]";

  const cls = isUser
    ? "ml-auto bg-black text-white"
    : isSystem
    ? "mr-auto border border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200"
    : "mr-auto border border-zinc-200 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-black dark:text-zinc-100";

  return (
    <div className={[base, cls].join(" ")}>
      {role === "assistant" ? (
        <div className="prose prose-zinc max-w-none text-[13.5px] leading-6 dark:prose-invert">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ ...props }) => (
                <a {...props} className="underline underline-offset-2 hover:opacity-80" />
              ),
              code: ({ className, children, ...props }) => {
                const isInline = !className;
                if (isInline) {
                  return (
                    <code
                      {...props}
                      className="rounded bg-zinc-100 px-1 py-0.5 text-[12.5px] dark:bg-zinc-900"
                    >
                      {children}
                    </code>
                  );
                }
                return (
                  <pre className="overflow-x-auto rounded-xl border border-zinc-200 bg-zinc-50 p-3 text-[12.5px] dark:border-zinc-800 dark:bg-zinc-950">
                    <code {...props}>{children}</code>
                  </pre>
                );
              },
            }}
          >
            {text}
          </ReactMarkdown>
        </div>
      ) : (
        <div className="whitespace-pre-wrap">{text}</div>
      )}

      <div className="mt-2 text-[10px] opacity-50">{new Date(ts).toLocaleTimeString()}</div>
    </div>
  );
}

function StatusPill({ loading, connected }: { loading: boolean; connected: boolean }) {
  if (loading) {
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1 text-[12px] text-zinc-700 dark:border-zinc-800 dark:bg-black dark:text-zinc-200">
        <span className="h-2 w-2 animate-pulse rounded-full bg-zinc-400" />
        Checking…
      </div>
    );
  }

  return connected ? (
    <div className="inline-flex items-center gap-2 rounded-full border border-black bg-black px-3 py-1 text-[12px] text-white">
      <span className="h-2 w-2 rounded-full bg-white" />
      Connected
    </div>
  ) : (
    <div className="inline-flex items-center gap-2 rounded-full border border-zinc-300 bg-white px-3 py-1 text-[12px] text-zinc-800 dark:border-zinc-700 dark:bg-black dark:text-zinc-200">
      <span className="h-2 w-2 rounded-full bg-zinc-400" />
      Not connected
    </div>
  );
}

export default function ChatPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [userId, setUserId] = useState("adithya");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [entering, setEntering] = useState(true);

  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string>("");

  const [message, setMessage] = useState("");

  // ✅ global pending is THE source of truth for lock + pending UI
  const [globalPending, setGlobalPending] = useState<PendingAction | null>(null);

  // google status
  const [googleChecking, setGoogleChecking] = useState(false);
  const [googleConnected, setGoogleConnected] = useState(false);

  const listRef = useRef<HTMLDivElement | null>(null);

  const apiUrl = useMemo(() => process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000", []);

  const active = useMemo(() => threads.find((t) => t.id === activeId) || null, [threads, activeId]);

  const inputLocked = !!globalPending; // ✅ lock chat if pending exists

  function ensureActiveThread(nextThreads?: Thread[]) {
    const arr = nextThreads ?? threads;
    if (arr.length === 0) return;
    if (!arr.some((t) => t.id === activeId)) setActiveId(arr[0].id);
  }

  function newThread() {
    const t: Thread = { id: uid(), title: "New chat", createdAt: Date.now(), msgs: [], pending: null };
    setThreads((prev) => [t, ...prev]);
    setActiveId(t.id);
    setMessage("");
    setErr(null);
  }

  function deleteThread(threadId: string) {
    setThreads((prev) => prev.filter((t) => t.id !== threadId));
    if (threadId === activeId) {
      setTimeout(() => {
        setThreads((current) => {
          if (current.length > 0) setActiveId(current[0].id);
          else setActiveId("");
          return current;
        });
      }, 0);
    }
  }

  function pushMsg(threadId: string, role: Msg["role"], text: string) {
    const msg: Msg = { id: uid(), role, text, ts: Date.now() };
    setThreads((prev) => prev.map((t) => (t.id === threadId ? { ...t, msgs: [...t.msgs, msg] } : t)));
  }

  function setThreadPending(threadId: string, pending: PendingAction | null) {
    setThreads((prev) => prev.map((t) => (t.id === threadId ? { ...t, pending } : t)));
  }

  function setPendingEverywhere(next: PendingAction | null) {
    setGlobalPending(next);
    writeGlobalPending(next);
    // also keep thread pending aligned so localStorage threads don't re-hydrate stale UI
    if (activeId) setThreadPending(activeId, next);
  }

  // Route guard + entering
  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    const t = setTimeout(() => setEntering(false), 500);
    return () => clearTimeout(t);
  }, [router]);

  // Hydrate local state
  useEffect(() => {
    const savedUserId = localStorage.getItem("sentellent_user_id");
    if (savedUserId) setUserId(savedUserId);

    // ✅ read global pending first
    setGlobalPending(readGlobalPending());

    try {
      const raw = localStorage.getItem(LS_THREADS);
      if (raw) {
        const parsed = JSON.parse(raw) as Thread[];
        if (Array.isArray(parsed) && parsed.length > 0) {
          setThreads(parsed);
          const savedActive = localStorage.getItem(LS_ACTIVE);
          if (savedActive && parsed.some((t) => t.id === savedActive)) setActiveId(savedActive);
          else setActiveId(parsed[0].id);
          return;
        }
      }
    } catch {}

    const t0: Thread = { id: uid(), title: "New chat", createdAt: Date.now(), msgs: [], pending: null };
    setThreads([t0]);
    setActiveId(t0.id);
  }, []);

  // persist
  useEffect(() => {
    localStorage.setItem("sentellent_user_id", userId);
  }, [userId]);

  useEffect(() => {
    localStorage.setItem(LS_THREADS, JSON.stringify(threads.slice(0, 30)));
    if (activeId) localStorage.setItem(LS_ACTIVE, activeId);
  }, [threads, activeId]);

  // connected flag
  useEffect(() => {
    const connected = searchParams.get("connected");
    if (connected === "1" && activeId) {
      const already = localStorage.getItem("sentellent_connected_banner");
      if (!already) {
        pushMsg(activeId, "system", "Google connected. You can now use Gmail/Calendar tools.");
        localStorage.setItem("sentellent_connected_banner", "1");
      }
      setGoogleConnected(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, activeId]);

  async function refreshGoogleStatus(nextUserId?: string) {
    const u = (nextUserId ?? userId).trim();
    if (!u) return;

    setGoogleChecking(true);
    try {
      const res = await getGoogleStatus(u);
      setGoogleConnected(!!res.connected);
    } catch {
      setGoogleConnected(false);
    } finally {
      setGoogleChecking(false);
    }
  }

  useEffect(() => {
    if (!userId) return;
    refreshGoogleStatus(userId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  // auto-scroll
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [active?.msgs.length, busy, globalPending]);

  async function send() {
    const text = message.trim();
    if (!text || !active) return;

    // ✅ hard-block sending when pending exists
    if (inputLocked) {
      pushMsg(active.id, "system", "You have an action waiting for confirmation. Please Confirm/Cancel first.");
      return;
    }

    setErr(null);
    setMessage("");
    pushMsg(active.id, "user", text);

    if (active.title === "New chat") {
      setThreads((prev) => prev.map((t) => (t.id === active.id ? { ...t, title: clampTitle(text) } : t)));
    }

    try {
      setBusy(true);
      const res = await postChat(userId, text);

      pushMsg(active.id, "assistant", res.reply || "OK");

      // ✅ always sync pending everywhere
      setPendingEverywhere(res.pending_action ?? null);
    } catch (e: any) {
      const m = e?.message || String(e);
      setErr(m);
      pushMsg(active.id, "system", `Error: ${m}`);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(confirmation: "yes" | "no") {
    if (!active) return;
    setErr(null);

    // ✅ optimistic unlock so UI never gets stuck
    // If backend returns a new pending action, we’ll re-lock immediately.
    setPendingEverywhere(null);

    try {
      setBusy(true);
      const res = await postConfirm(userId, confirmation);

      pushMsg(active.id, "assistant", res.reply || "OK");

      // ✅ res.pending_action is REQUIRED in your type, so this is safe
      setPendingEverywhere(res.pending_action ?? null);
    } catch (e: any) {
      const m = e?.message || String(e);
      setErr(m);
      pushMsg(active.id, "system", `Error: ${m}`);
      // if confirm failed, restore from localStorage (best effort)
      setGlobalPending(readGlobalPending());
    } finally {
      setBusy(false);
    }
  }

  async function connectGoogle() {
    setErr(null);
    try {
      setBusy(true);
      const { auth_url } = await startGoogleAuth(userId);
      window.location.href = auth_url;
    } catch (e: any) {
      const m = e?.message || String(e);
      setErr(m);
      if (active) pushMsg(active.id, "system", `Error: ${m}`);
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearAuth();
    localStorage.removeItem(LS_THREADS);
    localStorage.removeItem(LS_ACTIVE);
    localStorage.removeItem("sentellent_connected_banner");
    localStorage.removeItem(LS_GLOBAL_PENDING);
    router.replace("/login");
  }

  function clearActiveChat() {
    if (!active) return;

    // if pending exists, don’t let them wipe context (optional but safer)
    if (inputLocked) {
      pushMsg(active.id, "system", "Can’t clear the chat while an action is waiting for confirmation. Confirm/Cancel first.");
      return;
    }

    setThreads((prev) =>
      prev.map((t) => (t.id === active.id ? { ...t, msgs: [], pending: null, title: "New chat" } : t))
    );
    setMessage("");
    setErr(null);
  }

  useEffect(() => {
    ensureActiveThread();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threads.length]);

  return (
    <div className="min-h-screen bg-white text-black dark:bg-black dark:text-white font-sans">
      <div
        className="pointer-events-none fixed inset-0 opacity-[0.05] dark:opacity-[0.07]"
        style={{
          backgroundImage:
            "linear-gradient(#000 1px, transparent 1px), linear-gradient(90deg, #000 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />

      {entering && (
        <div className="fixed inset-0 z-[999] flex items-center justify-center bg-white/90 dark:bg-black/90">
          <div className="flex flex-col items-center gap-3">
            <div className="h-10 w-10 animate-spin rounded-full border-2 border-zinc-300 border-t-black dark:border-zinc-700 dark:border-t-white" />
            <div className="text-sm text-zinc-600 dark:text-zinc-300">Loading Sentellent…</div>
          </div>
        </div>
      )}

      <div className="relative h-screen w-full overflow-hidden">
        <div className="flex h-full w-full">
          <aside
            className={[
              "h-full w-[320px] shrink-0 border-r border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-800 dark:bg-black/60",
              sidebarOpen ? "block" : "hidden md:block",
            ].join(" ")}
          >
            <div className="flex items-center justify-between gap-2 border-b border-zinc-200 bg-black px-4 py-3 dark:border-zinc-800">
              <div className="text-white font-semibold tracking-tight">Sentellent</div>
              <button
                onClick={() => setSidebarOpen(false)}
                className="md:hidden rounded-lg px-2 py-1 text-xs text-white/80 hover:text-white"
              >
                Close
              </button>
            </div>

            <div className="p-3">
              <button
                onClick={newThread}
                className="w-full rounded-xl bg-black px-3 py-2 text-sm font-semibold text-white hover:bg-zinc-800 disabled:opacity-60"
                disabled={busy || inputLocked}
                title={inputLocked ? "Confirm/Cancel the pending action first" : undefined}
              >
                + New chat
              </button>

              <div className="mt-3 text-[11px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                Chats
              </div>

              <div className="mt-2 flex flex-col gap-1">
                {threads.map((t) => {
                  const isActive = t.id === activeId;

                  return (
                    <div
                      key={t.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setActiveId(t.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setActiveId(t.id);
                        }
                      }}
                      className={[
                        "group w-full rounded-xl border px-3 py-2 text-left cursor-pointer select-none",
                        isActive
                          ? "border-zinc-300 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/40"
                          : "border-transparent hover:border-zinc-200 hover:bg-zinc-50 dark:hover:border-zinc-800 dark:hover:bg-zinc-900/30",
                      ].join(" ")}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
                            {t.title}
                          </div>
                          <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                            {t.msgs.length} messages{t.pending ? " • pending" : ""}
                          </div>
                        </div>

                        <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteThread(t.id);
                            }}
                            className="rounded-lg border border-zinc-200 px-2 py-1 text-[11px] text-zinc-700 hover:bg-white dark:border-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-950"
                          >
                            Del
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-4 rounded-2xl border border-zinc-200 bg-white p-3 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
                <div className="font-semibold text-zinc-900 dark:text-zinc-100">Tips</div>
                <ul className="mt-2 list-disc pl-5 space-y-1">
                  <li>Show important emails from last 2 days</li>
                  <li>Show my events tomorrow</li>
                  <li>Schedule “Test meeting” tomorrow 10:00 for 30 minutes</li>
                </ul>
              </div>
            </div>
          </aside>

          <main className="flex h-full min-w-0 flex-1 flex-col">
            <div className="flex items-center justify-between gap-3 border-b border-zinc-200 bg-white/80 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-black/40">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSidebarOpen((s) => !s)}
                  className="md:hidden rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:hover:bg-zinc-900"
                >
                  Menu
                </button>

                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                    {active?.title || "Chat"}
                  </div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400">API: {apiUrl}</div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <StatusPill loading={googleChecking} connected={googleConnected} />

                <button
                  onClick={connectGoogle}
                  disabled={busy || googleConnected}
                  className={[
                    "rounded-xl px-3 py-2 text-sm font-semibold",
                    googleConnected
                      ? "bg-zinc-200 text-zinc-700 cursor-not-allowed dark:bg-zinc-900 dark:text-zinc-300"
                      : "bg-black text-white hover:bg-zinc-800 disabled:opacity-60",
                  ].join(" ")}
                >
                  {googleConnected ? "Connected ✓" : "Connect Google"}
                </button>

                <button
                  onClick={() => refreshGoogleStatus()}
                  disabled={busy || googleChecking}
                  className="rounded-xl border border-zinc-300 px-3 py-2 text-sm font-semibold hover:bg-zinc-50 disabled:opacity-60 dark:border-zinc-700 dark:hover:bg-zinc-900"
                >
                  Refresh
                </button>

                <button
                  onClick={clearActiveChat}
                  disabled={inputLocked}
                  className="rounded-xl border border-zinc-300 px-3 py-2 text-sm font-semibold hover:bg-zinc-50 disabled:opacity-60 dark:border-zinc-700 dark:hover:bg-zinc-900"
                  title={inputLocked ? "Confirm/Cancel the pending action first" : undefined}
                >
                  Clear
                </button>

                <button
                  onClick={logout}
                  className="rounded-xl border border-zinc-300 px-3 py-2 text-sm font-semibold hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
                >
                  Logout
                </button>
              </div>
            </div>

            <div className="flex min-h-0 flex-1">
              <div className="flex min-h-0 w-full flex-col px-4 py-4">
                {globalPending && (
                  <PendingCard
                    pending={globalPending}
                    busy={busy}
                    onYes={() => confirm("yes")}
                    onNo={() => confirm("no")}
                  />
                )}

                {err && (
                  <div className="mt-3 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-200">
                    {err}
                  </div>
                )}

                <div
                  ref={listRef}
                  className="mt-3 min-h-0 flex-1 overflow-y-auto rounded-2xl border border-zinc-200 bg-white/80 p-4 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-black/40"
                >
                  {!active || active.msgs.length === 0 ? (
                    <div className="text-sm text-zinc-600 dark:text-zinc-300">
                      <div className="font-semibold text-zinc-900 dark:text-zinc-100">Welcome to Sentellent</div>
                      <div className="mt-1">Try Gmail/Calendar actions after you’re connected.</div>

                      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {[
                          "Show important emails from last 2 days",
                          "Show my events tomorrow",
                          "Don’t schedule meetings before 10:00",
                          "Schedule 'Test meeting' tomorrow at 10:00 for 30 minutes",
                          "Send email to someone@gmail.com subject Hello body Testing",
                        ].map((s) => (
                          <button
                            key={s}
                            onClick={() => setMessage(s)}
                            disabled={inputLocked}
                            className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-left text-sm hover:bg-zinc-50 disabled:opacity-60 dark:border-zinc-800 dark:bg-zinc-950 dark:hover:bg-zinc-900"
                            title={inputLocked ? "Confirm/Cancel the pending action first" : undefined}
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-3">
                      {active.msgs.map((m) => (
                        <Bubble key={m.id} role={m.role} text={m.text} ts={m.ts} />
                      ))}
                      {busy && (
                        <div className="mr-auto max-w-[70%] rounded-2xl border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
                          Sentellent is thinking…
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="mt-3 rounded-2xl border border-zinc-200 bg-white/90 p-3 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-black/50">
                  <div className="flex items-end gap-2">
                    <textarea
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          if (!busy) send();
                        }
                      }}
                      rows={2}
                      placeholder={inputLocked ? "Confirm/Cancel the pending action above…" : "Message Sentellent…"}
                      disabled={busy || inputLocked}
                      className="min-h-[52px] flex-1 resize-none rounded-xl border border-zinc-300 bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-400 disabled:opacity-60 dark:border-zinc-700 dark:focus:ring-zinc-600"
                    />
                    <button
                      onClick={send}
                      disabled={busy || inputLocked || !message.trim() || !active}
                      className="h-[52px] rounded-xl bg-black px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800 disabled:opacity-60"
                      title={inputLocked ? "Confirm/Cancel the pending action first" : undefined}
                    >
                      Send
                    </button>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-zinc-500 dark:text-zinc-400">
                    <div>
                      {inputLocked ? "Input locked • confirm or cancel the pending action" : "Enter to send • Shift+Enter for newline"}
                    </div>

                    {inputLocked && (
                      <button
                        className="rounded-lg border border-zinc-300 px-2 py-1 text-[11px] hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
                        onClick={() => {
                          // emergency unlock (UI only)
                          setPendingEverywhere(null);
                          if (active) pushMsg(active.id, "system", "Pending UI cleared locally. If it reappears, backend still has a pending action.");
                        }}
                        disabled={busy}
                        title="If backend already cleared it but UI got stuck, this unlocks the input."
                      >
                        Force unlock
                      </button>
                    )}
                  </div>
                </div>

                <div className="mt-3 text-center text-[11px] text-zinc-500 dark:text-zinc-400">
                  Sentellent Agent Console
                </div>
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
