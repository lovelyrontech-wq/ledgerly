"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useSession } from "@/lib/auth/token-store";

/**
 * Sends signed-out users to /login?next=<this page>.
 *
 * The shell and page skeletons always render, so Next.js can prerender them for instant navigation;
 * only the data waits for a session (queries use `enabled: !!session`). The token lives in the browser,
 * so the check runs on the client. The API checks the token on every request anyway.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session === null) {
      // window.location instead of usePathname: no Suspense needed, and it only runs on the client.
      const next = window.location.pathname + window.location.search;
      router.replace(`/login?next=${encodeURIComponent(next)}`);
    }
  }, [session, router]);

  return children;
}
