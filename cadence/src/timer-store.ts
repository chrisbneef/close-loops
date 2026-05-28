/**
 * Local timer state with pause/resume support.
 *
 * Single task at a time. Elapsed time is `accumulatedMs + (currentRunStartMs
 * → now)`. Pause captures the current run into accumulated and nulls out
 * currentRunStartMs; resume just sets currentRunStartMs to now. So the timer
 * picks up where it left off after an interruption — no zero-reset.
 *
 * Server is the source of truth for task status; this store is the visual
 * countdown. Reloads lose timer state (no localStorage rehydration in v1);
 * the server still has the task at status=in_progress or =paused, so the
 * widget will re-show the right buttons even if elapsed display starts at 0.
 */

import { create } from 'zustand';

interface TimerState {
  taskId: number | null;
  accumulatedMs: number;
  currentRunStartMs: number | null;

  start: (taskId: number) => void;
  pause: () => void;
  resume: () => void;
  reset: () => void;

  isActiveFor: (taskId: number | null) => boolean;       // taskId is the one currently in the timer
  isRunningFor: (taskId: number | null) => boolean;      // active AND not paused
  isPausedFor: (taskId: number | null) => boolean;       // active AND paused

  elapsedMs: (nowMs: number) => number;
  remainingMs: (durationMinutes: number, nowMs: number) => number;
}

export const useTimer = create<TimerState>((set, get) => ({
  taskId: null,
  accumulatedMs: 0,
  currentRunStartMs: null,

  start: (taskId) =>
    set({ taskId, accumulatedMs: 0, currentRunStartMs: Date.now() }),

  pause: () => {
    const s = get();
    if (s.taskId === null || s.currentRunStartMs === null) return;
    const runElapsed = Date.now() - s.currentRunStartMs;
    set({
      accumulatedMs: s.accumulatedMs + runElapsed,
      currentRunStartMs: null,
    });
  },

  resume: () => {
    const s = get();
    if (s.taskId === null) return;
    if (s.currentRunStartMs !== null) return; // already running
    set({ currentRunStartMs: Date.now() });
  },

  reset: () => set({ taskId: null, accumulatedMs: 0, currentRunStartMs: null }),

  isActiveFor: (taskId) => {
    const s = get();
    return taskId !== null && s.taskId === taskId;
  },

  isRunningFor: (taskId) => {
    const s = get();
    return taskId !== null && s.taskId === taskId && s.currentRunStartMs !== null;
  },

  isPausedFor: (taskId) => {
    const s = get();
    return taskId !== null && s.taskId === taskId && s.currentRunStartMs === null && s.accumulatedMs > 0;
  },

  elapsedMs: (nowMs) => {
    const s = get();
    if (s.taskId === null) return 0;
    if (s.currentRunStartMs === null) return s.accumulatedMs;
    return s.accumulatedMs + (nowMs - s.currentRunStartMs);
  },

  remainingMs: (durationMinutes, nowMs) => {
    const elapsed = get().elapsedMs(nowMs);
    return Math.max(0, durationMinutes * 60_000 - elapsed);
  },
}));

/** Format milliseconds as "MM:SS". */
export function formatTimer(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}
