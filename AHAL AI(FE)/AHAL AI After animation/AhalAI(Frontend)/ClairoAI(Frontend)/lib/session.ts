"use client";

const SESSION_STORAGE_KEY = "session_id";
const CHAT_MODE_STORAGE_KEY = "chat_mode";
export const SESSION_EVENT_NAME = "ahal-session-change";
export const SESSION_FOCUS_EVENT_NAME = "ahal-session-focus-change";

export type SessionChatMode = "code" | "folder" | "repo";

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function getSessionId(): string | null {
  if (!canUseStorage()) {
    return null;
  }

  return window.localStorage.getItem(SESSION_STORAGE_KEY);
}

export function getChatMode(): SessionChatMode {
  if (!canUseStorage()) {
    return "code";
  }

  const value = window.localStorage.getItem(CHAT_MODE_STORAGE_KEY);
  if (value === "folder" || value === "repo") {
    return value;
  }
  return "code";
}

export function getOrCreateSessionId(): string {
  const existing = getSessionId();
  if (existing) {
    return existing;
  }

  return createFreshSessionId();
}

export function setChatMode(mode: SessionChatMode) {
  if (!canUseStorage()) {
    return;
  }

  window.localStorage.setItem(CHAT_MODE_STORAGE_KEY, mode);
}

export function setSessionId(sessionId: string, mode?: SessionChatMode) {
  if (!canUseStorage()) {
    return;
  }

  window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  if (mode) {
    window.localStorage.setItem(CHAT_MODE_STORAGE_KEY, mode);
  }
  window.dispatchEvent(
    new CustomEvent(SESSION_EVENT_NAME, {
      detail: { sessionId, mode: mode || getChatMode() },
    })
  );
}

export function createFreshSessionId(mode?: SessionChatMode): string {
  if (!canUseStorage()) {
    return crypto.randomUUID();
  }

  const nextSessionId = crypto.randomUUID();
  setSessionId(nextSessionId, mode);
  return nextSessionId;
}

export function dispatchSessionFocus(detail: {
  sessionId: string;
  mode?: SessionChatMode;
  focus?: string;
  module?: string;
  workflow?: string;
  filePath?: string;
}) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(SESSION_FOCUS_EVENT_NAME, { detail }));
}
