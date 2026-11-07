"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, type components } from "@/lib/api/client";
import { useSession } from "@/lib/auth/token-store";

import { ApiError } from "./use-folders";

export type LedgerRecord = components["schemas"]["RecordOut"];

/** Statuses a record can have, per folder type. Mirrors STATUSES_BY_FOLDER_TYPE in the backend. */
export const STATUSES_BY_FOLDER_TYPE: Record<string, readonly string[]> = {
  invoice: ["draft", "sent", "paid", "overdue"],
  product: ["active", "archived"],
};

export const PAGE_SIZE = 25;

/** Key prefix for every records query of a folder, so the assistant can refresh them after apply/undo. */
export const recordsKey = (folderId: string) => ["records", folderId] as const;

export function useRecords(folderId: string, { status, page }: { status: string | null; page: number }) {
  const session = useSession();
  return useQuery({
    queryKey: [...recordsKey(folderId), { status, page, user: session?.user.id }],
    enabled: !!session,
    placeholderData: keepPreviousData, // keep the old page on screen while the next one loads
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/folders/{folder_id}/records", {
        params: {
          path: { folder_id: folderId },
          query: { status: status ?? undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE },
        },
      });
      if (!data) throw new ApiError(response.status, (error as { detail?: string })?.detail ?? "Could not load records");
      return data;
    },
  });
}

/** "12,345.60 EUR" style money, from integer cents. */
export function formatMoney(cents: number, currency: string) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(cents / 100);
  } catch {
    return `${(cents / 100).toFixed(2)} ${currency}`; // unknown currency code
  }
}
