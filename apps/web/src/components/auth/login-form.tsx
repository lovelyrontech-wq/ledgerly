"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { sessionFromLogin, tokenStore } from "@/lib/auth/token-store";

const schema = z.object({
  email: z.email("Enter a valid email address"),
  password: z.string().min(4, "Enter your password"),
});
type LoginValues = z.infer<typeof schema>;

/** Only same-site paths, so a crafted ?next= link cannot send the user to another site after login. */
function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/folders";
}

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<LoginValues>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit(values: LoginValues) {
    setError(null);
    const { data, response } = await api.POST("/api/auth/login", { body: values }).catch(() => ({
      data: undefined,
      response: undefined,
    }));
    if (!data) {
      setError(
        response?.status === 401
          ? "Wrong email or password."
          : "Cannot reach the Ledgerly API. Is the backend running?",
      );
      return;
    }
    tokenStore.set(sessionFromLogin(data));
    router.replace(safeNext(new URLSearchParams(window.location.search).get("next")));
  }

  return (
    <Card>
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <CardContent className="grid gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              placeholder="alice@ledgerly.test"
              aria-invalid={!!errors.email}
              {...form.register("email")}
            />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={!!errors.password}
              {...form.register("password")}
            />
            {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
          </div>
        </CardContent>
        <CardFooter className="mt-4">
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting && <LoaderCircle className="animate-spin" />}
            Sign in
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
