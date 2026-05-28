/**
 * Kanban click-to-move logic. Maps a target column to the right backend call:
 * forward transitions use the dedicated endpoints (so gamification / presence /
 * execution_log / interruptions side effects fire); the backward move to
 * "Up Next" uses the generic PATCH. On success, both the board list and the
 * widget/Now sidebar queries are invalidated so every surface re-renders.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, type TaskOut } from '@/src/api';

export type ColumnKey = 'whiteboard' | 'up_next' | 'in_progress' | 'paused' | 'done';

export const COLUMNS: { key: ColumnKey; label: string }[] = [
  { key: 'whiteboard', label: 'WHITE BOARD' },
  { key: 'up_next', label: 'UP NEXT' },
  { key: 'in_progress', label: 'IN PROGRESS' },
  { key: 'paused', label: 'PAUSED' },
  { key: 'done', label: 'DONE' },
];

/** Which board column a task's status belongs in. */
export function columnFor(status: TaskOut['status']): ColumnKey {
  switch (status) {
    case 'whiteboard': return 'whiteboard';
    case 'in_progress': return 'in_progress';
    case 'paused': return 'paused';
    case 'done': return 'done';
    default: return 'up_next'; // pending | scheduled
  }
}

export function useTaskMove(ownerId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ task, target, reason }: { task: TaskOut; target: ColumnKey; reason?: string }) => {
      switch (target) {
        case 'in_progress':
          return task.status === 'paused' ? api.resumeTask(task.id) : api.startTask(task.id);
        case 'paused':
          return api.pauseTask(task.id, reason ?? 'paused from board');
        case 'done':
          return api.completeTask(task.id);
        case 'whiteboard':
          return api.patchTask(task.id, { status: 'whiteboard' });
        case 'up_next':
          return api.patchTask(task.id, { status: 'pending' });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', ownerId] });
      qc.invalidateQueries({ queryKey: ['next-action', ownerId] });
    },
  });
}
