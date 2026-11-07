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
  paid: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  active: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  overdue: "bg-destructive/10 text-destructive",
  sent: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
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
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by status">
        {[null, ...statuses].map((s) => (
          <Button
            key={s ?? "all"}
            size="sm"
            variant={status === s ? "secondary" : "ghost"}
            aria-pressed={status === s}
            className="capitalize"
            onClick={() => chooseStatus(s)}
          >
            {s ?? "All"}
          </Button>
        ))}
        <Button
          size="icon-sm"
          variant="ghost"
          className="ml-auto"
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
            <Skeleton key={i} className="h-9" />
          ))}
        </div>
      ) : (
        <div className={cn("rounded-lg border transition-opacity", isPlaceholderData && "opacity-60")}>
          <Table>
            <TableHeader>
              <TableRow>
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
                  <TableRow key={record.id}>
                    <TableCell className="max-w-56 truncate font-medium">{record.name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(record.valueCents, record.currency)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className={cn("capitalize", STATUS_STYLE[record.status])}>
                        {record.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground sm:table-cell">
                      <time dateTime={record.updatedAt}>{new Date(record.updatedAt).toLocaleString()}</time>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span aria-live="polite">
          {from}–{to} of {total}
        </span>
        <Button
          size="icon-sm"
          variant="outline"
          className="ml-auto"
          aria-label="Previous page"
          disabled={page === 0}
          onClick={() => setPage((p) => p - 1)}
        >
          <ChevronLeft />
        </Button>
        <span className="tabular-nums">
          {page + 1} / {pageCount}
        </span>
        <Button
          size="icon-sm"
          variant="outline"
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
