"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { formatMoney, PAGE_SIZE, STATUSES_BY_FOLDER_TYPE, useRecords, type LedgerRecord } from "./use-records";

type SortKey = "name" | "valueCents" | "status" | "updatedAt";
type Sort = { key: SortKey; dir: "asc" | "desc" };

const STATUS_STYLE: Record<string, string> = {
  paid: "bg-success/12 text-success",
  active: "bg-success/12 text-success",
  overdue: "bg-destructive/10 text-destructive",
  sent: "bg-brand-2/15 text-brand-2",
  draft: "bg-warning/15 text-warning",
};

function compare(a: LedgerRecord, b: LedgerRecord, key: SortKey) {
  const x = a[key];
  const y = b[key];
  if (typeof x === "number" && typeof y === "number") return x - y;
  return String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: "base" });
}

function SortHeader({
  label,
  column,
  sort,
  onSort,
  className,
}: {
  label: string;
  column: SortKey;
  sort: Sort | null;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = sort?.key === column;
  const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead
      className={className}
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
    >
      <Button variant="ghost" size="xs" className="-ml-2" onClick={() => onSort(column)}>
        {label}
        <Icon className={cn(!active && "opacity-40")} />
      </Button>
    </TableHead>
  );
}

/**
 * Records of one folder. The status filter and paging run on the server; sorting by a column
 * reorders the page on screen (the API returns records sorted by name).
 */
export function RecordsTable({ folderId, folderType }: { folderId: string; folderType: string | undefined }) {
  const [status, setStatus] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<Sort | null>(null);
  const { data, isPending, isError, error, isFetching, refetch, isPlaceholderData } = useRecords(folderId, {
    status,
    page,
  });

  const rows = useMemo(() => {
    const items = data?.items ?? [];
    if (!sort) return items;
    const sorted = [...items].sort((a, b) => compare(a, b, sort.key));
    return sort.dir === "asc" ? sorted : sorted.reverse();
  }, [data, sort]);

  const statuses = folderType ? (STATUSES_BY_FOLDER_TYPE[folderType] ?? []) : [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);

  function chooseStatus(next: string | null) {
    setStatus(next);
    setPage(0);
  }

  function toggleSort(key: SortKey) {
    setSort((current) => {
      if (current?.key !== key) return { key, dir: "asc" };
      if (current.dir === "asc") return { key, dir: "desc" };
      return null; // third click: back to the server's order
    });
  }

  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2">
        <div
          className="-mx-1 flex min-w-0 flex-1 gap-1 overflow-x-auto px-1 py-0.5 [scrollbar-width:none]"
          role="group"
          aria-label="Filter by status"
        >
          {[null, ...statuses].map((s) => (
            <Button
              key={s ?? "all"}
              size="sm"
              variant="ghost"
              aria-pressed={status === s}
              className={cn(
                "shrink-0 rounded-full border border-transparent px-3.5 text-muted-foreground capitalize",
                "aria-pressed:border-primary/20 aria-pressed:bg-primary/10 aria-pressed:text-primary aria-pressed:hover:bg-primary/15",
              )}
              onClick={() => chooseStatus(s)}
            >
              {s ?? "All"}
            </Button>
          ))}
        </div>
        <Button
          size="icon-sm"
          variant="outline"
          className="shrink-0 rounded-full"
          aria-label="Reload records"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw className={cn(isFetching && "animate-spin")} />
        </Button>
      </div>

      {isError ? (
        <Alert variant="destructive">
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ) : isPending ? (
        <div className="grid gap-2">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-11 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className={cn("surface overflow-hidden transition-opacity", isPlaceholderData && "opacity-60")}>
          <Table>
            <TableHeader className="bg-muted/50 [&_th]:h-10 [&_th]:text-xs [&_th]:font-semibold [&_th]:tracking-wide [&_th]:text-muted-foreground">
              <TableRow className="hover:bg-transparent">
                <SortHeader label="Name" column="name" sort={sort} onSort={toggleSort} />
                <SortHeader label="Value" column="valueCents" sort={sort} onSort={toggleSort} className="text-right" />
                <SortHeader label="Status" column="status" sort={sort} onSort={toggleSort} />
                <SortHeader
                  label="Updated"
                  column="updatedAt"
                  sort={sort}
                  onSort={toggleSort}
                  className="hidden sm:table-cell"
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                    No records{status ? ` with status “${status}”` : ""}.
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((record) => (
                  <TableRow key={record.id} className="transition-colors hover:bg-accent/40 [&_td]:py-3">
                    <TableCell className="max-w-40 truncate font-medium sm:max-w-72">{record.name}</TableCell>
                    <TableCell className="text-right font-mono text-[0.8rem] tabular-nums">
                      {formatMoney(record.valueCents, record.currency)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className={cn("gap-1.5 capitalize", STATUS_STYLE[record.status])}>
                        <span className="size-1.5 rounded-full bg-current" aria-hidden />
                        {record.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground sm:table-cell">
                      <time dateTime={record.updatedAt}>
                        {new Date(record.updatedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                      </time>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground">
        <span aria-live="polite" className="tabular-nums">
          {from}–{to} of {total}
        </span>
        <Button
          size="icon-sm"
          variant="outline"
          className="ml-auto rounded-full"
          aria-label="Previous page"
          disabled={page === 0}
          onClick={() => setPage((p) => p - 1)}
        >
          <ChevronLeft />
        </Button>
        <span className="min-w-12 text-center font-mono text-xs tabular-nums">
          {page + 1} / {pageCount}
        </span>
        <Button
          size="icon-sm"
          variant="outline"
          className="rounded-full"
          aria-label="Next page"
          disabled={page + 1 >= pageCount || isPlaceholderData}
          onClick={() => setPage((p) => p + 1)}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
