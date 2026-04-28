"use client";

import { usePathname } from "next/navigation";

import { ChatAssistant } from "@/components/layout/chat-assistant";
import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/topbar";
import { PageTransition } from "@/components/animations/page-transition";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const showChatAssistant =
    pathname !== "/dashboard" && pathname !== "/dashboard/history";
  const contentLayoutClass = showChatAssistant
    ? "mx-auto grid max-w-[1600px] items-start gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(320px,24vw)]"
    : "mx-auto max-w-[1600px]";

  return (
    <div className="min-h-screen bg-[hsl(224,71%,4%)]">
      <Sidebar />
      <div className="ml-[260px] transition-all duration-300">
        <TopBar />
        <main className="p-6 lg:p-8">
          <div className={contentLayoutClass}>
            <div className="min-w-0 flex-1">
              <PageTransition>{children}</PageTransition>
            </div>
            {showChatAssistant ? <ChatAssistant /> : null}
          </div>
        </main>
      </div>
    </div>
  );
}
