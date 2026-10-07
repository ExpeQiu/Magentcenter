"use client";

import { useCallback, useRef, useState } from "react";
import { officeLog } from "@/components/kanban/office/office-log";
import {
  anchorFor,
  type BoardNote,
  type DriveBeat,
  type OfficeActor,
  type OfficePose,
} from "@/components/kanban/office/office-model";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function useOfficeDirector() {
  const [actors, setActors] = useState<OfficeActor[]>([]);
  const [notes, setNotes] = useState<BoardNote[]>([]);
  const [statusOverride, setStatusOverride] = useState<Record<string, string>>({});
  const [playing, setPlaying] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const playingRef = useRef(false);
  const actorsRef = useRef(actors);
  actorsRef.current = actors;
  const tokenRef = useRef(0);
  const pumpingRef = useRef(false);
  const queueRef = useRef<{ beats: DriveBeat[]; reason: string }[]>([]);

  const addNote = useCallback((author: string, text: string) => {
    const clean = text.trim();
    if (!clean) return;
    setNotes((prev) =>
      [
        {
          id: `${Date.now()}-${prev.length}`,
          author,
          text: clean,
          at: Date.now(),
        },
        ...prev,
      ].slice(0, 30)
    );
    officeLog("board", { author, text: clean.slice(0, 120) });
  }, []);

  const applyBeat = useCallback((beat: DriveBeat) => {
    if (beat.board) {
      const actor = beat.agentId
        ? actorsRef.current.find((item) => item.id === beat.agentId)
        : undefined;
      addNote(actor?.name || "白板", beat.board);
    }
    if (beat.taskId && beat.taskStatus) {
      setStatusOverride((prev) => ({ ...prev, [beat.taskId!]: beat.taskStatus! }));
      officeLog("task_override", { task_id: beat.taskId, status: beat.taskStatus });
    }
    if (!beat.agentId) return;
    setActors((prev) => {
      const actor = prev.find((item) => item.id === beat.agentId);
      if (!actor) {
        officeLog("pose_skip", { agent_id: beat.agentId || "", reason: "off_duty" });
        return prev;
      }
      const dest = anchorFor(beat.to || "desk", actor, prev);
      const pose: OfficePose = beat.pose || (beat.to && beat.to !== "desk" ? "walking" : "idle");
      officeLog("pose", {
        agent_id: actor.id,
        to: beat.to || "desk",
        pose,
        say: beat.say || "",
      });
      return prev.map((item) => {
        if (item.id !== actor.id) {
          if (!beat.say) return item;
          return {
            ...item,
            bubble: "",
            pose: item.pose === "talking" ? "idle" : item.pose,
          };
        }
        return { ...item, x: dest.x, y: dest.y, pose, bubble: beat.say || "" };
      });
    });
  }, [addNote]);

  const applyRef = useRef(applyBeat);
  applyRef.current = applyBeat;

  const finish = useCallback((token: number) => {
    if (tokenRef.current !== token) return;
    pumpingRef.current = false;
    playingRef.current = false;
    setPlaying(false);
    setEpoch((value) => value + 1);
  }, []);

  const pump = useCallback(async () => {
    if (pumpingRef.current) return;
    const token = tokenRef.current;
    pumpingRef.current = true;
    playingRef.current = true;
    setPlaying(true);
    try {
      while (queueRef.current.length > 0 && tokenRef.current === token) {
        const job = queueRef.current.shift();
        if (!job) break;
        officeLog("play_start", { reason: job.reason, beats: job.beats.length, play_id: token });
        for (const beat of job.beats) {
          if (tokenRef.current !== token) {
            officeLog("play_cancel", { play_id: token, reason: job.reason });
            return;
          }
          applyRef.current(beat);
          await sleep(beat.holdMs ?? 1200);
        }
        officeLog("play_end", { reason: job.reason, beats: job.beats.length, play_id: token });
      }
    } finally {
      finish(token);
    }
  }, [finish]);

  const play = useCallback(
    (beats: DriveBeat[], reason: string) => {
      if (beats.length === 0) return;
      queueRef.current.push({ beats, reason });
      officeLog("enqueue", { reason, beats: beats.length, queued: queueRef.current.length });
      void pump();
    },
    [pump]
  );

  const stop = useCallback(() => {
    tokenRef.current += 1;
    queueRef.current = [];
    officeLog("play_stop", { play_id: tokenRef.current });
    finish(tokenRef.current);
  }, [finish]);

  const syncDesks = useCallback((next: OfficeActor[]) => {
    if (playingRef.current) return;
    setActors(next);
  }, []);

  const clearOverrides = useCallback(() => setStatusOverride({}), []);

  return {
    actors,
    notes,
    statusOverride,
    playing,
    epoch,
    play,
    stop,
    syncDesks,
    addNote,
    clearOverrides,
  };
}
