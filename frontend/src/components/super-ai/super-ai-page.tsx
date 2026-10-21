"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Avatar, type AvatarPhase } from "@/components/super-ai/avatar";
import {
  api,
  type SuperAiPending,
  type SuperAiTurnResponse,
} from "@/lib/api";
import { getLastWorkspaceSlug } from "@/lib/context/workspace-context";
import { paths } from "@/lib/paths";
import type { TaskInfo } from "@/lib/types";

interface SpeechResultEvent {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
}

interface SpeechRec {
  lang: string;
  interimResults: boolean;
  onresult: ((ev: SpeechResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechCtor = new () => SpeechRec;

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  service?: string;
  href?: string;
  taskId?: string;
  taskStatus?: string;
}

const GREETING =
  "我是超级AI。可以直接聊天，也可以把事情交给已绑定的智能体。查任务、知识、技能和系统仍用原来的说法。分配任务会直接执行。";

const CHIPS = ["有哪些进行中的任务", "有哪些技能", "系统是否正常", "最近产出"];
const MOCK_UTTERANCE = "有哪些进行中的任务";
const THREAD_KEY = "super-ai-thread";
const SESSION_KEY = "super-ai-session";

const TASK_LABEL: Record<string, string> = {
  queued: "排队",
  running: "执行中",
  completed: "完成",
  failed: "失败",
  cancelled: "已取消",
};

function newId(): string {
  // randomUUID 只在 https 或 localhost 上存在。公网 http 用 getRandomValues。
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function sessionId(): string {
  const existing = sessionStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const id = newId();
  sessionStorage.setItem(SESSION_KEY, id);
  return id;
}

function taskBubble(task: TaskInfo): string {
  if (task.status === "completed") {
    const output = (task.output || "").trim() || "任务已完成。";
    return output.length > 280 ? `${output.slice(0, 279)}…` : output;
  }
  if (task.status === "failed") return (task.error || "").trim() || "任务失败。";
  if (task.status === "cancelled") return "任务已取消。";
  return `任务仍在${TASK_LABEL[task.status] || task.status}。`;
}

const SERVICE_LABEL: Record<string, string> = {
  tasks: "任务",
  knowledge: "知识库",
  skills: "技能",
  outputs: "输出物",
  system: "系统",
  fleet: "多端",
  navigate: "打开页面",
};

function loadThread(): ChatMessage[] {
  if (typeof sessionStorage === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(THREAD_KEY);
    const parsed = raw ? (JSON.parse(raw) as ChatMessage[]) : [];
    return Array.isArray(parsed) ? parsed.slice(-20) : [];
  } catch {
    return [];
  }
}

export function SuperAiPage() {
  const [slug, setSlug] = useState("cyber");
  const [phase, setPhase] = useState<AvatarPhase>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<SuperAiPending | null>(null);
  const [confirmationId, setConfirmationId] = useState("");
  const [watching, setWatching] = useState<string[]>([]);
  const [lastHref, setLastHref] = useState("");
  const [mockMode, setMockMode] = useState(true);
  const [providerOpen, setProviderOpen] = useState(false);
  const [providerBase, setProviderBase] = useState("");
  const [providerModel, setProviderModel] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [providerKeySet, setProviderKeySet] = useState(false);
  const [providerNote, setProviderNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [voiceHint, setVoiceHint] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const recRef = useRef<SpeechRec | null>(null);
  const heardRef = useRef("");
  const holdingRef = useRef(false);

  useEffect(() => {
    setSlug(getLastWorkspaceSlug());
    setMessages(loadThread());
    api
      .health()
      .then((h) => setMockMode(Boolean(h.mock_mode)))
      .catch(() => setMockMode(true));
    api
      .superAiProvider()
      .then((row) => {
        setProviderBase(row.base_url || "");
        setProviderModel(row.model || "");
        setProviderKeySet(Boolean(row.api_key_set));
      })
      .catch((err) => {
        console.warn("super_ai provider", err);
      });
  }, []);

  useEffect(() => {
    sessionStorage.setItem(THREAD_KEY, JSON.stringify(messages.slice(-20)));
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages]);

  function speak(text: string) {
    const synth = window.speechSynthesis;
    if (!synth) {
      setPhase("speaking");
      window.setTimeout(() => setPhase("idle"), 1600);
      return;
    }
    synth.cancel();
    const utter = new SpeechSynthesisUtterance(text.replace(/\n/g, "。"));
    utter.lang = "zh-CN";
    utter.onstart = () => setPhase("speaking");
    utter.onend = () => setPhase("idle");
    utter.onerror = () => setPhase("idle");
    synth.speak(utter);
  }

  async function send(text: string, fromVoice = false) {
    const content = text.trim();
    if (!content || busy) return;
    window.speechSynthesis?.cancel();
    setDraft("");
    setBusy(true);
    setPhase("thinking");
    setVoiceHint("");
    const userMsg: ChatMessage = {
      id: `${Date.now()}-u`,
      role: "user",
      text: content,
    };
    setMessages((prev) => [...prev, userMsg]);
    try {
      const res = await api.superAiTurn({
        text: content,
        workspace_slug: slug,
        pending,
        last_href: lastHref,
        session_id: sessionId(),
        confirmation_id: content === "确认" ? confirmationId : "",
      });
      console.info(
        "super_ai turn",
        JSON.stringify({
          run_id: res.run_id,
          intent: res.intent,
          service: res.service,
        })
      );
      pushReply(res);
      if (fromVoice) speak(res.reply);
      else {
        setPhase("speaking");
        window.setTimeout(() => setPhase("idle"), Math.min(2200, 600 + res.reply.length * 28));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "请求失败";
      setMessages((prev) => [
        ...prev,
        { id: `${Date.now()}-e`, role: "assistant", text: message },
      ]);
      setPhase("idle");
    } finally {
      setBusy(false);
    }
  }

  function pushReply(res: SuperAiTurnResponse) {
    setPending(res.pending);
    setConfirmationId(res.confirmation_id || "");
    if (res.href) setLastHref(res.href);
    setMessages((prev) => [
      ...prev,
      {
        id: res.run_id,
        role: "assistant",
        text: res.reply,
        service: res.service,
        href: res.href,
        taskId: res.task_id || undefined,
        taskStatus: res.task_status || undefined,
      },
    ]);
    if (res.task_id) {
      setWatching((prev) => (prev.includes(res.task_id as string) ? prev : [...prev, res.task_id as string]));
    }
  }

  useEffect(() => {
    if (watching.length === 0) return;
    let stop = false;
    const tick = async () => {
      for (const id of watching) {
        try {
          const task = await api.task(id);
          if (stop) return;
          console.info(
            "super_ai task",
            JSON.stringify({ task_id: task.id, status: task.status })
          );
          setMessages((prev) => {
            const marker = `status-${task.id}-${task.status}`;
            if (prev.some((item) => item.id === marker)) return prev;
            return [
              ...prev,
              {
                id: marker,
                role: "assistant" as const,
                text: taskBubble(task),
                service: "tasks",
                href: paths.workspace(slug).taskDetail(task.id),
                taskId: task.id,
                taskStatus: task.status,
              },
            ];
          });
          if (task.status === "completed" || task.status === "failed" || task.status === "cancelled") {
            setWatching((prev) => prev.filter((item) => item !== id));
          }
        } catch (err) {
          console.warn("super_ai task poll", id, err);
        }
      }
    };
    void tick();
    const timer = window.setInterval(() => {
      void tick();
    }, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [watching, slug]);

  async function saveProvider() {
    try {
      const body: { base_url: string; model: string; api_key?: string } = {
        base_url: providerBase.trim(),
        model: providerModel.trim(),
      };
      if (providerKey.trim()) body.api_key = providerKey.trim();
      const saved = await api.superAiProviderUpdate(body);
      setProviderBase(saved.base_url || "");
      setProviderModel(saved.model || "");
      setProviderKey("");
      setProviderKeySet(Boolean(saved.api_key_set));
      setProviderNote("已保存");
      console.info(
        "super_ai provider",
        JSON.stringify({ model: saved.model, key_set: saved.api_key_set })
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存失败";
      setProviderNote(message);
      console.warn("super_ai provider save", err);
    }
  }

  function speechCtor(): SpeechCtor | null {
    const w = window as Window & {
      SpeechRecognition?: SpeechCtor;
      webkitSpeechRecognition?: SpeechCtor;
    };
    return w.SpeechRecognition || w.webkitSpeechRecognition || null;
  }

  function holdStart() {
    if (busy || holdingRef.current) return;
    holdingRef.current = true;
    heardRef.current = "";
    setPhase("listening");
    if (mockMode || !speechCtor()) {
      setVoiceHint(mockMode ? "Mock：松手后发送示例语句" : "当前浏览器不能识别语音，松手后改用示例语句");
      return;
    }
    const rec = new (speechCtor() as SpeechCtor)();
    rec.lang = "zh-CN";
    rec.interimResults = false;
    rec.onresult = (ev) => {
      heardRef.current = ev.results[0]?.[0]?.transcript || "";
    };
    rec.onerror = () => {
      heardRef.current = "";
    };
    recRef.current = rec;
    try {
      rec.start();
    } catch {
      setVoiceHint("麦克风没有打开，请改用文字。");
    }
  }

  function holdEnd() {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    if (busy) return;
    const rec = recRef.current;
    recRef.current = null;
    if (mockMode || !rec) {
      setPhase("thinking");
      void send(MOCK_UTTERANCE, true);
      return;
    }
    rec.onend = () => {
      const heard = heardRef.current.trim();
      if (!heard) {
        setPhase("idle");
        setVoiceHint("没有听清，请再说一次或改用文字。");
        return;
      }
      void send(heard, true);
    };
    try {
      rec.stop();
    } catch {
      setPhase("idle");
    }
  }

  const shown = messages.length
    ? messages
    : [{ id: "greet", role: "assistant" as const, text: GREETING }];

  return (
    <div className="flex h-screen flex-col bg-slate-950">
      <header className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
        <div>
          <p className="text-xs tracking-widest text-indigo-300/80">AGENTCENTER</p>
          <h1 className="text-lg font-semibold">超级AI</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/bind"
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            绑定终端
          </Link>
          <button
            type="button"
            onClick={() => setProviderOpen((open) => !open)}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            模型
          </button>
          <Link
            href={paths.root(slug)}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            进入控制台
          </Link>
        </div>
      </header>
      {providerOpen ? (
        <form
          className="flex flex-wrap items-end gap-2 border-b border-slate-800 px-5 py-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            void saveProvider();
          }}
        >
          <label className="flex min-w-52 flex-1 flex-col gap-1 text-xs text-slate-400">
            Host
            <input
              value={providerBase}
              onChange={(e) => setProviderBase(e.target.value)}
              placeholder="https://api.example.com/v1"
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
            />
          </label>
          <label className="flex w-40 flex-col gap-1 text-xs text-slate-400">
            模型
            <input
              value={providerModel}
              onChange={(e) => setProviderModel(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
            />
          </label>
          <label className="flex w-44 flex-col gap-1 text-xs text-slate-400">
            Key
            <input
              type="password"
              value={providerKey}
              onChange={(e) => setProviderKey(e.target.value)}
              placeholder={providerKeySet ? "已设置，留空不改" : "本地服务可留空"}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
            />
          </label>
          <button type="submit" className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm">
            保存
          </button>
          {providerNote ? <span className="pb-1 text-xs text-slate-400">{providerNote}</span> : null}
        </form>
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(280px,420px)_1fr]">
        <section className="flex items-center justify-center border-b border-slate-800 py-8 lg:border-b-0 lg:border-r">
          <Avatar phase={phase} />
        </section>

        <section className="flex min-h-0 flex-col">
          <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
            {shown.map((msg) => (
              <div
                key={msg.id}
                className={`max-w-[40rem] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "ml-auto bg-indigo-600 text-white"
                    : "bg-slate-900 text-slate-200"
                }`}
              >
                {msg.service ? (
                  <p className="mb-1 text-xs text-indigo-300">
                    {SERVICE_LABEL[msg.service] || msg.service}
                  </p>
                ) : null}
                <p className="whitespace-pre-wrap">{msg.text}</p>
                {msg.href ? (
                  <Link href={msg.href} className="mt-2 inline-block text-indigo-300 underline">
                    打开
                  </Link>
                ) : null}
              </div>
            ))}
          </div>

          {messages.length === 0 ? (
            <div className="flex flex-wrap gap-2 px-5 pb-2">
              {CHIPS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  onClick={() => void send(chip)}
                  className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800"
                >
                  {chip}
                </button>
              ))}
            </div>
          ) : null}

          {pending ? (
            <div className="mx-5 mb-2 flex items-center justify-between gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
              <span className="truncate">待确认：{pending.prompt}</span>
              <span className="flex shrink-0 gap-2">
                <button type="button" onClick={() => void send("确认")} className="underline">
                  确认
                </button>
                <button type="button" onClick={() => void send("取消")} className="underline">
                  取消
                </button>
              </span>
            </div>
          ) : null}

          <form
            className="border-t border-slate-800 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              void send(draft);
            }}
          >
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(draft);
                  }
                }}
                rows={2}
                placeholder="输入文字，或按住说话"
                className="min-h-14 flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <button
                type="button"
                aria-label="按住说话"
                onPointerDown={(e) => {
                  e.preventDefault();
                  (e.currentTarget as HTMLButtonElement).setPointerCapture(e.pointerId);
                  holdStart();
                }}
                onPointerUp={holdEnd}
                onPointerCancel={holdEnd}
                className={`h-14 rounded-xl px-4 text-sm ${
                  phase === "listening"
                    ? "bg-rose-600 text-white"
                    : "bg-slate-800 text-slate-200 hover:bg-slate-700"
                }`}
              >
                按住说话
              </button>
              <button
                type="submit"
                disabled={busy || !draft.trim()}
                className="h-14 rounded-xl bg-indigo-600 px-4 text-sm font-medium disabled:opacity-40"
              >
                发送
              </button>
            </div>
            {voiceHint ? <p className="mt-2 text-xs text-slate-500">{voiceHint}</p> : null}
          </form>
        </section>
      </div>
    </div>
  );
}
