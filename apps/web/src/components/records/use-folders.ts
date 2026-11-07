"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useSession } from "@/lib/auth/token-store";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function useFolders() {
  const session = useSession();
  return useQuery({
    queryKey: ["folders", session?.user.id],
    enabled: !!session, // signed out (or not known yet): show the skeleton, don't call the API
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/folders");
      if (!data) throw new ApiError(response.status, (error as { detail?: string })?.detail ?? "Could not load folders");
      return data;
    },
  });
}
