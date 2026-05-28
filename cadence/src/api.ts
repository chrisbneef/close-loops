/**
 * Tiny fetch wrapper around the Cadence brain backend.
 *
 * For dev: backend runs on http://localhost:8000. Web target (expo start --web)
 * hits this directly from the browser. Phone Expo Go needs the machine's LAN IP
 * — override via the EXPO_PUBLIC_API_BASE env var at expo start time, e.g.
 *   EXPO_PUBLIC_API_BASE=http://192.168.1.42:8000 npx expo start
 */

import { getToken, handleUnauthorized } from '@/src/auth-token';

const API_BASE =
  process.env.EXPO_PUBLIC_API_BASE ?? 'http://localhost:8000';

export interface AuthUser {
  id: number;
  name: string;
  email: string | null;
  role: string;
  timezone: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface SubtaskOut {
  id: number;
  task_id: number;
  position: number;
  title: string;
  completed: boolean;
  completed_at: string | null;
}

export type TaskStatus =
  | 'pending' | 'scheduled' | 'in_progress' | 'paused' | 'done' | 'decayed';

export interface TaskOut {
  id: number;
  title: string;
  description: string | null;
  owner_id: number;
  delegator_id: number | null;
  est_minutes: number;
  importance: number;
  status: TaskStatus;
  deadline: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  subtasks: SubtaskOut[];
}

export interface NextActionResponse {
  current: TaskOut | null;
  current_start: string | null;
  current_end: string | null;
  why: string | null;
  up_next: TaskOut[];
}

export interface GamificationOut {
  user_id: number;
  points: number;
  current_streak: number;
  longest_streak: number;
  last_action_at: string | null;
}

export interface PartnerPresence {
  user_id: number;
  user_name: string;
  status: 'focusing' | 'idle' | 'offline';
  current_task_id: number | null;
  current_task_title: string | null;
  updated_at: string | null;
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    // A 401 means the token is missing/expired — bounce to login. Skip the
    // bounce for the login call itself (bad credentials, not a dead session).
    if (res.status === 401 && path !== '/auth/login') {
      handleUnauthorized();
    }
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // body wasn't JSON; keep statusText
    }
    throw new Error(`${res.status} ${detail}`);
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  // -- auth --
  login(email: string, password: string): Promise<LoginResponse> {
    return jsonRequest<LoginResponse>(`/auth/login`, {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },
  getMe(): Promise<AuthUser> {
    return jsonRequest<AuthUser>(`/auth/me`);
  },

  getNextAction(ownerId: number): Promise<NextActionResponse> {
    return jsonRequest<NextActionResponse>(`/next-action?owner_id=${ownerId}`);
  },
  createTask(
    ownerId: number, title: string, estMinutes?: number, importance?: number,
  ): Promise<TaskOut> {
    return jsonRequest<TaskOut>(`/tasks`, {
      method: 'POST',
      body: JSON.stringify({
        owner_id: ownerId,
        title,
        ...(estMinutes ? { est_minutes: estMinutes } : {}),
        ...(importance ? { importance } : {}),
      }),
    });
  },
  // All of an owner's board-visible tasks (every status but decayed), subtasks
  // embedded. Done tasks capped to the recent window server-side.
  listTasks(ownerId: number, doneWithinDays?: number): Promise<TaskOut[]> {
    const q = doneWithinDays !== undefined ? `&done_within_days=${doneWithinDays}` : '';
    return jsonRequest<TaskOut[]>(`/tasks?owner_id=${ownerId}${q}`);
  },
  // Generic edit + backward/neutral status move (Kanban). Forward moves
  // (in_progress/paused/done) must use start/pause/done — server 409s otherwise.
  patchTask(
    taskId: number,
    fields: Partial<{ title: string; importance: number; est_minutes: number; deadline: string; status: 'pending' | 'scheduled' }>,
  ): Promise<TaskOut> {
    return jsonRequest<TaskOut>(`/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify(fields),
    });
  },
  startTask(taskId: number): Promise<void> {
    return jsonRequest<void>(`/tasks/${taskId}/start`, { method: 'POST' });
  },
  pauseTask(taskId: number, reason: string): Promise<void> {
    return jsonRequest<void>(`/tasks/${taskId}/pause`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },
  resumeTask(taskId: number): Promise<TaskOut> {
    return jsonRequest<TaskOut>(`/tasks/${taskId}/resume`, { method: 'POST' });
  },
  // /done returns the new NextAction so the UI can flip without a second poll.
  completeTask(taskId: number): Promise<NextActionResponse> {
    return jsonRequest<NextActionResponse>(`/tasks/${taskId}/done`, {
      method: 'POST',
    });
  },
  getGamification(ownerId: number): Promise<GamificationOut> {
    return jsonRequest<GamificationOut>(`/gamification?owner_id=${ownerId}`);
  },
  setPushToken(ownerId: number, pushToken: string): Promise<void> {
    return jsonRequest<void>(`/users/${ownerId}/push-token`, {
      method: 'POST',
      body: JSON.stringify({ push_token: pushToken }),
    });
  },
  // Returns null when there's no partner (solo team) or the partner has never
  // had a presence row. jsonRequest treats valid JSON `null` as `null`.
  getPartnerPresence(ownerId: number): Promise<PartnerPresence | null> {
    return jsonRequest<PartnerPresence | null>(
      `/presence/partner?owner_id=${ownerId}`,
    );
  },

  // -- subtasks (widget) --
  listSubtasks(taskId: number): Promise<SubtaskOut[]> {
    return jsonRequest<SubtaskOut[]>(`/tasks/${taskId}/subtasks`);
  },
  createSubtask(taskId: number, title: string, position?: number): Promise<SubtaskOut> {
    return jsonRequest<SubtaskOut>(`/tasks/${taskId}/subtasks`, {
      method: 'POST',
      body: JSON.stringify({ title, ...(position !== undefined ? { position } : {}) }),
    });
  },
  toggleSubtask(taskId: number, subtaskId: number, completed: boolean): Promise<SubtaskOut> {
    return jsonRequest<SubtaskOut>(`/tasks/${taskId}/subtasks/${subtaskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ completed }),
    });
  },
  deleteSubtask(taskId: number, subtaskId: number): Promise<void> {
    return jsonRequest<void>(`/tasks/${taskId}/subtasks/${subtaskId}`, { method: 'DELETE' });
  },
};
