"use client";

import { Toaster as SonnerToaster } from "sonner";

export function Toaster() {
  return (
    <SonnerToaster
      position="bottom-right"
      toastOptions={{
        style: {
          background: "rgba(15, 23, 42, 0.9)",
          border: "1px solid rgba(148, 163, 184, 0.1)",
          backdropFilter: "blur(16px)",
          color: "#e2e8f0",
          fontSize: "13px",
        },
      }}
    />
  );
}
