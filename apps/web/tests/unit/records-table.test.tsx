import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordsTable } from "@/components/records/records-table";
import { formatMoney } from "@/components/records/use-records";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ api: { GET: get } }));
vi.mock("@/lib/auth/token-store", () => ({ useSession: () => ({ user: { id: "usr_1" } }) }));

const record = (name: string, valueCents: number, status: string) => ({
  id: `rec_${name}`,
  folderId: "fld_1",
  name,
  valueCents,
  currency: "USD",
  status,
  fields: {},
  version: 1,
  updatedAt: "2026-11-01T10:00:00Z",
});

function renderTable() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecordsTable folderId="fld_1" folderType="invoice" />
    </QueryClientProvider>,
  );
}

const names = () =>
  screen
    .getAllByRole("row")
    .map((row) => within(row).queryAllByRole("cell")[0]?.textContent)
    .filter(Boolean);

describe("RecordsTable", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockImplementation(async (_path: string, { params }: { params: { query: { status?: string } } }) => {
      const all = [record("Acme", 5000, "paid"), record("Beta", 100, "draft"), record("Cobalt", 9000, "draft")];
      const items = params.query.status ? all.filter((r) => r.status === params.query.status) : all;
      return { data: { items, total: items.length, limit: 25, offset: 0 }, response: { status: 200 } };
    });
  });

  it("lists records with money and status", async () => {
    renderTable();
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText(formatMoney(5000, "USD"))).toBeInTheDocument();
    expect(screen.getByText("1–3 of 3")).toBeInTheDocument();
  });

  it("filters by status on the server and sorts by value on screen", async () => {
    const user = userEvent.setup();
    renderTable();
    await screen.findByText("Acme");

    await user.click(screen.getByRole("button", { name: /^Value/ }));
    expect(names()).toEqual(["Beta", "Acme", "Cobalt"]);
    await user.click(screen.getByRole("button", { name: /^Value/ }));
    expect(names()).toEqual(["Cobalt", "Acme", "Beta"]);

    await user.click(screen.getByRole("button", { name: "draft" }));
    await screen.findByText("1–2 of 2");
    expect(get).toHaveBeenLastCalledWith("/api/folders/{folder_id}/records", {
      params: { path: { folder_id: "fld_1" }, query: { status: "draft", limit: 25, offset: 0 } },
    });
  });

  it("shows the API error", async () => {
    get.mockResolvedValue({ data: undefined, error: { detail: "Folder not found" }, response: { status: 404 } });
    renderTable();
    expect(await screen.findByText("Folder not found")).toBeInTheDocument();
  });
});
