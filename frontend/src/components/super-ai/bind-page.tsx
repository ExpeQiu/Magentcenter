"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

export function BindPage() {
  const params = useSearchParams();
  const [code, setCode] = useState(params.get("code") || "");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const claimed = await api.pairClaim(code.trim());
      setMessage(`已绑定 ${claimed.name || claimed.device_id}。设备会自己取回令牌。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "绑定失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-6"
      >
        <p className="text-xs tracking-widest text-indigo-300/80">AGENTCENTER</p>
        <h1 className="mt-1 text-lg font-semibold">绑定终端</h1>
        <p className="mt-2 text-sm text-slate-400">
          输入设备屏幕或串口上的 6 位验证码。长期令牌不会出现在这个页面。
        </p>
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
          placeholder="6 位验证码"
          className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-center text-lg tracking-[0.4em]"
        />
        {message ? <p className="mt-3 text-sm text-emerald-300">{message}</p> : null}
        {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}
        <button
          type="submit"
          disabled={busy || code.length !== 6}
          className="mt-4 w-full rounded-lg bg-indigo-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {busy ? "绑定中" : "确认绑定"}
        </button>
        <Link href="/" className="mt-4 block text-center text-sm text-slate-400 hover:text-slate-200">
          返回超级AI
        </Link>
      </form>
    </div>
  );
}
