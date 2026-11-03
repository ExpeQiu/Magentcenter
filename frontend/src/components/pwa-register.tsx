"use client";

import { useEffect } from "react";

/** 注册 Service Worker（PWA 离线壳）。 */
export function PwaRegister() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
      return;
    }
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("pwa sw register failed", err);
    });
  }, []);
  return null;
}
