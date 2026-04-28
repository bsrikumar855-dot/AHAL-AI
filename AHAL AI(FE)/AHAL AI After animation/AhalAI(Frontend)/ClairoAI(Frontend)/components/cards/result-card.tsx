"use client";

import { motion } from "framer-motion";
import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface ResultCardProps {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
  className?: string;
  delay?: number;
  variant?: "default" | "list" | "warning";
}

export function ResultCard({
  icon: Icon,
  title,
  children,
  className,
  delay = 0,
  variant = "default",
}: ResultCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      transition={{
        duration: 0.5,
        delay,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={cn(
        "glass-card glass-card-hover glow-border p-5 rounded-xl",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-3 mb-3">
        <div
          className={cn(
            "w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0",
            variant === "warning"
              ? "bg-amber-500/10"
              : variant === "list"
              ? "bg-cyan-500/10"
              : "bg-violet-500/10"
          )}
        >
          <Icon
            className={cn(
              "w-4.5 h-4.5",
              variant === "warning"
                ? "text-amber-400"
                : variant === "list"
                ? "text-cyan-400"
                : "text-violet-400"
            )}
          />
        </div>
        <h3 className="text-sm font-semibold text-slate-200 tracking-wide uppercase">
          {title}
        </h3>
      </div>

      {/* Content */}
      <div className="text-sm text-slate-400 leading-relaxed">{children}</div>
    </motion.div>
  );
}
