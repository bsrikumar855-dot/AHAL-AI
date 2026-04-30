"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, ChevronLeft, SendHorizonal, User2 } from "lucide-react";

import { askAI, type ChatMode } from "@/lib/api";
import { getChatMode, getSessionId, SESSION_EVENT_NAME, SESSION_FOCUS_EVENT_NAME, setChatMode } from "@/lib/session";

type Message = {
  role: "user" | "assistant";
  content: string;
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
    empty: 'Ask things like "What does this function do?" or "Explain this logic flow."',
  },
  {
    id: "folder",
    label: "Folder Chat",
    intro: "Ask about structure, modules, and system design.",
    empty: 'Ask things like "Explain this folder structure" or "What are the main modules?"',
  },
  {
    id: "repo",
    label: "Repo Chat",
    intro: "Ask about project purpose, architecture, risks, and improvements.",
    empty: 'Ask things like "What does this repo do?" or "What are the biggest risks?"',
  },
];

const AI_ERROR_MESSAGE = "Error. Try again.";

function normalizeAssistantCopy(answer: string) {
  return answer.trim() || AI_ERROR_MESSAGE;
}

const streamResponse = (text: string, onChunk: (value: string) => void) =>
  new Promise<void>((resolve) => {
    let index = 0;
    const interval = window.setInterval(() => {
      onChunk(text.slice(0, index));
      index += 1;
      if (index > text.length) {
        window.clearInterval(interval);
        resolve();
      }
    }, 10);
  });

interface ChatAssistantProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ChatAssistant({ isOpen, onOpenChange }: ChatAssistantProps) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatMode, setChatModeState] = useState<ChatMode>("code");
  const [focusHint, setFocusHint] = useState("");
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([
    "Explain system workflow",
    "What are the main risks?",
    "How can this be improved?",
  ]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const handleModeChange = (mode: ChatMode) => {
    setChatMode(mode);
    setChatModeState(mode);
  };

  useEffect(() => {
    const currentSessionId = getSessionId();
    const currentChatMode = getChatMode();
    setSessionId(currentSessionId);
    setChatModeState(currentChatMode);

    const handleSessionChange = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId?: string; mode?: ChatMode }>).detail;
      const nextSessionId = detail?.sessionId || getSessionId();
      const nextMode = detail?.mode || getChatMode();
      setSessionId(nextSessionId);
      setChatModeState(nextMode);
    };

    const handleFocusChange = (event: Event) => {
      const detail = (event as CustomEvent<{ focus?: string; module?: string; workflow?: string }>).detail;
      const nextHint = detail?.focus || detail?.workflow || detail?.module || "";
      if (!nextHint) {
        return;
      }
      setFocusHint(nextHint);
    };

    window.addEventListener(SESSION_EVENT_NAME, handleSessionChange);
    window.addEventListener(SESSION_FOCUS_EVENT_NAME, handleFocusChange);
    return () => {
      window.removeEventListener(SESSION_EVENT_NAME, handleSessionChange);
      window.removeEventListener(SESSION_FOCUS_EVENT_NAME, handleFocusChange);
    };
  }, []);

  useEffect(() => {
    setMessages([]);
  }, [chatMode]);

  useEffect(() => {
    setMessages([]);
  }, [sessionId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
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
          role: "assistant",
          content: "No active analysis session. Run analysis first.",
        },
      ]);
      setInput("");
      return;
    }

    const userMessage: Message = {
      role: "user",
      content: question,
    };

    setMessages((current) => [
      ...current,
      userMessage,
      {
        role: "assistant",
        content: "",
      },
    ]);
    setInput("");
    setIsSending(true);

    try {
      const response = await askAI(question, currentSessionId, chatMode);
      setSuggestedQuestions(response.suggested_questions || suggestedQuestions);
      setSessionId(response.session_id || currentSessionId);
      await streamResponse(normalizeAssistantCopy(response.answer), (value) => {
        setMessages((current) =>
          current.map((message, index) =>
            index === current.length - 1
              ? {
                  ...message,
                  content: value,
                }
              : message
          )
        );
      });
    } catch (error) {
      console.error("API ERROR:", error);
      setMessages((current) =>
        current.map((message, index) =>
          index === current.length - 1
            ? {
                ...message,
                content: AI_ERROR_MESSAGE,
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
                  onClick={() => onOpenChange(false)}
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

                <div className="mt-4 flex-1 space-y-4 overflow-y-auto pr-1">
                  {messages.length === 0 ? (
                    <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-6 text-center">
                      <p className="text-sm leading-6 text-slate-400">{activeMode.empty}</p>
                    </div>
                  ) : null}

                  {messages.map((message, index) => (
                    <div
                      key={`${message.role}-${index}`}
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
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
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
                      {isSending ? "Sending..." : "Send"}
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
              onClick={() => onOpenChange(true)}
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
