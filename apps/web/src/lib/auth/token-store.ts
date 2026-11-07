"use client";

import { useSyncExternalStore } from "react";

/**
 * The login token from POST /api/auth/login, kept in localStorage so a reload stays signed in.
 *
 * Trade-off: localStorage is readable by any script on the page, so an XSS bug could steal the
 * token. It is fine for this local demo; production would use an httpOnly cookie set by the API.
 */

const KEY = "ledgerly.session";

export type Session = {
  accessToken: string;
  expiresAt: number; // ms since epoch
  user: { id: string; email: string; name: string };
};

/** Build a session from the login response; `expiresIn` is in seconds. */
export function sessionFromLogin(login: { accessToken: string; expiresIn: number; user: Session["user"] }): Session {
  return { accessToken: login.accessToken, expiresAt: Date.now() + login.expiresIn * 1000, user: login.user };
}

const listeners = new Set<() => void>();
let cached: Session | null | undefined;

function read(): Session | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    return session.expiresAt > Date.now() ? session : null;
  } catch {
    return null; // storage blocked (private mode) or corrupt value
  }
}

function notify() {
  cached = undefined;
  listeners.forEach((listener) => listener());
}

export const tokenStore = {
  get(): Session | null {
    if (typeof window === "undefined") return null;
    if (cached === undefined) cached = read();
    return cached;
  },
  set(session: Session) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(session));
    } catch {
      // Storage blocked: the session still lives in memory until reload.
    }
    cached = session;
    listeners.forEach((listener) => listener());
  },
  clear() {
    try {
      window.localStorage.removeItem(KEY);
    } catch {
      // ignore
    }
    notify();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    const onStorage = (event: StorageEvent) => {
      if (event.key === KEY) notify(); // signed in or out in another tab
    };
    window.addEventListener("storage", onStorage);
    return () => {
      listeners.delete(listener);
      window.removeEventListener("storage", onStorage);
    };
  },
};

/** The current session, or null. `undefined` while rendering on the server (not known yet). */
export function useSession(): Session | null | undefined {
  return useSyncExternalStore(tokenStore.subscribe, tokenStore.get, () => undefined);
}
