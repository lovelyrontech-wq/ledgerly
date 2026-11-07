import type { Metadata } from "next";
import { Suspense } from "react";

import { FolderList } from "@/components/records/folder-list";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Folders" };

export default function FoldersPage() {
  return (
    <div className="mx-auto w-full max-w-3xl p-4 sm:p-6">
      <h1 className="text-xl font-semibold tracking-tight">Folders</h1>
      <p className="mb-4 text-sm text-muted-foreground">Pick a folder to see its records and talk to the assistant.</p>
      {/* On wide screens the sidebar already lists folders; here it is the main list, mostly for phones. */}
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <FolderList variant="cards" />
      </Suspense>
    </div>
  );
}
