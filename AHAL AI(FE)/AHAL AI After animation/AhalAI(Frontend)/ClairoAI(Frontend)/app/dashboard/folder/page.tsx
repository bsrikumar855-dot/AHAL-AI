"use client";

import { useCallback, useRef } from "react";
import { motion } from "framer-motion";
import {
  FolderUp,
  Upload,
  File,
  X,
  CheckCircle2,
  AlertCircle,
  RotateCcw,
} from "lucide-react";

import { ResultPanel } from "@/components/cards/result-panel";
import { ResultSkeleton } from "@/components/ui/skeleton";
import { useUpload } from "@/hooks/useUpload";

const uploadStages = [
  { label: "uploading", threshold: 15 },
  { label: "analyzing", threshold: 40 },
  { label: "generating insights", threshold: 80 },
  { label: "finalizing", threshold: 100 },
];

export default function FolderUploadPage() {
  const {
    result,
    loading,
    error,
    progress,
    stage,
    selectedFile,
    sessionId,
    upload,
    selectFile,
    reset,
  } = useUpload();
  const stageLabel = stage || "uploading";

  const inputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dropRef.current?.classList.remove("active");

      const file = e.dataTransfer.files?.[0];
      if (file && file.name.endsWith(".zip")) {
        selectFile(file);
      }
    },
    [selectFile]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dropRef.current?.classList.add("active");
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dropRef.current?.classList.remove("active");
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) selectFile(file);
  };

  const handleUpload = () => {
    if (selectedFile) upload(selectedFile);
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div className="mb-1 flex items-center gap-3">
          <FolderUp className="h-6 w-6 text-cyan-400" />
          <h1 className="text-2xl font-bold text-white">Folder Analysis</h1>
        </div>
        <p className="text-sm text-slate-400">
          Upload a .zip project archive for AI-powered structural analysis.
        </p>
        {sessionId ? (
          <p className="mt-2 text-xs uppercase tracking-[0.18em] text-cyan-300/80">
            Active session {sessionId.slice(0, 8)}
          </p>
        ) : null}
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
      >
        {!selectedFile ? (
          <div
            ref={dropRef}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => inputRef.current?.click()}
            className="drop-zone flex min-h-[280px] cursor-pointer flex-col items-center justify-center rounded-xl p-12"
          >
            <motion.div
              animate={{ y: [0, -8, 0] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            >
              <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-cyan-500/10">
                <Upload className="h-8 w-8 text-cyan-400" />
              </div>
            </motion.div>
            <p className="mb-2 text-white font-medium">Drop your .zip file here</p>
            <p className="mb-4 text-sm text-slate-500">or click to browse files</p>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-500">
              Supports .zip files up to 50MB
            </span>
            <input
              ref={inputRef}
              type="file"
              accept=".zip"
              onChange={handleFileSelect}
              className="hidden"
            />
          </div>
        ) : (
          <div className="glass-card space-y-4 rounded-xl p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/10">
                  <File className="h-5 w-5 text-cyan-400" />
                </div>
                <div>
                  <p className="text-sm font-medium text-white">
                    {selectedFile.name}
                  </p>
                  <p className="text-xs text-slate-500">
                    {formatFileSize(selectedFile.size)}
                  </p>
                </div>
              </div>
              {!loading && !result && (
                <button
                  onClick={reset}
                  className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-white/5 hover:text-slate-300"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {loading && (
              <div className="space-y-3">
                <div className="h-2 overflow-hidden rounded-full bg-white/5">
                  <motion.div
                    className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-violet-500"
                    initial={{ width: "0%" }}
                    animate={{ width: `${Math.max(progress, 6)}%` }}
                    transition={{ duration: 0.3 }}
                  />
                </div>
                <p className="text-right text-xs text-slate-500">
                  {Math.round(progress)}% - {stageLabel}
                </p>
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                  <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Analysis Process
                  </p>
                  <div className="space-y-2">
                    {uploadStages.map((stage, index) => {
                      const isComplete = progress >= stage.threshold || (!!result && index === uploadStages.length - 1);
                      const isCurrent =
                        progress < stage.threshold &&
                        (index === 0 ||
                          progress >= uploadStages[index - 1].threshold);

                      return (
                        <div
                          key={stage.label}
                          className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5"
                        >
                          <div className="flex items-center gap-3">
                            <div
                              className={`h-2.5 w-2.5 rounded-full transition-colors ${
                                isComplete
                                  ? "bg-emerald-400 shadow-[0_0_14px_rgba(74,222,128,0.6)]"
                                  : isCurrent
                                    ? "bg-cyan-400 shadow-[0_0_14px_rgba(34,211,238,0.6)]"
                                    : "bg-slate-700"
                              }`}
                            />
                            <span
                              className={`text-sm transition-colors ${
                                isComplete
                                  ? "text-emerald-300"
                                  : isCurrent
                                    ? "text-slate-200"
                                    : "text-slate-500"
                              }`}
                            >
                              {stage.label}
                            </span>
                          </div>
                          <span
                            className={`text-[11px] uppercase tracking-[0.16em] ${
                              isComplete
                                ? "text-emerald-400"
                                : isCurrent
                                  ? "text-cyan-400"
                                  : "text-slate-600"
                            }`}
                          >
                            {isComplete
                              ? "Done"
                              : isCurrent
                                ? "In Progress"
                                : "Pending"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {result && (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex items-center gap-2 text-sm text-emerald-400"
              >
                <CheckCircle2 className="h-4 w-4" />
                Analysis complete
              </motion.div>
            )}

            {!loading && !result && (
              <button
                onClick={handleUpload}
                className="btn-glow flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-cyan-600 to-violet-600 px-6 py-3 text-sm font-medium text-white shadow-lg shadow-cyan-500/20"
              >
                <Upload className="h-4 w-4" />
                Start Analysis
              </button>
            )}

            {result && (
              <button
                onClick={reset}
                className="flex items-center gap-1.5 rounded-lg bg-white/5 px-3 py-1.5 text-xs text-slate-400 transition-all hover:bg-white/10 hover:text-slate-200"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Upload another file
              </button>
            )}
          </div>
        )}
      </motion.div>

      {error && (
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
      )}

      {!result && loading && <ResultSkeleton />}

      {result && <ResultPanel result={result} />}
    </div>
  );
}
