"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertCircle,
  FolderGit2,
  Github,
  Link2,
  Play,
  RotateCcw,
  Sparkles,
} from "lucide-react";

import { ResultPanel } from "@/components/cards/result-panel";
import { ResultSkeleton } from "@/components/ui/skeleton";
import { useRepoAnalyze } from "@/hooks/useRepoAnalyze";

const repoExamples = [
  "https://github.com/vercel/next.js",
  "https://github.com/facebook/react",
  "https://github.com/openai/openai-node",
];

export default function RepoAnalysisPage() {
  const [repoUrl, setRepoUrl] = useState("");
  const { result, loading, error, sessionId, progress, stage, status, analyze, reset } =
    useRepoAnalyze();
  const stageLabel = stage || "uploading";

  const isValidRepoUrl = useMemo(() => {
    try {
      const url = new URL(repoUrl.trim());
      return ["github.com", "www.github.com"].includes(url.hostname);
    } catch {
      return false;
    }
  }, [repoUrl]);

  const handleAnalyze = () => {
    if (!isValidRepoUrl) return;
    analyze(repoUrl.trim());
  };

  const handleReset = () => {
    setRepoUrl("");
    reset();
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div className="mb-1 flex items-center gap-3">
          <FolderGit2 className="h-6 w-6 text-sky-300" />
          <h1 className="text-2xl font-bold text-white">Analyze Repo</h1>
        </div>
        <p className="text-sm text-slate-400">
          Paste a GitHub repository link to inspect structure, architecture, and
          implementation patterns.
        </p>
        {sessionId ? (
          <p className="mt-2 text-xs uppercase tracking-[0.18em] text-sky-300/80">
            Active session {sessionId.slice(0, 8)}
          </p>
        ) : null}
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="glass-card overflow-hidden rounded-xl"
      >
        <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex gap-1.5">
              <span className="h-3 w-3 rounded-full bg-red-500/60" />
              <span className="h-3 w-3 rounded-full bg-yellow-500/60" />
              <span className="h-3 w-3 rounded-full bg-green-500/60" />
            </div>
            <span className="ml-2 text-xs font-mono text-slate-500">
              repo-link-input
            </span>
          </div>
          <span className="text-xs text-slate-600">
            GitHub repository URL
          </span>
        </div>

        <div className="space-y-5 p-5">
          <div className="rounded-2xl border border-sky-400/10 bg-[linear-gradient(135deg,rgba(8,47,73,0.45),rgba(15,23,42,0.78))] p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-sky-400/15 bg-sky-400/10">
                  <Github className="h-6 w-6 text-sky-300" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-white">
                    Repository Source
                  </p>
                  <p className="text-xs text-slate-400">
                    Public GitHub links work best
                  </p>
                </div>
              </div>
              <div className="hidden rounded-full border border-amber-400/15 bg-amber-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-amber-300 sm:block">
                Repo Analysis
              </div>
            </div>

            <div className="relative">
              <Link2 className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/owner/repository"
                className="w-full rounded-xl border border-white/8 bg-slate-950/70 py-3 pl-11 pr-4 text-sm text-slate-200 placeholder:text-slate-500 focus:border-sky-400/40 focus:outline-none focus:ring-2 focus:ring-sky-400/20"
              />
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {repoExamples.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setRepoUrl(example)}
                  className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-xs text-slate-400 transition-all hover:border-sky-400/20 hover:bg-sky-400/5 hover:text-slate-200"
                >
                  {example.replace("https://github.com/", "")}
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {[
              {
                title: "Architecture",
                description: "Detect how the repo is structured and organized.",
              },
              {
                title: "Core Modules",
                description: "Surface the most important files and subsystems.",
              },
              {
                title: "Risks & Gaps",
                description: "Highlight implementation risks and missing pieces.",
              },
            ].map((item) => (
              <div
                key={item.title}
                className="rounded-xl border border-white/5 bg-white/[0.02] p-4"
              >
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-violet-300" />
                  <p className="text-sm font-semibold text-slate-100">
                    {item.title}
                  </p>
                </div>
                <p className="text-sm leading-6 text-slate-400">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-white/5 px-4 py-3">
          <div>
            {result ? (
              <button
                onClick={handleReset}
                className="flex items-center gap-1.5 rounded-lg bg-white/5 px-3 py-1.5 text-xs text-slate-400 transition-all hover:bg-white/10 hover:text-slate-200"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset
              </button>
            ) : null}
          </div>

          <button
            onClick={handleAnalyze}
            disabled={loading || !isValidRepoUrl}
            className={`btn-glow flex items-center gap-2 rounded-lg px-6 py-2.5 text-sm font-medium transition-all ${
              loading || !isValidRepoUrl
                ? "cursor-not-allowed bg-violet-600/30 text-violet-300/50"
                : "bg-gradient-to-r from-violet-600 to-purple-600 text-white shadow-lg shadow-violet-500/20"
            }`}
          >
            {loading ? (
              <>
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-sky-200/20 border-t-sky-200" />
                {stageLabel}
              </>
            ) : (
              <>
                <Play className="h-4 w-4" />
                Analyze Repo
              </>
            )}
          </button>
        </div>
      </motion.div>

      {error ? (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4"
        >
          <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-400" />
          <div>
            <p className="text-sm font-medium text-amber-200">Analysis failed</p>
            <p className="mt-0.5 text-xs text-amber-200/70">{error}</p>
          </div>
        </motion.div>
      ) : null}

      {loading || status === "processing" ? (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-sky-400/15 bg-sky-400/10 p-4"
        >
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-sky-100">
                {stageLabel}
              </p>
              <p className="mt-1 text-xs text-sky-200/75">
                Polling progress every second
              </p>
            </div>
            <p className="text-sm font-semibold text-sky-200">{progress}%</p>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-950/50">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-400 via-cyan-300 to-emerald-300 transition-all duration-500"
              style={{ width: `${Math.max(progress, 6)}%` }}
            />
          </div>
        </motion.div>
      ) : null}

      {!result && loading ? <ResultSkeleton /> : null}

      {result ? <ResultPanel result={result} /> : null}
    </div>
  );
}
