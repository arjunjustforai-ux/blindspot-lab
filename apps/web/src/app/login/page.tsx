"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Logo } from "@/components/shell/logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const loginSchema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Enter your password") });
const registerSchema = z.object({
  display_name: z.string().min(1, "Enter your name").max(120),
  email: z.string().email("Enter a valid email"),
  password: z.string().min(8, "Use at least 8 characters").max(128),
});

function LoginInner() {
  const auth = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = React.useState(params.get("mode") === "register" ? "register" : "login");

  React.useEffect(() => {
    if (auth.ready && auth.user) router.replace("/app");
  }, [auth.ready, auth.user, router]);

  const login = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });
  const reg = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema) });

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4">
      <div className="glow-indigo pointer-events-none absolute inset-0" />
      <div className="relative w-full max-w-md space-y-6">
        <Link href="/" className="flex justify-center">
          <Logo />
        </Link>
        <Card>
          <CardContent className="p-6">
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="login">Sign in</TabsTrigger>
                <TabsTrigger value="register">Create account</TabsTrigger>
              </TabsList>
              <TabsContent value="login">
                <form
                  className="space-y-4"
                  onSubmit={login.handleSubmit(async (v) => {
                    try {
                      await auth.login(v.email, v.password);
                      router.push("/app");
                    } catch (e) {
                      toast.error(errorMessage(e));
                    }
                  })}
                >
                  <Field label="Email" error={login.formState.errors.email?.message}>
                    <Input type="email" autoComplete="email" {...login.register("email")} />
                  </Field>
                  <Field label="Password" error={login.formState.errors.password?.message}>
                    <Input type="password" autoComplete="current-password" {...login.register("password")} />
                  </Field>
                  <Button type="submit" className="w-full" disabled={login.formState.isSubmitting}>
                    Sign in
                  </Button>
                </form>
              </TabsContent>
              <TabsContent value="register">
                <form
                  className="space-y-4"
                  onSubmit={reg.handleSubmit(async (v) => {
                    try {
                      await auth.register(v.email, v.password, v.display_name);
                      router.push("/app");
                    } catch (e) {
                      toast.error(errorMessage(e));
                    }
                  })}
                >
                  <Field label="Name" error={reg.formState.errors.display_name?.message}>
                    <Input autoComplete="name" {...reg.register("display_name")} />
                  </Field>
                  <Field label="Email" error={reg.formState.errors.email?.message}>
                    <Input type="email" autoComplete="email" {...reg.register("email")} />
                  </Field>
                  <Field label="Password" error={reg.formState.errors.password?.message}>
                    <Input type="password" autoComplete="new-password" {...reg.register("password")} />
                  </Field>
                  <Button type="submit" className="w-full" disabled={reg.formState.isSubmitting}>
                    Create account
                  </Button>
                  <p className="text-xs text-subtle">New accounts are enrolled in the demonstration course and can create their own courses.</p>
                </form>
              </TabsContent>
            </Tabs>
            <div className="my-5 flex items-center gap-3 text-xs text-subtle">
              <div className="h-px flex-1 bg-line" /> or <div className="h-px flex-1 bg-line" />
            </div>
            <Button
              variant="outline"
              className="w-full"
              data-testid="demo-login"
              onClick={async () => {
                try {
                  await auth.demo();
                  router.push("/app");
                } catch (e) {
                  toast.error(errorMessage(e));
                }
              }}
            >
              <Sparkles className="text-warn" /> Continue as a demo learner
            </Button>
            <p className="mt-2 text-center text-[11px] text-subtle">Creates a fresh synthetic learner with no history.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
      {error && <p className="text-xs text-bad">{error}</p>}
    </label>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense>
      <LoginInner />
    </React.Suspense>
  );
}
