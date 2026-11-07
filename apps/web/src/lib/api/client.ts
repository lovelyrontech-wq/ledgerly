import createClient, { type Middleware } from "openapi-fetch";

import { tokenStore } from "@/lib/auth/token-store";
import { env } from "@/lib/env";

import type { paths } from "./schema";

/** Adds the signed-in user's token, and signs out when the API says the token is no longer valid. */
const auth: Middleware = {
  onRequest({ request }) {
    const session = tokenStore.get();
    if (session) request.headers.set("Authorization", `Bearer ${session.accessToken}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401 && tokenStore.get()) tokenStore.clear();
    return response;
  },
};

/** Typed client for the FastAPI backend. Paths and bodies come from its OpenAPI schema (npm run gen:api). */
export const api = createClient<paths>({ baseUrl: env.apiUrl });
api.use(auth);

export type { components, paths } from "./schema";
