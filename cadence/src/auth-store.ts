/**
 * Auth state (Zustand). Holds the session token + cached user, persists them
 * across launches, and exposes login/logout. `hydrated` gates the root layout
 * so we don't flash the login screen before the stored token is read back.
 *
 * The module also wires a 401 handler: any API call that comes back 401 (dead
 * or missing token) clears the session, which flips the router guard back to
 * the login screen.
 */

import { create } from 'zustand';

import { api, type AuthUser } from '@/src/api';
import { setToken, setUnauthorizedHandler } from '@/src/auth-token';
import { storageDelete, storageGet, storageSet } from '@/src/storage';

const TOKEN_KEY = 'cadence.token';
const USER_KEY = 'cadence.user';

interface AuthState {
  hydrated: boolean;
  token: string | null;
  user: AuthUser | null;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuth = create<AuthState>((set) => ({
  hydrated: false,
  token: null,
  user: null,

  hydrate: async () => {
    const [token, userJson] = await Promise.all([
      storageGet(TOKEN_KEY),
      storageGet(USER_KEY),
    ]);
    if (token) setToken(token);
    let user: AuthUser | null = null;
    if (userJson) {
      try {
        user = JSON.parse(userJson) as AuthUser;
      } catch {
        user = null;
      }
    }
    set({ token: token ?? null, user, hydrated: true });
  },

  login: async (email, password) => {
    const res = await api.login(email, password);
    setToken(res.access_token);
    await Promise.all([
      storageSet(TOKEN_KEY, res.access_token),
      storageSet(USER_KEY, JSON.stringify(res.user)),
    ]);
    set({ token: res.access_token, user: res.user });
  },

  logout: async () => {
    setToken(null);
    await Promise.all([storageDelete(TOKEN_KEY), storageDelete(USER_KEY)]);
    set({ token: null, user: null });
  },
}));

// A 401 from any request clears the session → router guard shows login.
setUnauthorizedHandler(() => {
  void useAuth.getState().logout();
});
