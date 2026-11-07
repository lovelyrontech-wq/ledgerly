"use client";

import { MessageSquare } from "lucide-react";

import { AssistantPanel } from "@/components/agent/assistant-panel";
import { useAssistant } from "@/components/agent/use-assistant";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";

import { RecordsTable } from "./records-table";
import { useFolders } from "./use-folders";

/**
 * One folder: records on the left, assistant on the right.
 * - lg and up: two columns side by side.
 * - below lg: records take the full width; the assistant opens in a bottom sheet.
 */
export function FolderWorkspace({ folderId }: { folderId: string }) {
  const { data: folders } = useFolders();
  const folder = folders?.find((f) => f.id === folderId);
  // One chat shared by the desktop column and the phone sheet.
  const assistant = useAssistant(folderId);

  return (
    <div className="grid min-h-[calc(100dvh-3.5rem)] lg:grid-cols-[minmax(0,1fr)_24rem]">
      <section className="min-w-0 p-4 sm:p-6" aria-labelledby="folder-title">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {folder ? (
            <h1 id="folder-title" className="min-w-0 flex-1 truncate text-xl font-semibold tracking-tight">
              {folder.name}
            </h1>
          ) : (
            <Skeleton className="h-7 flex-1 sm:max-w-48" />
          )}
          <Sheet>
            <SheetTrigger render={<Button variant="outline" size="sm" className="lg:hidden" />}>
              <MessageSquare />
              Assistant
            </SheetTrigger>
            <SheetContent side="bottom" className="p-0 data-[side=bottom]:h-[85dvh]">
              <SheetHeader className="border-b">
                <SheetTitle>Assistant</SheetTitle>
              </SheetHeader>
              <AssistantPanel assistant={assistant} />
            </SheetContent>
          </Sheet>
        </div>

        <RecordsTable key={folderId} folderId={folderId} folderType={folder?.type} />
      </section>

      <aside className="hidden border-l lg:flex lg:flex-col" aria-label="Assistant">
        <div className="sticky top-14 flex h-[calc(100dvh-3.5rem)] flex-col">
          <p className="border-b px-4 py-3 text-sm font-medium">Assistant</p>
          <AssistantPanel assistant={assistant} />
        </div>
      </aside>
    </div>
  );
}

export function FolderWorkspaceSkeleton() {
  return (
    <div className="grid gap-4 p-4 sm:p-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="grid gap-3">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
      <Skeleton className="hidden h-[60dvh] lg:block" />
    </div>
  );
}
