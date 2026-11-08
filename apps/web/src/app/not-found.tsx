import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="app-backdrop flex min-h-dvh flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-gradient font-heading text-7xl font-bold">404</p>
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">The page you are looking for does not exist.</p>
      <Link href="/folders" className={buttonVariants({ className: "rounded-full px-5" })}>
        Back to folders
      </Link>
    </main>
  );
}
