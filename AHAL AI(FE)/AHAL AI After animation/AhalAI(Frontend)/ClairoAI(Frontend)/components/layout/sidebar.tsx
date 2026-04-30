"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronLeft,
  Code2,
  FolderGit2,
  FolderUp,
  History,
  Home,
} from "lucide-react";

import { AihalLogo } from "@/components/branding/ahalAI-logo";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Home", icon: Home },
  { href: "/dashboard/code", label: "Code Analysis", icon: Code2 },
  { href: "/dashboard/folder", label: "Folder Upload", icon: FolderUp },
  { href: "/dashboard/api", label: "Analyze Repo", icon: FolderGit2 },
  { href: "/dashboard/history", label: "History", icon: History },
];

const SIDEBAR_TRANSITION = { duration: 0.3, ease: [0.22, 1, 0.36, 1] as const };

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 260 }}
      transition={SIDEBAR_TRANSITION}
      className="fixed left-0 top-0 bottom-0 z-40 flex flex-col overflow-hidden glass-card border-r border-white/5"
    >
      <div className="flex h-16 items-center gap-3 border-b border-white/5 px-5">
        <AnimatePresence>
          {!collapsed && (
            <motion.span
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: "auto" }}
              exit={{ opacity: 0, width: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <Link
                href="/"
                className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
              >
                <AihalLogo compact className="gap-2.5" iconClassName="p-1" />
              </Link>
            </motion.span>
          )}
        </AnimatePresence>
        {collapsed ? (
          <Link
            href="/"
            className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
          >
            <AihalLogo compact iconClassName="p-1" textClassName="hidden" />
          </Link>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-4 pr-2 [scrollbar-gutter:stable]">
        <nav className="space-y-1 rounded-xl">
          {navItems.map((item) => {
            const isActive =
              item.href === "/dashboard"
                ? pathname === "/dashboard"
                : pathname.startsWith(item.href);

            return (
              <Link key={item.href} href={item.href}>
                <div
                  className={cn(
                    "group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 transition-all duration-200",
                    isActive
                      ? "bg-violet-500/10 text-violet-400"
                      : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                  )}
                >
                  {isActive && (
                    <motion.div
                      layoutId="sidebar-active"
                      className="absolute left-0 top-1 bottom-1 w-[3px] rounded-r-full bg-violet-500"
                      transition={{ type: "spring", stiffness: 300, damping: 30 }}
                    />
                  )}
                  <item.icon
                    className={cn("h-5 w-5 flex-shrink-0", isActive && "text-violet-400")}
                  />
                  <AnimatePresence>
                    {!collapsed && (
                      <motion.span
                        initial={{ opacity: 0, width: 0 }}
                        animate={{ opacity: 1, width: "auto" }}
                        exit={{ opacity: 0, width: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden whitespace-nowrap text-sm font-medium"
                      >
                        {item.label}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </div>
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="border-t border-white/5 px-3 py-4">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center rounded-lg py-2 text-slate-400 transition-colors hover:bg-white/5 hover:text-slate-200"
        >
          <motion.div
            animate={{ rotate: collapsed ? 180 : 0 }}
            transition={{ duration: 0.3 }}
          >
            <ChevronLeft className="h-5 w-5" />
          </motion.div>
        </button>
      </div>
    </motion.aside>
  );
}
