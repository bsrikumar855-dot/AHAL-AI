"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Clock,
  Code2,
  FolderGit2,
  FolderUp,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { ActionCard } from "@/components/cards/action-card";
import { getSessionHistory } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { SessionHistoryItem } from "@/types";

type QuickAction = {
  title: string;
  description: string;
  icon: LucideIcon;
  onClick: () => void;
};

export default function DashboardHomePage() {
  const router = useRouter();
  const [recentSessions, setRecentSessions] = useState<SessionHistoryItem[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);

  useEffect(() => {
    getSessionHistory(undefined, 0, 5)
      .then((data) => setRecentSessions(data.sessions))
      .catch(() => setRecentSessions([]))
      .finally(() => setLoadingSessions(false));
  }, []);

  const quickActions: QuickAction[] = [
    {
      title: "Analyze Code",
      description: "Paste a code snippet and get structured AI insights.",
      icon: Code2,
      onClick: () => router.push("/dashboard/code"),
    },
    {
      title: "Upload Folder",
      description: "Upload a .zip project archive for full analysis.",
      icon: FolderUp,
      onClick: () => router.push("/dashboard/folder"),
    },
    {
      title: "Analyze Repo",
      description:
        "Analyze GitHub repositories for architecture, patterns, and actionable AI insights.",
      icon: FolderGit2,
      onClick: () => router.push("/dashboard/api"),
    },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="glass-card relative overflow-hidden rounded-2xl p-8"
      >
        <div className="absolute inset-0 bg-gradient-to-br from-violet-500/5 to-cyan-500/5" />
        <div className="relative">
          <div className="mb-3 flex items-center gap-3">
            <Sparkles className="h-6 w-6 text-violet-400" />
            <span className="text-xs font-medium uppercase tracking-wider text-violet-400">
              Welcome back
            </span>
          </div>
          <h1 className="mb-2 text-3xl font-bold text-white">
            What would you like to analyze?
          </h1>
          <p className="max-w-lg text-slate-400">
            Paste code snippets for instant analysis or upload entire project
            archives for deep structural intelligence.
          </p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {quickActions.map((action, index) => (
          <motion.div
            key={action.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 + index * 0.08 }}
          >
            <ActionCard {...action} />
          </motion.div>
        ))}
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.3 }}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-200">
            <Clock className="h-5 w-5 text-slate-500" />
            Recent Analyses
          </h2>
          <Link
            href="/dashboard/history"
            className="text-xs text-violet-400 transition-colors hover:text-violet-300"
          >
            View all -&gt;
          </Link>
        </div>

        {loadingSessions ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="glass-card shimmer h-16 rounded-xl p-4" />
            ))}
          </div>
        ) : recentSessions.length > 0 ? (
          <div className="space-y-2">
            {recentSessions.map((session, i) => (
              <motion.div
                key={session.session_id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.4 + i * 0.05 }}
                className="glass-card flex items-center justify-between rounded-xl p-4 transition-colors hover:bg-white/[0.04]"
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                      session.type === "code"
                        ? "bg-violet-500/10"
                        : session.type === "folder"
                          ? "bg-cyan-500/10"
                          : "bg-emerald-500/10"
                    }`}
                  >
                    {session.type === "code" ? (
                      <Code2 className="h-4 w-4 text-violet-400" />
                    ) : (
                      <FolderUp className="h-4 w-4 text-cyan-400" />
                    )}
                  </div>
                  <div>
                    <p className="max-w-xs truncate text-sm font-medium text-slate-200">
                      {session.title}
                    </p>
                    <p className="text-xs text-slate-500">
                      {formatDate(session.created_at)}
                    </p>
                  </div>
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    session.status === "completed"
                      ? "bg-emerald-500/10 text-emerald-400"
                      : session.status === "failed"
                        ? "bg-red-500/10 text-red-400"
                        : "bg-amber-500/10 text-amber-400"
                  }`}
                >
                  {session.status}
                </span>
              </motion.div>
            ))}
          </div>
        ) : (
          <div className="glass-card rounded-xl p-8 text-center">
            <p className="text-sm text-slate-500">
              No analyses yet. Start by analyzing some code!
            </p>
          </div>
        )}
      </motion.div>
    </div>
  );
}
