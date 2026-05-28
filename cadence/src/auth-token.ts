/**
 * Module-level token holder. Kept separate from the Zustand auth store and the
 * API wrapper so neither has to import the other (no circular dependency):
 *   - the auth store calls setToken() on login/logout/hydrate
 *   - api.ts reads getToken() on every request and calls handleUnauthorized()
 *     on a 401, which the store wires up to logout().
 */

let token: string | null = null;
let onUnauthorized: () => void = () => {};

export function getToken(): string | null {
  return token;
}

export function setToken(next: string | null): void {
  token = next;
}

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export function handleUnauthorized(): void {
  onUnauthorized();
}
