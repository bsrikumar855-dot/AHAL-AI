"use client";

import { useStore, Mode } from "@/lib/store";
import { motion } from "framer-motion";
import { Zap, Globe, BrainCircuit } from "lucide-react";
import clsx from "clsx";

const MODES: { id: Mode; label: string; icon: any }[] = [
  { id: "offline", label: "Offline", icon: Zap },
  { id: "online", label: "Online", icon: Globe },
  { id: "smart", label: "Smart", icon: BrainCircuit },
];

export function ModeSwitch() {
  const { mode, setMode } = useStore();

  return (
    <div className="relative flex items-center rounded-full bg-slate-900/50 p-1 border border-slate-800/50 backdrop-blur-md">
      {MODES.map((m) => {
        const Icon = m.icon;
        const isActive = mode === m.id;

        return (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className={clsx(
              "relative flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors z-10",
              isActive ? "text-white" : "text-slate-400 hover:text-slate-200"
            )}
          >
            {isActive && (
              <motion.div
                layoutId="mode-switch-active"
                className="absolute inset-0 rounded-full bg-slate-800 border border-slate-700 shadow-sm"
                transition={{ type: "spring", stiffness: 300, damping: 25 }}
                style={{ zIndex: -1 }}
              />
            )}
            <Icon
              className={clsx(
                "h-4 w-4",
                isActive && m.id === "offline" && "text-amber-400",
                isActive && m.id === "online" && "text-blue-400",
                isActive && m.id === "smart" && "text-purple-400"
              )}
            />
            <span className="hidden sm:inline">{m.label}</span>
          </button>
        );
      })}
    </div>
  );
}
