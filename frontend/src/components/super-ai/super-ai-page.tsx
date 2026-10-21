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
}

const GREETING =
  "我是超级AI。可以直接说：查进行中的任务、建任务、查知识、看技能、看最近产出，或问系统是否正常。写操作我会先跟你确认。";

const CHIPS = ["有哪些进行中的任务", "有哪些技能", "系统是否正常", "最近产出"];
const MOCK_UTTERANCE = "有哪些进行中的任务";
const THREAD_KEY = "super-ai-thread";

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
  const [lastHref, setLastHref] = useState("");
  const [mockMode, setMockMode] = useState(true);
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
    if (res.href) setLastHref(res.href);
    setMessages((prev) => [
      ...prev,
      {
        id: res.run_id,
        role: "assistant",
        text: res.reply,
        service: res.service,
        href: res.href,
      },
    ]);
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
        <Link
          href={paths.root(slug)}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          进入控制台
        </Link>
      </header>

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
