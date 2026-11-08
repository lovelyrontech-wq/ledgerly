"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { Suspense, useState, type ReactNode } from "react";

import { FolderList } from "@/components/records/folder-list";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";

import { Logo } from "./logo";
import { ThemeToggle } from "./theme-toggle";
import { UserMenu } from "./user-menu";

function FolderNavFallback() {
  return (
    <div className="grid gap-2 p-3">
      <Skeleton className="h-8" />
      <Skeleton className="h-8" />
      <Skeleton className="h-8" />
    </div>
  );
}

/**
 * Header + folder sidebar.
 * - md and up: the sidebar is always visible on the left.
 * - below md: the sidebar moves into a slide-in sheet opened from the menu button.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="app-backdrop flex min-h-dvh flex-col">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/70 px-3 backdrop-blur-xl backdrop-saturate-150 sm:px-5">
        <Sheet open={navOpen} onOpenChange={setNavOpen}>
          <SheetTrigger render={<Button variant="ghost" size="icon" className="md:hidden" aria-label="Open folders" />}>
            <Menu />
          </SheetTrigger>
          <SheetContent side="left" className="w-72 bg-sidebar p-0">
            <SheetHeader className="border-b">
              <SheetTitle>
                <Logo />
              </SheetTitle>
            </SheetHeader>
            {/* Active-link highlighting reads the URL, so it needs a Suspense boundary. */}
            <Suspense fallback={<FolderNavFallback />}>
              <FolderList variant="nav" onNavigate={() => setNavOpen(false)} />
            </Suspense>
          </SheetContent>
        </Sheet>

        <Link href="/folders" aria-label="Ledgerly home" className="rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
          <Logo />
        </Link>
        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <UserMenu />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-64 shrink-0 border-r bg-sidebar/60 backdrop-blur md:block" aria-label="Folders">
          <div className="sticky top-14 max-h-[calc(100dvh-3.5rem)] overflow-y-auto">
            <p className="px-5 pt-5 pb-1.5 text-[0.7rem] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
              Workspace
            </p>
            <Suspense fallback={<FolderNavFallback />}>
              <FolderList variant="nav" />
            </Suspense>
          </div>
        </aside>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
