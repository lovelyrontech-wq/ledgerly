import { cn } from "@/lib/utils";

/** Ledgerly mark: stacked ledger lines in a gradient tile, plus the word mark. */
export function Logo({ className, showText = true }: { className?: string; showText?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className="brand-gradient grid size-8 place-items-center rounded-xl shadow-md shadow-primary/25 ring-1 ring-white/15">
        <svg viewBox="0 0 24 24" className="size-4.5 text-white" fill="none" aria-hidden>
          <path d="M5 7h14M5 12h9M5 17h6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          <circle cx="18" cy="16.5" r="2.5" fill="currentColor" />
        </svg>
      </span>
      {showText && <span className="font-heading text-lg font-semibold tracking-tight">Ledgerly</span>}
    </span>
  );
}
