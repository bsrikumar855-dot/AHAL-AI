"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, ChevronLeft, SendHorizonal, User2 } from "lucide-react";

import { askAI, getChatHistory, getSessionIntelligence, type ChatMode } from "@/lib/api";
import { getChatMode, getSessionId, SESSION_EVENT_NAME, SESSION_FOCUS_EVENT_NAME, setChatMode } from "@/lib/session";
import type { SessionIntelligenceResponse } from "@/types";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  source?: string;
  relatedFiles?: string[];
  modulesInvolved?: string[];
  suggestedQuestions?: string[];
  isLoading?: boolean;
};

const CHAT_MODES: Array<{
  id: ChatMode;
  label: string;
  intro: string;
  empty: string;
}> = [
  {
    id: "code",
    label: "Code Chat",
    intro: "Ask about functions, logic, and runtime behavior.",
    empty: "Ask things like “What does this function do?” or “Explain this logic flow.”",
  },
  {
    id: "folder",
    label: "Folder Chat",
    intro: "Ask about structure, modules, and system design.",
    empty: "Ask things like “Explain this folder structure” or “What are the main modules?”",
  },
  {
    id: "repo",
    label: "Repo Chat",
    intro: "Ask about project purpose, architecture, risks, and improvements.",
    empty: "Ask things like “What does this repo do?” or “What are the biggest risks?”",
  },
];

const AI_ERROR_MESSAGE = "I have the project context loaded, and I am refining the next answer now. Please try again in a moment.";

function createMessageId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeAssistantCopy(answer: string) {
  return answer || AI_ERROR_MESSAGE;
}

function buildInstantAssistantReply(
  mode: ChatMode,
  focusHint: string,
  intelligence: SessionIntelligenceResponse | null
) {
  const topWorkflow = intelligence?.workflows?.[0];
  const topModules = intelligence?.graph?.central_nodes?.slice(0, 3) || [];
  const graphSummary = intelligence?.graph?.summary || "";
  const memoryFocus = intelligence?.memory_profile?.focus || "";
  const workflowLine =
    topWorkflow?.steps?.length
      ? `${topWorkflow.name}: ${topWorkflow.steps.slice(0, 4).join(" -> ")}`
      : "";

  const modeLabel =
    mode === "repo"
      ? "repository architecture"
      : mode === "folder"
        ? "project structure"
        : "code behavior";

  const parts = [
    `I am grounding this answer in the current ${modeLabel}.`,
    focusHint || memoryFocus || graphSummary || "The latest stored analysis is already available.",
  ];

  if (topModules.length) {
    parts.push(`Current core modules: ${topModules.join(", ")}.`);
  }
  if (workflowLine) {
    parts.push(`System workflow: ${workflowLine}.`);
  }

  parts.push("Refining the deeper explanation now...");
  return parts.join(" ");
}

