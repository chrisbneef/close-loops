/**
 * Tiny fetch wrapper around the Cadence brain backend.
 *
 * For dev: backend runs on http://localhost:8000. Web target (expo start --web)
 * hits this directly from the browser. Phone Expo Go needs the machine's LAN IP
 * — override via the EXPO_PUBLIC_API_BASE env var at expo start time, e.g.
 *   EXPO_PUBLIC_API_BASE=http://192.168.1.42:8000 npx expo start
 */

const API_BASE =
  process.env.EXPO_PUBLIC_API_BASE ?? 'http://localhost:8000';

export interface TaskOut {
  id: number;
  title: string;
  description: string | null;
  owner_id: number;
  delegator_id: number | null;
  est_minutes: number;
  importance: number;
  status: string;
  deadline: string | null;
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
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
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
  getNextAction(ownerId: number): Promise<NextActionResponse> {
    return jsonRequest<NextActionResponse>(`/next-action?owner_id=${ownerId}`);
  },
  startTask(taskId: number): Promise<void> {
    return jsonRequest<void>(`/tasks/${taskId}/start`, { method: 'POST' });
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
  // Returns null when there's no partner (solo team) or the partner has never
  // had a presence row. jsonRequest treats valid JSON `null` as `null`.
  getPartnerPresence(ownerId: number): Promise<PartnerPresence | null> {
    return jsonRequest<PartnerPresence | null>(
      `/presence/partner?owner_id=${ownerId}`,
    );
  },
};
