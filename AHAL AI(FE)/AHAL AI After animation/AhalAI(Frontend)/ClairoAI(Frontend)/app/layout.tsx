import type { Metadata } from "next";

import { Toaster } from "@/components/ui/toaster";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "AHAL AI - Intelligence That Brings Light",
  description:
    "Understand any codebase instantly with AI. Analyze code snippets, project folders, and GitHub repositories to extract structured intelligence.",
  icons: {
    icon: "/branding/Ahal%20logo.jpeg",
    shortcut: "/branding/Ahal%20logo.jpeg",
    apple: "/branding/Ahal%20logo.jpeg",
  },
  keywords: [
    "AI",
    "code analysis",
    "developer tools",
    "codebase intelligence",
    "repository analysis",
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
      </head>
      <body className="min-h-screen antialiased">
        {children}
        <Toaster />
      </body>
    </html>
  );
}
