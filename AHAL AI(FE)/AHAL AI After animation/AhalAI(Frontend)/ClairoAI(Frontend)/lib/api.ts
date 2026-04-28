import type {
  AnalysisResult,
  ChatContextSyncResponse,
  ChatHistoryResponse,
  ChatResponse,
  SessionIntelligenceResponse,
  SessionReportResponse,
  SessionHistoryResponse,
  SessionStatusResponse,
} from "@/types";
import { createFreshSessionId, getOrCreateSessionId, setSessionId } from "@/lib/session";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1";
const GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again.";
export type ChatMode = "code" | "folder" | "repo";

export class ApiClientError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

function buildUrl(endpoint: string) {
  return `${API_BASE}${endpoint}`;
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

async function requestJson<T>(endpoint: string, body: Record<string, unknown>): Promise<T> {
  try {
    const res = await fetch(buildUrl(endpoint), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as T;
  } catch (error) {
    console.error("API ERROR:", error);
    if (error instanceof Error) {
      throw error;
    }
    throw new ApiClientError(GENERIC_ERROR_MESSAGE, 500);
  }
}

async function requestForm<T>(endpoint: string, formData: FormData): Promise<T> {
  try {
    const res = await fetch(buildUrl(endpoint), {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as T;
  } catch (error) {
    console.error("API ERROR:", error);
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
  });

  return persistSessionFromResult(result);
}

export async function analyzeFolder(file: File, sessionId = getOrCreateSessionId()) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);
  formData.append("mode", "online");

  const result = await requestForm<SessionStatusResponse>("/folder/analyze", formData);
  return persistSessionFromResult(result);
}

export async function analyzeRepo(repo_url: string, sessionId = getOrCreateSessionId()) {
  const result = await requestJson<SessionStatusResponse>("/repo/analyze", {
    repo_url,
    session_id: sessionId,
    mode: "online",
  });

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
    const res = await fetch(buildUrl(`/session/${sessionId}/status`), {
      method: "GET",
    });

    if (!res.ok) {
      throw await parseError(res);
    }

    return (await res.json()) as SessionStatusResponse;
  } catch (error) {
    console.error("API ERROR:", error);
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
    const res = await fetch(buildUrl(`/session/${sessionId}/intelligence`), {
      method: "GET",
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
