/**
 * Local timer state. The server owns the task lifecycle (pending → in_progress
 * → done) via the start/done endpoints; this store owns the visual countdown
 * the user sees on the Now screen between those state transitions.
 *
 * Single source of timer truth: `startedAtMs` — wall-clock ms when the user
 * tapped Start. Elapsed and remaining are derived from `Date.now() - startedAtMs`
 * on each render tick. No drift, no separate paused/resumed state to track
 * (Pomodoro v1 doesn't support pause — push the simple thing first).
 */

import { create } from 'zustand';

interface TimerState {
  taskId: number | null;
  startedAtMs: number | null;

  start: (taskId: number) => void;
  reset: () => void;
  isRunningFor: (taskId: number | null) => boolean;
  remainingMs: (durationMinutes: number, nowMs: number) => number;
  elapsedMs: (nowMs: number) => number;
}

export const useTimer = create<TimerState>((set, get) => ({
  taskId: null,
  startedAtMs: null,

  start: (taskId) => set({ taskId, startedAtMs: Date.now() }),
  reset: () => set({ taskId: null, startedAtMs: null }),

  isRunningFor: (taskId) => {
    const s = get();
    return s.taskId === taskId && s.startedAtMs !== null;
  },

  remainingMs: (durationMinutes, nowMs) => {
    const s = get();
    if (s.startedAtMs === null) return durationMinutes * 60_000;
    const elapsed = nowMs - s.startedAtMs;
    return Math.max(0, durationMinutes * 60_000 - elapsed);
  },

  elapsedMs: (nowMs) => {
    const s = get();
    if (s.startedAtMs === null) return 0;
    return nowMs - s.startedAtMs;
  },
}));

/** Format milliseconds as "MM:SS". Used by the Now screen's countdown display. */
export function formatTimer(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}
