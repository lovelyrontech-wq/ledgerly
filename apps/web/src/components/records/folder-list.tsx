"use client";

import { ArrowUpRight, FileText, Package } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useFolders } from "./use-folders";

const ICONS = { invoice: FileText, product: Package } as const;
const TINTS: Record<string, string> = {
  invoice: "bg-primary/10 text-primary",
  product: "bg-brand-2/15 text-brand-2",
};

/**
 * The folders the user can open. Two looks:
 * - "nav": compact links for the sidebar / mobile sheet, with the open folder highlighted
 * - "cards": larger tappable rows for the /folders page
 * Uses useParams, so callers must wrap it in Suspense.
 */
export function FolderList({ variant, onNavigate }: { variant: "nav" | "cards"; onNavigate?: () => void }) {
  const { folderId } = useParams<{ folderId?: string }>();
  const { data: folders, isPending, isError, error } = useFolders();

  if (isPending) {
    return (
      <div className="grid gap-2 p-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className={variant === "cards" ? "h-16" : "h-8"} />
        ))}
      </div>
    );
  }
  if (isError) {
    return (
      <Alert variant="destructive" className="m-3 w-auto">
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (folders.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No folders yet.</p>;
  }

  return (
    <nav className={cn(variant === "nav" ? "grid gap-0.5 p-2" : "grid gap-3 sm:grid-cols-2")}>
      {folders.map((folder) => {
        const Icon = ICONS[folder.type as keyof typeof ICONS] ?? FileText;
        const tint = TINTS[folder.type] ?? "bg-muted text-muted-foreground";
        const active = folder.id === folderId;
        if (variant === "nav") {
          return (
            <Link
              key={folder.id}
              href={`/folders/${folder.id}`}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group relative flex min-w-0 items-center gap-3 rounded-xl px-3 py-2 text-sm text-sidebar-foreground/80 transition-colors",
                "hover:bg-sidebar-accent/70 hover:text-sidebar-foreground",
                "aria-[current=page]:bg-sidebar-accent aria-[current=page]:font-medium aria-[current=page]:text-sidebar-accent-foreground",
              )}
            >
              <span className={cn("grid size-7 shrink-0 place-items-center rounded-lg", tint)}>
                <Icon className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1 truncate">{folder.name}</span>
              <Badge variant="outline" className="shrink-0 text-[0.65rem] capitalize opacity-70">
                {folder.role}
              </Badge>
            </Link>
          );
        }
        return (
          <Link
            key={folder.id}
            href={`/folders/${folder.id}`}
            onClick={onNavigate}
            className="surface group flex min-w-0 items-center gap-4 p-4 transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5"
          >
            <span className={cn("grid size-11 shrink-0 place-items-center rounded-xl", tint)}>
              <Icon className="size-5" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{folder.name}</span>
              <span className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground capitalize">
                {folder.type}s
                <span className="size-1 rounded-full bg-muted-foreground/40" />
                {folder.role}
              </span>
            </span>
            <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-primary" />
          </Link>
        );
      })}
    </nav>
  );
}
