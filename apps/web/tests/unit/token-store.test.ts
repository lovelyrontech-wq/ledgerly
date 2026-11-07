import { beforeEach, describe, expect, it, vi } from "vitest";

import { tokenStore, type Session } from "@/lib/auth/token-store";

const session = (expiresInMs: number): Session => ({
  accessToken: "token-123",
  expiresAt: Date.now() + expiresInMs,
  user: { id: "usr_alice", email: "alice@ledgerly.test", name: "Alice Admin" },
});

describe("tokenStore", () => {
  beforeEach(() => {
    window.localStorage.clear();
    tokenStore.clear();
  });

  it("keeps the session and tells subscribers", () => {
    const listener = vi.fn();
    const unsubscribe = tokenStore.subscribe(listener);
    tokenStore.set(session(60_000));
    expect(tokenStore.get()?.accessToken).toBe("token-123");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("returns the same object until it changes (needed by useSyncExternalStore)", () => {
    tokenStore.set(session(60_000));
    expect(tokenStore.get()).toBe(tokenStore.get());
  });

  it("ignores an expired session", () => {
    window.localStorage.setItem("ledgerly.session", JSON.stringify(session(-1)));
    expect(tokenStore.get()).toBeNull();
  });

  it("ignores a corrupt value", () => {
    window.localStorage.setItem("ledgerly.session", "{not json");
    expect(tokenStore.get()).toBeNull();
  });

  it("clear signs out", () => {
    tokenStore.set(session(60_000));
    tokenStore.clear();
    expect(tokenStore.get()).toBeNull();
    expect(window.localStorage.getItem("ledgerly.session")).toBeNull();
  });
});
