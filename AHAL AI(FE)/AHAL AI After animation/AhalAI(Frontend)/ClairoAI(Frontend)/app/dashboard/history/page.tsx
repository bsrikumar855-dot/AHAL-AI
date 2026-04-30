"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  History as HistoryIcon,
  Code2,
  FolderUp,
  FolderGit2,
  GitBranch,
  ChevronRight,
  Trash2,
} from "lucide-react";
import { deleteSession, getSessionHistory, getSessionStatus } from "@/lib/api";
import type { SessionHistoryItem, SessionStatusResponse } from "@/types";
import { formatDate } from "@/lib/utils";
import { ResultPanel } from "@/components/cards/result-panel";

type FilterType = "all" | "code" | "folder" | "repo";

export default function HistoryPage() {
  const [sessions, setSessions] = useState<SessionHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedResult, setExpandedResult] =
    useState<SessionStatusResponse | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchSessions = async (type: FilterType) => {
    setLoading(true);
    try {
      const data = await getSessionHistory(
        type === "all" ? undefined : type,
        0,
        50
      );
      setSessions(data.sessions);
      setTotal(data.total);
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions(filter);
  }, [filter]);

  const handleExpand = async (sessionId: string) => {
    if (expandedId === sessionId) {
      setExpandedId(null);
      setExpandedResult(null);
      return;
    }

    setExpandedId(sessionId);
    setLoadingDetail(true);
    try {
      const data = await getSessionStatus(sessionId);
      setExpandedResult(data);
    } catch {
      setExpandedResult(null);
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleDelete = async (sessionId: string) => {
    if (deletingId) {
      return;
    }

    setDeletingId(sessionId);
    try {
      await deleteSession(sessionId);
      setSessions((current) => current.filter((session) => session.session_id !== sessionId));
      setTotal((current) => Math.max(0, current - 1));
      if (expandedId === sessionId) {
        setExpandedId(null);
        setExpandedResult(null);
      }
    } catch (error) {
      console.error("API ERROR:", error);
    } finally {
      setDeletingId(null);
    }
  };

  const filters: { value: FilterType; label: string; icon: typeof Code2 }[] = [
    { value: "all", label: "All", icon: HistoryIcon },
    { value: "code", label: "Code", icon: Code2 },
    { value: "folder", label: "Folder", icon: FolderUp },
    { value: "repo", label: "Repo", icon: FolderGit2 },
  ];

  const getTypeIcon = (type: string) => {
    switch (type) {
      case "code":
        return <Code2 className="w-4 h-4 text-violet-400" />;
      case "folder":
        return <FolderUp className="w-4 h-4 text-cyan-400" />;
      case "repo":
        return <GitBranch className="w-4 h-4 text-emerald-400" />;
      default:
        return <Code2 className="w-4 h-4 text-slate-400" />;
    }
  };

  const getTypeBg = (type: string) => {
    switch (type) {
      case "code":
        return "bg-violet-500/10";
      case "folder":
        return "bg-cyan-500/10";
      case "repo":
        return "bg-emerald-500/10";
      default:
        return "bg-slate-500/10";
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div className="flex items-center gap-3 mb-1">
          <HistoryIcon className="w-6 h-6 text-slate-400" />
          <h1 className="text-2xl font-bold text-white">History</h1>
        </div>
        <p className="text-sm text-slate-400">
          View all past analyses. Click on a session to view full results.
        </p>
      </motion.div>

      {/* Filter Tabs */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/5 w-fit"
      >
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`relative flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              filter === f.value
                ? "text-white"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {filter === f.value && (
              <motion.div
                layoutId="history-tab"
                className="absolute inset-0 bg-white/10 rounded-lg"
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
              />
            )}
            <span className="relative flex items-center gap-2">
              <f.icon className="w-4 h-4" />
              {f.label}
            </span>
          </button>
        ))}
      </motion.div>

      {/* Sessions List */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="glass-card p-4 rounded-xl shimmer h-16" />
          ))}
        </div>
      ) : sessions.length > 0 ? (
        <div className="space-y-2">
          {sessions.map((session, i) => (
            <motion.div
              key={session.session_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
            >
              {/* Session Row */}
              <div className="glass-card rounded-xl p-4 transition-all hover:bg-white/[0.04] group">
                <div className="flex items-center justify-between gap-4">
                  <button
                    onClick={() => handleExpand(session.session_id)}
                    className="flex flex-1 items-center justify-between text-left"
                  >
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div
                    className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${getTypeBg(
                      session.type
                    )}`}
                  >
                    {getTypeIcon(session.type)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-200 truncate">
                      {session.title}
                    </p>
                    <p className="text-xs text-slate-500 truncate">
                      {session.preview}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 ml-4 flex-shrink-0">
                  <span className="text-xs text-slate-600 hidden sm:block">
                    {formatDate(session.created_at)}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      session.status === "completed"
                        ? "bg-emerald-500/10 text-emerald-400"
                        : session.status === "failed"
                        ? "bg-red-500/10 text-red-400"
                        : "bg-amber-500/10 text-amber-400"
                    }`}
                  >
                    {session.status}
                  </span>
                  <motion.div
                    animate={{
                      rotate: expandedId === session.session_id ? 90 : 0,
                    }}
                    transition={{ duration: 0.2 }}
                  >
                    <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400" />
                  </motion.div>
                </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleDelete(session.session_id);
                    }}
                    disabled={deletingId === session.session_id}
                    className="rounded-lg border border-red-500/10 bg-red-500/5 p-2 text-red-300 transition-all hover:border-red-400/30 hover:bg-red-500/10 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label={`Delete ${session.title}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Expanded Result */}
              {expandedId === session.session_id && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.3 }}
                  className="mt-2 pl-4 border-l-2 border-violet-500/20"
                >
                  {loadingDetail ? (
                    <div className="p-6 space-y-3">
                      {Array.from({ length: 3 }).map((_, i) => (
                        <div
                          key={i}
                          className="shimmer h-12 rounded-lg"
                        />
                      ))}
                    </div>
                  ) : expandedResult?.result ? (
                    <div className="py-4">
                      <ResultPanel
                        result={{
                          type: expandedResult.type,
                          session_id: expandedResult.session_id,
                          ...expandedResult.result,
                        }}
                      />
                    </div>
                  ) : (
                    <div className="p-6 text-center text-slate-500 text-sm">
                      {expandedResult?.error
                        ? `Error: ${expandedResult.error}`
                        : "No result data available"}
                    </div>
                  )}
                </motion.div>
              )}
            </motion.div>
          ))}
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="glass-card p-12 rounded-xl text-center"
        >
          <HistoryIcon className="w-10 h-10 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">
            No sessions found{filter !== "all" ? ` for "${filter}"` : ""}.
          </p>
          <p className="text-slate-600 text-xs mt-1">
            Start analyzing code or upload a project to build history.
          </p>
        </motion.div>
      )}

      {/* Total Count */}
      {!loading && sessions.length > 0 && (
        <p className="text-xs text-slate-600 text-center">
          Showing {sessions.length} of {total} sessions
        </p>
      )}
    </div>
  );
}
