import type {
  AnalysisResult,
  ChatContextSyncResponse,
  ChatHistoryResponse,
  ChatResponse,
  SessionIntelligenceResponse,
  SessionReportResponse,
  SessionResultResponse,
  SessionHistoryResponse,
  SessionStatusResponse,
} from "@/types";
import { createFreshSessionId, getOrCreateSessionId, setSessionId } from "@/lib/session";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1";
const GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again.";
const DEFAULT_REQUEST_TIMEOUT_MS = 90000;
const ANALYZE_REQUEST_TIMEOUT_MS = 5000;
const POLL_REQUEST_TIMEOUT_MS = 30000;
export type ChatMode = "code" | "folder" | "repo";

export class ApiClientError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

export function isBackgroundProcessingMessage(message: string | null | undefined) {
  const normalized = String(message || "").toLowerCase();
  return normalized.includes("timeout")
    || normalized.includes("abort")
    || normalized.includes("aborted")
    || normalized.includes("still running")
    || normalized.includes("background")
    || normalized.includes("llm_timeout_background");
}

function buildUrl(endpoint: string) {
  return `${API_BASE}${endpoint}`;
}

function buildFreshUrl(endpoint: string) {
  const joiner = endpoint.includes("?") ? "&" : "?";
  return buildUrl(`${endpoint}${joiner}no_cache=true`);
}

export function buildSessionStreamUrl(sessionId: string) {
  return buildUrl(`/session/${sessionId}/stream`);
}

