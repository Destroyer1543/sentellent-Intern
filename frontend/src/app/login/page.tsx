"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { startGoogleAuth } from "@/lib/api";
import { setToken } from "@/lib/auth";

const QUOTES = [
  "For the enthusiasts",
  "Agentic workflows, no fluff",
  "Context that sticks",
  "Tools + confirmations",
  "Memory-driven assistants",
  "Less clutter. More signal.",
];

function getOrCreateUserId(): string {
  const key = "sentellent_user_id";
  const existing = localStorage.getItem(key);
  if (existing) return existing;

  const id =
    (globalThis.crypto?.randomUUID?.() || `u_${Math.random().toString(16).slice(2)}`) +
    "_" +
    Date.now().toString(16);

  localStorage.setItem(key, id);
  return id;
}

export default function LoginPage() {
  const router = useRouter();
  const [quoteIdx, setQuoteIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const t = setInterval(() => setQuoteIdx((i) => (i + 1) % QUOTES.length), 4200);
    return () => clearInterval(t);
  }, []);

  async function loginWithGoogle() {
    setMsg("");
    setBusy(true);
    try {
      const userId = getOrCreateUserId();
      const { auth_url } = await startGoogleAuth(userId);

      // After callback, backend redirects to /chat?connected=1
      window.location.href = auth_url;
    } catch (e: any) {
      setMsg(e?.message || "Failed to start Google OAuth.");
      setBusy(false);
    }
  }

  // If user hits /login manually after connecting, send them in
  useEffect(() => {
    // dev token is just to satisfy your isLoggedIn() guard.
    // Later: replace with real app session.
    const has = localStorage.getItem("sentellent_token");
    if (has) router.replace("/chat");
  }, [router]);

  return (
    <div className="min-h-screen bg-white text-black grid grid-cols-1 lg:grid-cols-5">
      {/* LEFT */}
      <div className="relative hidden lg:flex col-span-3 items-center justify-center overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.05] pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(#000 1px, transparent 1px), linear-gradient(90deg, #000 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />
        <div
          aria-hidden
          className="absolute -top-24 -left-24 h-[36rem] w-[36rem] rounded-full blur-3xl"
          style={{
            background:
              "radial-gradient(closest-side, rgba(0,0,0,0.12), rgba(0,0,0,0.03), transparent)",
          }}
        />
        <div className="relative w-full max-w-4xl px-12 py-20">
          <div className="font-extrabold tracking-tight text-5xl xl:text-7xl leading-[1.03] transition-opacity duration-500">
            {QUOTES[quoteIdx]}
          </div>
          <p className="mt-8 text-lg xl:text-xl text-gray-600 max-w-2xl">
            Sentellent — clean UI, strong agent loop, confirmation-gated tools.
          </p>
        </div>
      </div>

      {/* RIGHT */}
      <div className="col-span-2 flex items-center justify-center p-6 lg:p-10">
        <div className="w-full max-w-md bg-white/95 border border-gray-200 rounded-2xl shadow-xl">
          <div className="w-full bg-black flex items-center justify-center py-4 rounded-t-2xl">
            <div className="text-white font-semibold tracking-tight">Sentellent</div>
          </div>

          <div className="px-6 pt-4 pb-4 border-b border-gray-100 text-center">
            <h1 className="text-3xl font-bold tracking-tight">Sign in</h1>
            <p className="text-xs text-gray-500 mt-1">Continue with Google OAuth.</p>
          </div>

          <div className="p-6">
            <button
              onClick={() => {
                // set token BEFORE redirect so chat guard won't bounce
                setToken("dev-token");
                loginWithGoogle();
              }}
              disabled={busy}
              className="bg-black text-white w-full py-2.5 rounded-lg hover:bg-gray-800 disabled:opacity-60"
            >
              {busy ? "Redirecting…" : "Continue with Google"}
            </button>

            {msg ? <p className="text-center text-sm text-gray-600 mt-3">{msg}</p> : null}

            <div className="mt-6 text-center text-sm text-gray-500">
              This authorizes Gmail/Calendar access for your agent tools.
            </div>
          </div>

          <div className="px-6 py-3 bg-gray-50 border-t border-gray-100 text-[11px] text-gray-500 flex items-center justify-between rounded-b-2xl">
            <span>Agent Console</span>
            <span>Monochrome UI</span>
          </div>
        </div>
      </div>
    </div>
  );
}
