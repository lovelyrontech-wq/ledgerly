# Ledgerly web

The Next.js UI. It only talks to the FastAPI backend in `backend/` (login, folders, records, agent).

Stack: Next.js 16 (App Router, Cache Components), TypeScript, Tailwind CSS 4, shadcn/ui (Base UI),
TanStack Query, react-hook-form + zod, openapi-fetch with types generated from the API, Vitest, Playwright.

## Run

```bash
cd apps/web
npm install
cp .env.example .env.local     # NEXT_PUBLIC_API_URL, default http://localhost:8000
npm run dev                    # http://localhost:3000
```

The backend must be running (`uv run uvicorn ledgerly.api.app:create_app --factory --reload` in `backend/`),
plus the MCP server and Ollama for the assistant. Sign in with a demo user, e.g. `alice@ledgerly.test`
and your `SEED_DEMO_PASSWORD`.

## Commands

| Command | What it does |
|---------|--------------|
| `npm run dev` | Dev server on port 3000 |
| `npm run build` | Production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | Route types + `tsc --noEmit` |
| `npm test` | Unit tests (Vitest, jsdom) |
| `npm run test:e2e` | Browser tests on desktop and mobile (Playwright). First time: `npx playwright install chromium`. Set `E2E_PASSWORD` |
| `npm run gen:api` | Regenerate `src/lib/api/schema.d.ts` from the running API's OpenAPI schema. Run after backend API changes |

## Layout

```
src/
├── app/
│   ├── layout.tsx, providers.tsx      # Fonts, TanStack Query, toasts
│   ├── login/                         # Sign-in page
│   └── (dashboard)/                   # Signed-in area: header + folder sidebar
│       └── folders/[folderId]/        # One folder: records + assistant
├── components/
│   ├── auth/                          # Login form, sign-in guard
│   ├── layout/                        # App shell, user menu
│   ├── records/                       # Folder list, folder workspace, records table
│   ├── agent/                         # Assistant chat, preview/approve, metrics
│   └── ui/                            # shadcn/ui components (generated; edit freely)
└── lib/
    ├── api/                           # Typed API client, generated schema, agent SSE stream
    ├── auth/                          # Session (token) store
    └── env.ts                         # Validated public settings
tests/
├── unit/                              # Vitest
└── e2e/                               # Playwright (desktop + mobile)
```

## Responsive design

- **Phones (< 768px):** folders open from the menu button in a slide-in sheet; the assistant opens in a bottom sheet.
- **Tablets (768–1023px):** folder sidebar always visible; the assistant is still a sheet.
- **Desktops (≥ 1024px):** sidebar, records and assistant side by side.

## Notes

- Cache Components is on. Anything that reads the URL (`params`, `useParams`, `usePathname`) must sit inside
  `<Suspense>`, or the build fails. See `node_modules/next/dist/docs/` for this Next.js version.
- The login token is kept in `localStorage` (simple for a local demo). Production would use an httpOnly cookie.
