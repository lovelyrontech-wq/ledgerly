import type { Metadata } from "next";
import { Suspense } from "react";

import { FolderList } from "@/components/records/folder-list";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Folders" };

export default function FoldersPage() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-8 sm:py-12">
      <p className="text-xs font-semibold tracking-[0.14em] text-primary uppercase">Workspace</p>
      <h1 className="mt-2 text-3xl font-semibold sm:text-4xl">
        Your <span className="text-gradient">folders</span>
      </h1>
      <p className="mt-2 mb-8 max-w-prose text-sm text-muted-foreground sm:text-base">
        Pick a folder to see its records and ask the assistant. Bulk changes are always previewed first.
      </p>
      {/* On wide screens the sidebar already lists folders; here it is the main list, mostly for phones. */}
      <Suspense
        fallback={
          <div className="grid gap-3 sm:grid-cols-2">
            <Skeleton className="h-20 rounded-2xl" />
            <Skeleton className="h-20 rounded-2xl" />
          </div>
        }
      >
        <FolderList variant="cards" />
      </Suspense>
    </div>
  );
}
