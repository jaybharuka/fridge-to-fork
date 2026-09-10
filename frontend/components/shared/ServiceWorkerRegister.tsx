"use client";
import { useEffect } from "react";

// Production-only: registering in dev would cache Fast Refresh's own
// chunks and fight hot-reload. Next.js's own NODE_ENV is "development"
// under `next dev` and "production" under both `next build`+`next start`
// and a real deploy, so this check alone is the right gate — no separate
// env var needed.
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Best-effort — a failed SW registration shouldn't be user-visible,
      // the app works identically without one.
    });
  }, []);

  return null;
}
