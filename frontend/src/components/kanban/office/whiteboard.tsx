"use client";

import type { BoardNote } from "@/components/kanban/office/office-model";

interface OfficeWhiteboardProps {
  notes: BoardNote[];
  drive: string;
  playing: boolean;
  onDrive: (value: string) => void;
  onPlayDrive: () => void;
}

export function OfficeWhiteboard({
  notes,
  drive,
  playing,
  onDrive,
  onPlayDrive,
}: OfficeWhiteboardProps) {
  return (
    <section className="flex min-h-[220px] flex-1 flex-col rounded-2xl border border-slate-800 bg-slate-950/40">
      <div className="flex items-center justify-between px-4 py-2.5">
        <h2 className="text-sm font-medium">实时动态</h2>
        <span className="text-[11px] text-slate-500">{notes.length}</span>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 pb-3">
        {notes.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-xs text-slate-500">
            还没有人说话。在办公室下方输入一句，人会走出来。
          </p>
        ) : (
          notes.map((note) => (
            <article key={note.id} className="flex gap-2 text-xs">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-400" />
              <div className="min-w-0">
                <p className="text-slate-200">
                  <span className="text-slate-400">{note.author}</span> {note.text}
                </p>
                <p className="mt-0.5 text-[10px] text-slate-600">
                  {new Date(note.at).toLocaleTimeString("zh-CN", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </p>
              </div>
            </article>
          ))
        )}
      </div>
      <details className="border-t border-slate-800 px-4 py-2 text-xs text-slate-400">
        <summary className="cursor-pointer">外部驱动</summary>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          <code>agent 名字 board 说的话</code>、<code>agent 名字 visit 另一个</code>、
          <code>board 结论</code>。也可 POST <code>/api/kanban/office/drive</code>。
        </p>
        <textarea
          value={drive}
          onChange={(event) => onDrive(event.target.value)}
          rows={4}
          className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-[11px] text-slate-200"
        />
        <button
          type="button"
          onClick={onPlayDrive}
          disabled={playing}
          className="mt-2 rounded-lg border border-slate-700 px-3 py-1.5 text-xs hover:bg-slate-800 disabled:opacity-50"
        >
          播放驱动
        </button>
      </details>
    </section>
  );
}
