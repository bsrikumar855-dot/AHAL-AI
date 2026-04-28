"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { analyzeRepo, buildSessionStreamUrl, createAnalysisSessionId, getSessionStatus } from "@/lib/api";
import type { AnalysisResult, SessionStatusResponse } from "@/types";

const POLL_INTERVAL_MS = 1800;

interface UseRepoAnalyzeReturn {
  result: AnalysisResult | null;
  loading: boolean;
  error: string | null;
  sessionId: string | null;
  progress: number;
  stage: string | null;
  status: "processing" | "completed" | "failed" | null;
  analyze: (repoUrl: string) => Promise<void>;
  reset: () => void;
}

function toAnalysisResult(status: SessionStatusResponse): AnalysisResult | null {
  if (!status.result) {
    return null;
  }

  return {
    type: status.type,
    session_id: status.session_id,
    ...status.result,
  };
}

export function useRepoAnalyze(): UseRepoAnalyzeReturn {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<string | null>(null);
  const [status, setStatus] = useState<"processing" | "completed" | "failed" | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<EventSource | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
  }, []);

  const syncStatus = useCallback((payload: SessionStatusResponse) => {
    setSessionId(payload.session_id);
    setStatus(payload.status);
    setProgress(payload.progress ?? 0);
    setStage(payload.stage || null);

    const nextResult = toAnalysisResult(payload);
    if (nextResult) {
      setResult(nextResult);
    }

    if (payload.status === "failed") {
      setLoading(false);
      setError(
        payload.error ||
          "Partial analysis completed. Full analysis is still processing in background."
      );
      stopPolling();
      return;
    }

    if (payload.status === "completed") {
      setLoading(false);
      setError(null);
      stopPolling();
      return;
    }

    setLoading(true);
  }, [stopPolling]);

  const pollStatus = useCallback(async (activeSessionId: string) => {
    try {
      const payload = await getSessionStatus(activeSessionId);
      syncStatus(payload);
    } catch (err) {
      console.error("API ERROR:", err);
      setLoading(false);
      setStatus("failed");
      setError(
        err instanceof Error
          ? err.message
          : "Partial analysis completed. Live progress updates are temporarily paused."
      );
      stopPolling();
    }
  }, [stopPolling, syncStatus]);

  const startPolling = useCallback((activeSessionId: string) => {
    stopPolling();
    if (typeof window !== "undefined" && "EventSource" in window) {
      const stream = new EventSource(buildSessionStreamUrl(activeSessionId));
      stream.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as SessionStatusResponse;
          syncStatus(payload);
        } catch (error) {
          console.error("SSE PARSE ERROR:", error);
        }
      };
      stream.onerror = () => {
        stream.close();
        streamRef.current = null;
        pollRef.current = setInterval(() => {
          void pollStatus(activeSessionId);
        }, POLL_INTERVAL_MS);
      };
      streamRef.current = stream;
      return;
    }
    pollRef.current = setInterval(() => {
      void pollStatus(activeSessionId);
    }, POLL_INTERVAL_MS);
  }, [pollStatus, stopPolling]);

  const analyze = useCallback(async (repoUrl: string) => {
    stopPolling();
    setResult(null);
    setLoading(true);
    setError(null);
    setProgress(0);
    setStage("Submitting repository");
    setStatus("processing");

    try {
      const currentSessionId = createAnalysisSessionId("repo");
      setSessionId(currentSessionId);

      const initialStatus = await analyzeRepo(repoUrl, currentSessionId);
      syncStatus(initialStatus);

      if (initialStatus.status === "processing") {
        startPolling(initialStatus.session_id);
        void pollStatus(initialStatus.session_id);
      }
    } catch (err) {
      console.error("API ERROR:", err);
      setLoading(false);
      setStatus("failed");
      setError(
        err instanceof Error
          ? err.message
          : "Repository analysis is still preparing. Please retry in a moment."
      );
    }
  }, [pollStatus, startPolling, stopPolling, syncStatus]);

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

  return {
    result,
    loading,
    error,
    sessionId,
    progress,
    stage,
    status,
    analyze,
    reset,
  };
}
