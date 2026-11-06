-- CreateTable
CREATE TABLE "users" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "email" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "folders" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "ownerId" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "folders_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "users" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "folder_permissions" (
    "folderId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY ("folderId", "userId"),
    CONSTRAINT "folder_permissions_folderId_fkey" FOREIGN KEY ("folderId") REFERENCES "folders" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "folder_permissions_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "records" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "folderId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "valueCents" INTEGER NOT NULL,
    "currency" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "fields" JSONB NOT NULL,
    "version" INTEGER NOT NULL DEFAULT 1,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "records_folderId_fkey" FOREIGN KEY ("folderId") REFERENCES "folders" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "batches" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "folderId" TEXT NOT NULL,
    "createdBy" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "instruction" TEXT NOT NULL,
    "idempotencyKey" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" DATETIME,
    "appliedAt" DATETIME,
    "undoneAt" DATETIME,
    CONSTRAINT "batches_folderId_fkey" FOREIGN KEY ("folderId") REFERENCES "folders" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "batches_createdBy_fkey" FOREIGN KEY ("createdBy") REFERENCES "users" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "batch_items" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "batchId" TEXT NOT NULL,
    "recordId" TEXT NOT NULL,
    "field" TEXT NOT NULL DEFAULT 'valueCents',
    "before" INTEGER NOT NULL,
    "after" INTEGER NOT NULL,
    "expectedVersion" INTEGER NOT NULL,
    "result" TEXT,
    "error" TEXT,
    CONSTRAINT "batch_items_batchId_fkey" FOREIGN KEY ("batchId") REFERENCES "batches" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "batch_items_recordId_fkey" FOREIGN KEY ("recordId") REFERENCES "records" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "audit_log" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "batchId" TEXT,
    "details" JSONB NOT NULL,
    "at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "audit_log_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "audit_log_batchId_fkey" FOREIGN KEY ("batchId") REFERENCES "batches" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE INDEX "folders_ownerId_idx" ON "folders"("ownerId");

-- CreateIndex
CREATE INDEX "folder_permissions_userId_idx" ON "folder_permissions"("userId");

-- CreateIndex
CREATE INDEX "records_folderId_idx" ON "records"("folderId");

-- CreateIndex
CREATE UNIQUE INDEX "batches_idempotencyKey_key" ON "batches"("idempotencyKey");

-- CreateIndex
CREATE INDEX "batches_folderId_status_idx" ON "batches"("folderId", "status");

-- CreateIndex
CREATE INDEX "batch_items_recordId_idx" ON "batch_items"("recordId");

-- CreateIndex
CREATE UNIQUE INDEX "batch_items_batchId_recordId_key" ON "batch_items"("batchId", "recordId");

-- CreateIndex
CREATE INDEX "audit_log_batchId_idx" ON "audit_log"("batchId");

-- CreateIndex
CREATE INDEX "audit_log_userId_at_idx" ON "audit_log"("userId", "at");
