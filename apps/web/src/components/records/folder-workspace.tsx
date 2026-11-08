"use client";

import { Sparkles } from "lucide-react";

import { AssistantPanel } from "@/components/agent/assistant-panel";
import { useAssistant } from "@/components/agent/use-assistant";
import { Badge } from "@/components/ui/badge";
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
    <div className="grid min-h-[calc(100dvh-3.5rem)] lg:grid-cols-[minmax(0,1fr)_24rem] xl:grid-cols-[minmax(0,1fr)_26rem]">
      <section className="min-w-0 px-4 py-6 sm:px-8 sm:py-8" aria-labelledby="folder-title">
        <div className="mb-6 flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            {folder ? (
              <>
                <div className="mb-1.5 flex items-center gap-2">
                  <Badge variant="secondary" className="capitalize">
                    {folder.type}s
                  </Badge>
                  <Badge variant="outline" className="capitalize">
                    {folder.role}
                  </Badge>
                </div>
                <h1 id="folder-title" className="truncate text-2xl font-semibold sm:text-3xl">
                  {folder.name}
                </h1>
              </>
            ) : (
              <Skeleton className="h-9 w-full sm:max-w-64" />
            )}
          </div>
          <Sheet>
            <SheetTrigger
              render={<Button size="sm" className="rounded-full px-4 shadow-md shadow-primary/25 lg:hidden" />}
            >
              <Sparkles />
              Assistant
            </SheetTrigger>
            <SheetContent side="bottom" className="rounded-t-3xl p-0 data-[side=bottom]:h-[88dvh]">
              <SheetHeader className="border-b">
                <SheetTitle className="flex items-center gap-2">
                  <span className="brand-gradient grid size-6 place-items-center rounded-lg text-white">
                    <Sparkles className="size-3.5" />
                  </span>
                  Assistant
                </SheetTitle>
              </SheetHeader>
              <AssistantPanel assistant={assistant} />
            </SheetContent>
          </Sheet>
        </div>

        <RecordsTable key={folderId} folderId={folderId} folderType={folder?.type} />
      </section>

      <aside className="hidden border-l bg-card/60 backdrop-blur lg:flex lg:flex-col" aria-label="Assistant">
        <div className="sticky top-14 flex h-[calc(100dvh-3.5rem)] flex-col">
          <div className="flex items-center gap-2.5 border-b px-4 py-3">
            <span className="brand-gradient grid size-7 place-items-center rounded-lg text-white shadow-sm shadow-primary/30">
              <Sparkles className="size-4" />
            </span>
            <div className="leading-tight">
              <p className="font-heading text-sm font-semibold">Assistant</p>
              <p className="text-[0.7rem] text-muted-foreground">Previews changes · you approve</p>
            </div>
          </div>
          <AssistantPanel assistant={assistant} />
        </div>
      </aside>
    </div>
  );
}

export function FolderWorkspaceSkeleton() {
  return (
    <div className="grid gap-4 px-4 py-6 sm:px-8 sm:py-8 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="grid content-start gap-3">
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-80 w-full rounded-2xl" />
      </div>
      <Skeleton className="hidden h-[60dvh] lg:block" />
    </div>
  );
}
