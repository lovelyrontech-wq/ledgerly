import { PrismaClient } from "@prisma/client";

// One client per process. In Next.js dev mode, hot reload re-runs modules,
// so the client is cached on globalThis to avoid opening a new connection each time.
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const prisma = globalForPrisma.prisma ?? new PrismaClient();

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}

export * from "@prisma/client";
