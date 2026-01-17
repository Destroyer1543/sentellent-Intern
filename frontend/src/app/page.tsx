// app/page.tsx
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { isLoggedIn } from "@/lib/auth";

export default function Root() {
  const router = useRouter();

  useEffect(() => {
    router.replace(isLoggedIn() ? "/chat" : "/login");
  }, [router]);

  return null;
}
