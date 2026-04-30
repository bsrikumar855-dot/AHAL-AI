"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { analyzeCode, createAnalysisSessionId, getJobResult, getJobStatus, isBackgroundProcessingMessage } from "@/lib/api";
import type { AnalysisResult, SessionStatusResponse } from "@/types";

const POLL_INTERVAL_MS = 1000;
const MIN_STARTED_PROGRESS = 5;

function displayStage(stage?: string | null, progress = 0) {
  const normalized = String(stage || "").toLowerCase();
  if (normalized.includes("final")) return "finalizing";
  if (normalized.includes("insight")) return "generating insights";
  if (normalized.includes("analy")) return "analyzing";
  if (normalized.includes("upload")) return "uploading";
  if (progress >= 95) return "finalizing";
  if (progress >= 70) return "generating insights";
  if (progress >= 25) return "analyzing";
  return "uploading";
}

function visibleProgress(value?: number | null, status?: string | null) {
  const progress = Math.max(0, Math.min(100, Number(value || 0)));
  return status === "processing" ? Math.max(progress, MIN_STARTED_PROGRESS) : progress;
}

interface UseAnalyzeReturn {
  result: AnalysisResult | null;
  loading: boolean;
  error: string | null;
  sessionId: string | null;
  progress: number;
  stage: string | null;
  status: "processing" | "completed" | "failed" | null;
  analyze: (code: string) => Promise<void>;
  reset: () => void;
}

function toAnalysisResult(
  payload: { type: AnalysisResult["type"]; session_id: string; result: object | null }
): AnalysisResult | null {
  if (!payload.result) {
    return null;
  }

  return {
    ...(payload.result as Omit<AnalysisResult, "type" | "session_id">),
    type: payload.type,
    session_id: payload.session_id,
  };
}

export function useAnalyze(): UseAnalyzeReturn {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<string | null>(null);
  const [status, setStatus] = useState<"processing" | "completed" | "failed" | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  const schedulePoll = useCallback((jobId: string, run: () => Promise<void>) => {
    pollTimeoutRef.current = setTimeout(() => {
      void run();
    }, POLL_INTERVAL_MS);
  }, []);

  const pollUntilComplete = useCallback(async (jobId: string) => {
    try {
      const payload: SessionStatusResponse = await getJobStatus(jobId);
      setSessionId(payload.session_id);
      const nextProgress = visibleProgress(payload.progress, payload.status);
      setProgress(nextProgress);
      setStage(displayStage(payload.stage, nextProgress));
      setStatus(payload.status);

      if (payload.status === "failed") {
        setLoading(false);
        setResult(null);
        setError(payload.error || "Analysis failed.");
        stopPolling();
        return;
      }

      if (payload.status === "completed") {
        const finalPayload = payload.result ? payload : await getJobResult(jobId);
        const next = toAnalysisResult(finalPayload);
        if (!next && finalPayload.status !== "failed") {
          setLoading(true);
          setStatus("processing");
          setStage("finalizing");
          schedulePoll(jobId, () => pollUntilComplete(jobId));
          return;
        }
        setResult(next);
        setLoading(false);
        setError(finalPayload.error || null);
        setProgress(100);
        setStage("finalizing");
        setStatus("completed");
        stopPolling();
        return;
      }

      setLoading(true);
      setError(null);
      schedulePoll(jobId, () => pollUntilComplete(jobId));
    } catch (err) {
      console.error("API ERROR:", err);
      const message = err instanceof Error ? err.message : "Unable to fetch analysis status.";
      if (isBackgroundProcessingMessage(message)) {
        setLoading(true);
        setStatus("processing");
        setError(null);
        setProgress((current) => Math.max(current, MIN_STARTED_PROGRESS));
        setStage("generating insights");
        schedulePoll(jobId, () => pollUntilComplete(jobId));
        return;
      }
      setLoading(false);
      setError(message);
      setStatus("failed");
      stopPolling();
    }
  }, [schedulePoll, stopPolling]);

  const analyze = useCallback(async (code: string) => {
    stopPolling();
    setLoading(true);
    setError(null);
    setResult(null);
    setProgress(MIN_STARTED_PROGRESS);
    setStage("uploading");
    setStatus("processing");
    const currentSessionId = createAnalysisSessionId("code");

    try {
      setSessionId(currentSessionId);
      const initialStatus = await analyzeCode(code, currentSessionId);
      const jobId = initialStatus.task_id || initialStatus.job_id || initialStatus.session_id || currentSessionId;

      setSessionId(initialStatus.session_id);
      const nextProgress = visibleProgress(initialStatus.progress, initialStatus.status);
      setProgress(nextProgress);
      setStage(displayStage(initialStatus.stage, nextProgress));
      setStatus(initialStatus.status);

      if (jobId) {
        void pollUntilComplete(jobId);
      } else {
        throw new Error("Analysis job id was not returned by the backend.");
      }
    } catch (err) {
      console.error("API ERROR:", err);
      const message = err instanceof Error ? err.message : "Unable to start code analysis.";
      if (isBackgroundProcessingMessage(message) && currentSessionId) {
        setLoading(true);
        setStatus("processing");
        setError(null);
        setProgress((current) => Math.max(current, MIN_STARTED_PROGRESS));
        setStage("analyzing");
        void pollUntilComplete(currentSessionId);
        return;
      }
      setLoading(false);
      setStatus("failed");
      setError(message);
    }
  }, [pollUntilComplete, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setResult(null);
    setError(null);
    setLoading(false);
    setSessionId(null);
    setProgress(0);
    setStage(null);
    setStatus(null);
  }, [stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  return { result, loading, error, sessionId, progress, stage, status, analyze, reset };
}
