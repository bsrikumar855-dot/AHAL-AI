"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { analyzeFolder, buildSessionStreamUrl, createAnalysisSessionId, getSessionStatus } from "@/lib/api";
import type { AnalysisResult, SessionStatusResponse } from "@/types";

const POLL_INTERVAL_MS = 1800;

interface UseUploadReturn {
  result: AnalysisResult | null;
  loading: boolean;
  error: string | null;
  progress: number;
  selectedFile: File | null;
  sessionId: string | null;
  upload: (file: File) => Promise<void>;
  selectFile: (file: File) => void;
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

export function useUpload(): UseUploadReturn {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
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

  const selectFile = useCallback((file: File) => {
    setSelectedFile(file);
    setError(null);
    setResult(null);
    setProgress(0);
  }, []);

  const syncStatus = useCallback((payload: SessionStatusResponse) => {
    setSessionId(payload.session_id);
    setProgress(payload.progress ?? 0);
    const next = toAnalysisResult(payload);
    if (next) {
      setResult(next);
    }
    if (payload.status === "completed") {
      setLoading(false);
      setError(null);
      stopPolling();
      return;
    }
    if (payload.status === "failed") {
      setLoading(false);
      setError(payload.error || "Partial analysis completed. Full analysis is still processing in background.");
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
      setError(err instanceof Error ? err.message : "Partial analysis completed. Live progress updates are temporarily paused.");
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

  const upload = useCallback(async (file: File) => {
    stopPolling();
    setLoading(true);
    setError(null);
    setResult(null);
    setProgress(0);

    try {
      const currentSessionId = createAnalysisSessionId("folder");
      setSessionId(currentSessionId);
      const initialStatus = await analyzeFolder(file, currentSessionId);
      syncStatus(initialStatus);
      if (initialStatus.status === "processing") {
        startPolling(initialStatus.session_id);
        void pollStatus(initialStatus.session_id);
      }
    } catch (err) {
      console.error("API ERROR:", err);
      setLoading(false);
      setProgress(0);
      const message = err instanceof Error ? err.message : "Folder analysis is still preparing. Please retry in a moment.";
      setError(message);
    }
  }, [pollStatus, startPolling, stopPolling, syncStatus]);

  const reset = useCallback(() => {
    stopPolling();
    setResult(null);
    setError(null);
    setLoading(false);
    setProgress(0);
    setSelectedFile(null);
    setSessionId(null);
  }, [stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  return { result, loading, error, progress, selectedFile, sessionId, upload, selectFile, reset };
}