function extractErrorMessage(payload: unknown): string | null {
  if (!payload) {
    return null;
  }

  if (typeof payload === "string") {
    return payload;
  }

  if (typeof payload !== "object") {
    return null;
  }

  const candidate = payload as Record<string, unknown>;
  for (const key of ["error", "message", "detail", "details", "suggestion"]) {
    const value = candidate[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (value && typeof value === "object") {
      const nested = extractErrorMessage(value);
      if (nested) {
        return nested;
      }
    }
  }

  return null;
}

async function parseError(res: Response) {
  let message = GENERIC_ERROR_MESSAGE;
  let details: string | undefined;

  try {
    const errorBody = await res.json();
    console.error("API ERROR:", errorBody);
    message = extractErrorMessage(errorBody) || message;
    details =
      typeof errorBody?.details === "string"
        ? errorBody.details
        : typeof errorBody?.detail === "string"
          ? errorBody.detail
          : undefined;
  } catch {
    if (res.statusText) {
      message = res.statusText;
    }
  }

  const finalMessage = details && details !== message ? `${message} ${details}` : message;
  return new ApiClientError(finalMessage, res.status);
}

async function fetchWithTimeout(input: string, init: RequestInit, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

async function requestJson<T>(endpoint: string, body: Record<string, unknown>, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS): Promise<T> {
  try {
    const res = await fetchWithTimeout(buildUrl(endpoint), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    }, timeoutMs);

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as T;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError("Request timed out. Analysis is still running in the background.", 408);
    }
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

async function requestForm<T>(endpoint: string, formData: FormData, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS): Promise<T> {
  try {
    const res = await fetchWithTimeout(buildUrl(endpoint), {
      method: "POST",
      body: formData,
    }, timeoutMs);

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as T;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError("Request timed out. Analysis is still running in the background.", 408);
    }
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

function persistSessionFromResult<T extends { session_id?: string }>(result: T): T {
  if (result.session_id) {
    const analysisType = (result as T & { type?: string }).type;
    const mode =
      analysisType === "folder" || analysisType === "repo" || analysisType === "code"
        ? analysisType
        : undefined;
    setSessionId(result.session_id, mode);
  }

  return result;
}

export function ensureSessionId() {
  return getOrCreateSessionId();
}

export function createAnalysisSessionId(mode?: ChatMode) {
  return createFreshSessionId(mode);
}

export async function analyzeCode(code: string, sessionId = getOrCreateSessionId()) {
  const result = await requestJson<SessionStatusResponse>("/code/analyze", {
    code,
    session_id: sessionId,
    mode: "online",
  }, ANALYZE_REQUEST_TIMEOUT_MS);

  return persistSessionFromResult(result);
}

export async function analyzeFolder(file: File, sessionId = getOrCreateSessionId()) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);
  formData.append("mode", "online");

  const result = await requestForm<SessionStatusResponse>("/folder/analyze", formData, ANALYZE_REQUEST_TIMEOUT_MS);
  return persistSessionFromResult(result);
}

export async function analyzeRepo(repo_url: string, sessionId = getOrCreateSessionId()) {
  const result = await requestJson<SessionStatusResponse>("/repo/analyze", {
    repo_url,
    session_id: sessionId,
    mode: "online",
  }, ANALYZE_REQUEST_TIMEOUT_MS);

  return persistSessionFromResult(result);
}

export async function askAI(
  question: string,
  sessionId = getOrCreateSessionId(),
  mode: ChatMode = "code"
) {
  const result = await requestJson<ChatResponse>("/chat/ask", {
    question,
    session_id: sessionId,
    mode,
  });

  return persistSessionFromResult(result);
}

export async function getChatHistory(
  sessionId: string,
  mode: ChatMode = "code"
) {
  try {
    const params = new URLSearchParams({ mode });
    const res = await fetch(buildUrl(`/chat/history/${sessionId}?${params.toString()}`), {
      method: "GET",
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as ChatHistoryResponse;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function getSessionHistory(
  type?: string,
  skip = 0,
  limit = 20
): Promise<SessionHistoryResponse> {
  try {
    const params = new URLSearchParams();
    if (type) {
      params.set("type", type);
    }
    params.set("skip", String(skip));
    params.set("limit", String(limit));

    const res = await fetch(buildUrl(`/session/history?${params.toString()}`), {
      method: "GET",
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as SessionHistoryResponse;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function getSessionStatus(
  sessionId: string
): Promise<SessionStatusResponse> {
  try {
    const res = await fetchWithTimeout(buildUrl(`/session/${sessionId}/status`), {
      method: "GET",
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache, no-store, max-age=0",
        Pragma: "no-cache",
      },
    }, POLL_REQUEST_TIMEOUT_MS);

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as SessionStatusResponse;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError("Status request timed out. Background analysis may still be running.", 408);
    }
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function getJobStatus(
  jobId: string
): Promise<SessionStatusResponse> {
  try {
    const res = await fetchWithTimeout(buildFreshUrl(`/status/${jobId}`), {
      method: "GET",
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache, no-store, max-age=0",
        Pragma: "no-cache",
      },
    }, POLL_REQUEST_TIMEOUT_MS);

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as SessionStatusResponse;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError("Status request timed out. Analysis is still running in the background.", 408);
    }
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function getJobResult(
  jobId: string
): Promise<SessionResultResponse> {
  try {
    const res = await fetchWithTimeout(buildFreshUrl(`/session/result/${jobId}`), {
      method: "GET",
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache, no-store, max-age=0",
        Pragma: "no-cache",
      },
    }, POLL_REQUEST_TIMEOUT_MS);

    if (!res.ok && res.status !== 202) {
      throw await parseError(res);
    }

    return (await res.json()) as SessionResultResponse;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError("Result request timed out. Analysis is still finalizing.", 408);
    }
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function getSessionReport(
  sessionId: string
): Promise<SessionReportResponse> {
  try {
    const res = await fetch(buildUrl(`/session/${sessionId}/report`), {
      method: "GET",
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache, no-store, max-age=0",
        Pragma: "no-cache",
      },
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as SessionReportResponse;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function getSessionIntelligence(
  sessionId: string
): Promise<SessionIntelligenceResponse> {
  try {
    const res = await fetch(buildFreshUrl(`/session/${sessionId}/intelligence`), {
      method: "GET",
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache, no-store, max-age=0",
        Pragma: "no-cache",
      },
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as SessionIntelligenceResponse;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function deleteSession(sessionId: string): Promise<{ ok: boolean; session_id: string }> {
  try {
    const res = await fetch(buildUrl(`/session/${sessionId}`), {
      method: "DELETE",
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as { ok: boolean; session_id: string };
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

export async function syncChatContext(payload: {
  session_id: string;
  mode: ChatMode;
  focus?: string;
  module?: string;
  workflow?: string;
  file_path?: string;
}): Promise<ChatContextSyncResponse> {
  return await requestJson<ChatContextSyncResponse>("/chat/context", payload);
}
