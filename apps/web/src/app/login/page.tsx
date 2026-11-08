import { Bot, ShieldCheck, Undo2 } from "lucide-react";
import type { Metadata } from "next";

import { LoginForm } from "@/components/auth/login-form";
import { Logo } from "@/components/layout/logo";
import { ThemeToggle } from "@/components/layout/theme-toggle";

export const metadata: Metadata = { title: "Sign in" };

const FEATURES = [
  { icon: Bot, title: "Ask in plain words", text: "The assistant reads your folders and answers right away." },
  { icon: ShieldCheck, title: "Preview before you change anything", text: "Bulk edits show up as a diff and wait for your approval." },
  { icon: Undo2, title: "Undo in one click", text: "Every applied change is a batch you can roll back." },
];

export default function LoginPage() {
  return (
    <main className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      {/* Brand panel: large screens only */}
      <section className="brand-gradient relative hidden overflow-hidden p-10 text-white lg:flex lg:flex-col xl:p-14">
        <div className="dot-grid pointer-events-none absolute inset-0 opacity-60 [mask-image:radial-gradient(ellipse_at_top_left,black,transparent_70%)]" />
        <div className="pointer-events-none absolute -right-24 -bottom-24 size-96 rounded-full bg-white/10 blur-3xl" />
        <Logo className="relative [&>span:last-child]:text-white" />
        <div className="relative mt-auto max-w-lg">
          <h1 className="text-4xl leading-[1.1] font-semibold xl:text-5xl">
            Your records, with an assistant that asks first.
          </h1>
          <ul className="mt-10 grid gap-5">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-white/15 ring-1 ring-white/20 backdrop-blur">
                  <Icon className="size-5" />
                </span>
                <span>
                  <span className="block font-medium">{title}</span>
                  <span className="block text-sm text-white/75">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative mt-12 text-xs text-white/60">Ledgerly · demo workspace</p>
      </section>

      {/* Form */}
      <section className="app-backdrop relative flex flex-col px-4 py-6 sm:px-8">
        <div className="flex items-center justify-between">
          <Logo className="lg:invisible" />
          <ThemeToggle />
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">
          <div className="mb-8">
            <h2 className="text-3xl font-semibold">Welcome back</h2>
            <p className="mt-1.5 text-sm text-muted-foreground">Sign in to open your folders.</p>
          </div>
          <LoginForm />
        </div>
      </section>
    </main>
  );
}
