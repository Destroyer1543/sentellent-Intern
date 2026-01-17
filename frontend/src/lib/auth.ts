// src/lib/auth.ts (or /lib/auth.ts if you don't use /src)
export const AUTH_TOKEN_KEY = "sentellent_token";
export const USER_ID_KEY = "sentellent_user_id";

export function isLoggedIn(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean(localStorage.getItem(AUTH_TOKEN_KEY));
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuth() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  // keep user_id if you want, or clear it too:
  // localStorage.removeItem(USER_ID_KEY);
}