export function ChatAssistant() {
  const [isOpen, setIsOpen] = useState(true);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [chatMode, setChatModeState] = useState<ChatMode>("code");
  const [focusHint, setFocusHint] = useState("");
  const [intelligence, setIntelligence] = useState<SessionIntelligenceResponse | null>(null);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([
    "Explain system workflow",
    "What are the main risks?",
    "How can this be improved?",
  ]);
  const scrollerRef = useRef<HTMLDivElement>(null);

  const handleModeChange = (mode: ChatMode) => {
    setChatMode(mode);
    setChatModeState(mode);
  };

  useEffect(() => {
    const currentSessionId = getSessionId();
    const currentChatMode = getChatMode();
    setSessionId(currentSessionId);
    setChatModeState(currentChatMode);
    setHistoryLoaded(false);

    const handleSessionChange = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId?: string; mode?: ChatMode }>).detail;
      const nextSessionId = detail?.sessionId || getSessionId();
      const nextMode = detail?.mode || getChatMode();
      setSessionId(nextSessionId);
      setChatModeState(nextMode);
      setHistoryLoaded(false);
    };

    const handleFocusChange = (event: Event) => {
      const detail = (event as CustomEvent<{ focus?: string; module?: string; workflow?: string }>).detail;
      const nextHint = detail?.focus || detail?.workflow || detail?.module || "";
      if (!nextHint) {
        return;
      }
      setFocusHint(nextHint);
      setMessages((current) => [
        ...current,
        {
          id: createMessageId(),
          role: "assistant",
          content: nextHint,
          source: getChatMode(),
        },
      ]);
    };

    window.addEventListener(SESSION_EVENT_NAME, handleSessionChange);
    window.addEventListener(SESSION_FOCUS_EVENT_NAME, handleFocusChange);
    return () => {
      window.removeEventListener(SESSION_EVENT_NAME, handleSessionChange);
      window.removeEventListener(SESSION_FOCUS_EVENT_NAME, handleFocusChange);
    };
  }, []);

  useEffect(() => {
    setHistoryLoaded(false);
  }, [chatMode]);

  useEffect(() => {
    if (!sessionId || historyLoaded) {
      return;
    }

    let active = true;
    setMessages([]);

    getChatHistory(sessionId, chatMode)
      .then((history) => {
        if (!active) {
          return;
        }

        if (history.count === 0) {
          setMessages([]);
          return;
        }

        setMessages(
          history.history.flatMap((entry) => [
            {
              id: createMessageId(),
              role: "user",
              content: entry.question,
            },
            {
              id: createMessageId(),
              role: "assistant",
              content: entry.answer,
              source: chatMode,
              relatedFiles: [],
              modulesInvolved: [],
              suggestedQuestions: [],
            },
          ])
        );
      })
      .catch((error) => {
        console.error("API ERROR:", error);
        if (active) {
          setMessages([]);
        }
      })
      .finally(() => {
        if (active) {
          setHistoryLoaded(true);
        }
      });

    return () => {
      active = false;
    };
  }, [chatMode, historyLoaded, sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setIntelligence(null);
      return;
    }

    let active = true;
    getSessionIntelligence(sessionId)
      .then((payload) => {
        if (active) {
          setIntelligence(payload);
        }
      })
      .catch((error) => {
        console.error("API ERROR:", error);
        if (active) {
          setIntelligence(null);
        }
      });

    return () => {
      active = false;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!scrollerRef.current) {
      return;
    }

    scrollerRef.current.scrollTo({
      top: scrollerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const activeMode = CHAT_MODES.find((item) => item.id === chatMode) || CHAT_MODES[0];

  const canSend = useMemo(
    () => input.trim().length > 0 && !isSending,
    [input, isSending]
  );

  const handleSend = async () => {
    const question = input.trim();
    if (!question || isSending) {
      return;
    }

    const currentSessionId = getSessionId();
    if (!currentSessionId) {
      setMessages((current) => [
        ...current,
        {
          id: createMessageId(),
          role: "assistant",
          content: `No ${chatMode} analysis found. Run ${chatMode} analysis first.`,
          source: chatMode,
        },
      ]);
      setInput("");
      return;
    }

    const userMessage: ChatMessage = {
      id: createMessageId(),
      role: "user",
      content: question,
    };
    const instantId = createMessageId();
    const thinkingId = createMessageId();
    const instantReply = buildInstantAssistantReply(chatMode, focusHint, intelligence);

    setSessionId(currentSessionId);
    setMessages((current) => [
      ...current,
      userMessage,
      {
        id: instantId,
        role: "assistant",
        content: instantReply,
        source: chatMode,
      },
      {
        id: thinkingId,
        role: "assistant",
        content: "Refining the deeper answer...",
        source: chatMode,
        isLoading: true,
      },
    ]);
    setInput("");
    setIsSending(true);

    try {
      const response = await askAI(question, currentSessionId, chatMode);
      setSuggestedQuestions(response.suggested_questions || suggestedQuestions);
      setSessionId(response.session_id || currentSessionId);
      setMessages((current) =>
        current.map((message) =>
          message.id === thinkingId
            ? {
                id: thinkingId,
                role: "assistant",
                content: normalizeAssistantCopy(response.answer),
                source: response.source || chatMode,
                relatedFiles: response.related_files || [],
                modulesInvolved: response.modules_involved || [],
                suggestedQuestions: response.suggested_questions || [],
              }
            : message
        )
      );
    } catch (error) {
      console.error("API ERROR:", error);
      setMessages((current) =>
        current.map((message) =>
          message.id === thinkingId
            ? {
                id: thinkingId,
                role: "assistant",
                content: error instanceof Error ? error.message : AI_ERROR_MESSAGE,
                source: chatMode,
                relatedFiles: [],
                modulesInvolved: [],
                suggestedQuestions,
              }
            : message
        )
      );
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = async (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await handleSend();
    }
  };

  const sessionText = sessionId ? `Session ${sessionId.slice(0, 8)}` : "No active session";

  return (
    <div className="relative hidden w-full xl:block">
      <AnimatePresence mode="wait" initial={false}>
        {isOpen ? (
          <motion.aside
            key="open-panel"
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 24 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="sticky top-6 w-full lg:top-8"
          >
            <div className="glass-card relative flex h-[calc(100vh-7rem)] flex-col overflow-hidden rounded-2xl border border-sky-400/10 bg-gradient-to-b from-slate-950/90 via-slate-900/90 to-slate-950/90 shadow-[0_24px_80px_rgba(2,6,23,0.5)] lg:h-[calc(100vh-8rem)]">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(56,189,248,0.14),transparent_35%)]" />

              <div className="relative shrink-0 flex items-center justify-between border-b border-white/5 px-4 py-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-sky-400/20 bg-sky-400/10">
                    <Bot className="h-5 w-5 text-sky-300" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white">Workspace Assistant</p>
                    <p className="text-xs text-slate-400">{sessionText}</p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="rounded-lg border border-white/5 bg-white/5 p-2 text-slate-400 transition-colors hover:border-sky-400/20 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                  aria-label="Close chat assistant"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
              </div>

              <div className="relative flex min-h-0 flex-1 flex-col px-4 py-4">
                <div className="grid grid-cols-3 gap-2">
                  {CHAT_MODES.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() => handleModeChange(mode.id)}
                      className={`rounded-xl border px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] transition-all ${
                        chatMode === mode.id
                          ? "border-sky-300/40 bg-sky-400/15 text-sky-100"
                          : "border-white/8 bg-white/[0.03] text-slate-400 hover:border-sky-400/20 hover:text-slate-200"
                      }`}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>

                <div className="mt-4 rounded-2xl border border-sky-400/10 bg-slate-900/70 px-4 py-3">
                  <p className="text-sm leading-6 text-slate-300">{activeMode.intro}</p>
                  {focusHint ? (
                    <p className="mt-2 text-xs uppercase tracking-[0.16em] text-sky-300/80">
                      {focusHint}
                    </p>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {suggestedQuestions.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        onClick={() => setInput(suggestion)}
                        className="rounded-full border border-sky-400/15 bg-sky-400/5 px-2.5 py-1 text-[11px] text-sky-100 transition-all hover:border-sky-300/30 hover:bg-sky-400/10"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>

                <div
                  ref={scrollerRef}
                  className="mt-4 flex-1 space-y-4 overflow-y-auto pr-1"
                >
                  {messages.length === 0 ? (
                    <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-6 text-center">
                      <p className="text-sm leading-6 text-slate-400">{activeMode.empty}</p>
                    </div>
                  ) : null}

                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[88%] rounded-2xl px-4 py-3 ${
                          message.role === "user"
                            ? "border border-sky-400/20 bg-sky-500/15 text-sky-50"
                            : "border border-white/8 bg-slate-900/80 text-slate-100"
                        }`}
                      >
                        <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                          {message.role === "user" ? (
                            <>
                              <User2 className="h-3.5 w-3.5" />
                              You
                            </>
                          ) : (
                            <>
                              <Bot className="h-3.5 w-3.5" />
                              {activeMode.label}
                            </>
                          )}
                        </div>
                        <p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>
                        {message.role === "assistant" && !message.isLoading ? (
                          <>
                            <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.16em] text-slate-400">
                              <span className="rounded-full border border-white/8 px-2 py-1">
                                Source {message.source || chatMode}
                              </span>
                            </div>
                            {message.relatedFiles && message.relatedFiles.length > 0 ? (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {message.relatedFiles.map((file) => (
                                  <span
                                    key={`${message.id}-${file}`}
                                    className="rounded-full border border-sky-400/15 bg-sky-400/5 px-2 py-1 text-[11px] text-sky-100"
                                  >
                                    {file}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                            {message.modulesInvolved && message.modulesInvolved.length > 0 ? (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {message.modulesInvolved.map((module) => (
                                  <span
                                    key={`${message.id}-module-${module}`}
                                    className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-slate-200"
                                  >
                                    {module}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="shrink-0 border-t border-white/5 bg-slate-950/70 px-4 py-4 backdrop-blur-sm">
                <label htmlFor="assistant-message" className="sr-only">
                  Message AHAL AI
                </label>
                <div className="flex w-full flex-col rounded-2xl border border-white/8 bg-slate-950/80 p-3 shadow-inner shadow-black/20">
                  <textarea
                    id="assistant-message"
                    rows={4}
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={`Ask ${activeMode.label}...`}
                    className="w-full resize-none bg-transparent text-sm leading-6 text-slate-200 placeholder:text-slate-500 focus:outline-none"
                  />
                  <div className="mt-3 flex justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        void handleSend();
                      }}
                      disabled={!canSend}
                      className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 ${
                        canSend
                          ? "border border-sky-400/20 bg-sky-400/10 text-sky-200 hover:border-sky-300/30 hover:bg-sky-400/15 hover:text-white"
                          : "cursor-not-allowed border border-white/5 bg-white/5 text-slate-500"
                      }`}
                    >
                      {isSending ? "Thinking..." : "Send"}
                      <SendHorizonal className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </motion.aside>
        ) : (
          <motion.div
            key="closed-panel"
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 16 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="sticky top-6 flex w-full justify-end lg:top-8"
          >
            <button
              type="button"
              onClick={() => setIsOpen(true)}
              className="glass-card inline-flex items-center gap-3 rounded-2xl border border-sky-400/10 bg-slate-950/85 px-4 py-3 text-left shadow-[0_20px_60px_rgba(2,6,23,0.4)] transition-all hover:border-sky-400/20 hover:bg-slate-900/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-400/10 text-sky-300">
                <Bot className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">Open Chat</p>
                <p className="text-xs text-slate-400">{activeMode.label}</p>
              </div>
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
