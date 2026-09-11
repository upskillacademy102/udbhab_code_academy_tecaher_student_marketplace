import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { App } from "./app/App";

/**
 * Mounts into the #root that templates/web/app_shell.html renders.
 *
 * No stylesheet is imported here: Django's base.html already loads the built
 * static/css/app.css, which is the same design system the public pages use.
 * One stylesheet, one palette, no chance of the SPA drifting from the
 * landing page.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Teacher search is not fast-moving data, and a student flipping
      // between filters shouldn't re-hit the API for something just fetched.
      staleTime: 60_000,
      retry: (count, err) => {
        const status = (err as { status?: number })?.status ?? 0;
        // Never retry auth/permission failures — api.ts has already
        // redirected on a 401 and retrying just delays the redirect.
        if (status === 401 || status === 403 || status === 404) return false;
        return count < 2;
      },
      refetchOnWindowFocus: false,
    },
  },
});

const el = document.getElementById("root");
if (el) {
  createRoot(el).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
