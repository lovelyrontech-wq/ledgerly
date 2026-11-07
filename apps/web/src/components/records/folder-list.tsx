"use client";

import { FileText, Package } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useFolders } from "./use-folders";

const ICONS = { invoice: FileText, product: Package } as const;

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
    <nav className={cn(variant === "nav" ? "grid gap-0.5 p-2" : "grid gap-2 sm:grid-cols-2")}>
      {folders.map((folder) => {
        const Icon = ICONS[folder.type as keyof typeof ICONS] ?? FileText;
        const active = folder.id === folderId;
        return (
          <Link
            key={folder.id}
            href={`/folders/${folder.id}`}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-w-0 items-center gap-3 rounded-lg text-sm transition-colors",
              variant === "nav"
                ? "px-3 py-2 hover:bg-muted aria-[current=page]:bg-muted aria-[current=page]:font-medium"
                : "border p-4 hover:bg-muted/60",
            )}
          >
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{folder.name}</span>
            <Badge variant="outline" className="shrink-0 capitalize">
              {folder.role}
            </Badge>
          </Link>
        );
      })}
    </nav>
  );
}
