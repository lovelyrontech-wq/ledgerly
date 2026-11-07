import { z } from "zod";

// NEXT_PUBLIC_ values are inlined at build time, so they must be read as literal property accesses.
const schema = z.object({
  apiUrl: z.url().default("http://localhost:8000"),
});

export const env = schema.parse({
  apiUrl: process.env.NEXT_PUBLIC_API_URL || undefined,
});
