"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Code2, Play, RotateCcw, AlertCircle } from "lucide-react";
import { useAnalyze } from "@/hooks/useAnalyze";
import { ResultPanel } from "@/components/cards/result-panel";
import { ResultSkeleton } from "@/components/ui/skeleton";

export default function CodeAnalysisPage() {
  const [code, setCode] = useState("");
  const { result, loading, error, sessionId, analyze, reset } = useAnalyze();

  const handleAnalyze = () => {
    if (code.trim().length < 10) return;
    analyze(code);
  };

  const handleReset = () => {
    setCode("");
    reset();
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
          <Code2 className="w-6 h-6 text-violet-400" />
          <h1 className="text-2xl font-bold text-white">Code Analysis</h1>
        </div>
        <p className="text-sm text-slate-400">
          Paste your code below and let AI extract structured intelligence.
        </p>
        {sessionId ? (
          <p className="mt-2 text-xs uppercase tracking-[0.18em] text-violet-300/80">
            Active session {sessionId.slice(0, 8)}
          </p>
        ) : null}
      </motion.div>

      {/* Code Editor */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="glass-card rounded-xl overflow-hidden"
      >
        {/* Editor Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <div className="flex items-center gap-2">
            <div className="flex gap-1.5">
              <span className="w-3 h-3 rounded-full bg-red-500/60" />
              <span className="w-3 h-3 rounded-full bg-yellow-500/60" />
              <span className="w-3 h-3 rounded-full bg-green-500/60" />
            </div>
            <span className="text-xs text-slate-500 ml-2 font-mono">
              code-input
            </span>
          </div>
          <span className="text-xs text-slate-600">
            {code.length.toLocaleString()} characters
          </span>
        </div>

        {/* Editor Body */}
        <div className="relative">
          {/* Line Numbers */}
          <div className="absolute left-0 top-0 bottom-0 w-12 bg-white/[0.02] border-r border-white/5 flex flex-col pt-4 text-right pr-3">
            {Array.from({ length: Math.max(code.split("\n").length, 15) })
              .slice(0, 30)
              .map((_, i) => (
                <span
                  key={i}
                  className="text-xs text-slate-600 leading-6 font-mono select-none"
                >
                  {i + 1}
                </span>
              ))}
          </div>

          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={`// Paste your code here...\n// Example:\n\nfunction analyzeData(items) {\n  const sorted = items.sort((a, b) => b.score - a.score);\n  return sorted.filter(item => item.score > 0.5);\n}`}
            className="code-editor w-full min-h-[320px] p-4 pl-14 bg-transparent border-none focus:ring-0"
            spellCheck={false}
          />
        </div>

        {/* Editor Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-white/5">
          <div className="flex items-center gap-2">
            {result && (
              <button
                onClick={handleReset}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-xs text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-all"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Reset
              </button>
            )}
          </div>

          <button
            onClick={handleAnalyze}
            disabled={loading || code.trim().length < 10}
            className={`btn-glow flex items-center gap-2 px-6 py-2.5 rounded-lg font-medium text-sm transition-all ${
              loading || code.trim().length < 10
                ? "bg-violet-600/30 text-violet-300/50 cursor-not-allowed"
                : "bg-gradient-to-r from-violet-600 to-purple-600 text-white shadow-lg shadow-violet-500/20"
            }`}
          >
            {loading ? (
              <>
                <div className="w-4 h-4 border-2 border-violet-300/30 border-t-violet-300 rounded-full animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Analyze
              </>
            )}
          </button>
        </div>
      </motion.div>

      {/* Error */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-start gap-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/20"
        >
          <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-200">Partial analysis completed</p>
            <p className="text-xs text-amber-200/70 mt-0.5">{error}</p>
          </div>
        </motion.div>
      )}

      {/* Loading Skeleton */}
      {!result && loading && <ResultSkeleton />}

      {/* Results */}
      {result && <ResultPanel result={result} />}
    </div>
  );
}
