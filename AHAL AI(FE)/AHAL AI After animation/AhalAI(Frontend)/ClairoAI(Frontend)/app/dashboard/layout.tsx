"use client";

import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { useState } from "react";

import { ChatAssistant } from "@/components/layout/chat-assistant";
import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/topbar";
import { PageTransition } from "@/components/animations/page-transition";

const SIDEBAR_WIDTH_EXPANDED = 260;
const SIDEBAR_WIDTH_COLLAPSED = 72;
const LAYOUT_TRANSITION = { duration: 0.3, ease: [0.22, 1, 0.36, 1] as const };

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chatAssistantOpen, setChatAssistantOpen] = useState(true);
  const showChatAssistant =
    pathname !== "/dashboard" && pathname !== "/dashboard/history";
  const contentLayoutClass = showChatAssistant && chatAssistantOpen
    ? "mx-auto grid max-w-[1600px] items-start gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(320px,24vw)]"
    : "mx-auto max-w-[1600px]";

  return (
    <div className="min-h-screen bg-[hsl(224,71%,4%)]">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((current) => !current)}
      />
      <motion.div
        animate={{ marginLeft: sidebarCollapsed ? SIDEBAR_WIDTH_COLLAPSED : SIDEBAR_WIDTH_EXPANDED }}
        transition={LAYOUT_TRANSITION}
      >
        <TopBar />
        <main className="p-6 lg:p-8">
          <div className={contentLayoutClass}>
            <div className="min-w-0 flex-1">
              <PageTransition>{children}</PageTransition>
            </div>
            {showChatAssistant && chatAssistantOpen ? (
              <ChatAssistant
                isOpen={chatAssistantOpen}
                onOpenChange={setChatAssistantOpen}
              />
            ) : null}
          </div>
          {showChatAssistant && !chatAssistantOpen ? (
            <div className="pointer-events-none fixed right-8 top-24 z-30 hidden xl:block">
              <div className="pointer-events-auto">
                <ChatAssistant
                  isOpen={chatAssistantOpen}
                  onOpenChange={setChatAssistantOpen}
                />
              </div>
            </div>
          ) : null}
        </main>
      </motion.div>
    </div>
  );
}
