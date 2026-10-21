"use client";

import { useEffect, useState } from "react";
import { sessionUnlocked, subscribeUnauthorized, unlockSession } from "@/lib/api";

export function EntryGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<"checking" | "locked" | "open">("checking");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    sessionUnlocked()
      .then((unlocked) => {
        if (!cancelled) setPhase(unlocked ? "open" : "locked");
      })
      .catch(() => {
        if (!cancelled) setPhase("locked");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => subscribeUnauthorized(() => setPhase("locked")), []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await unlockSession(code);
      if (!result.ok) {
        setError(result.detail || "鉴权码不正确");
        return;
      }
      setCode("");
      setPhase("open");
    } catch {
      setError("无法连接服务");
    } finally {
      setBusy(false);
    }
  }

  if (phase === "open") return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
      {phase === "checking" ? (
        <p className="text-sm text-slate-400">正在确认访问</p>
      ) : (
        <form
          onSubmit={onSubmit}
          className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-6"
        >
          <p className="text-xs tracking-widest text-indigo-300/80">AGENTCENTER</p>
          <h1 className="mt-1 text-lg font-semibold">进入控制台</h1>
          <p className="mt-2 text-sm text-slate-400">输入鉴权码后继续。</p>
          <input
            type="password"
            autoComplete="current-password"
            autoFocus
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="鉴权码"
            className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}
          <button
            type="submit"
            disabled={busy || !code.trim()}
            className="mt-4 w-full rounded-lg bg-indigo-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            {busy ? "校验中" : "进入"}
          </button>
        </form>
      )}
    </div>
  );
}
