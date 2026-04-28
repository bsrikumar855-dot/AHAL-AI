"use client";

import { motion } from "framer-motion";
import { ArrowRight, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type ActionCardProps = {
  title: string;
  description: string;
  icon: LucideIcon;
  onClick: () => void;
  className?: string;
};

export function ActionCard({
  title,
  description,
  icon: Icon,
  onClick,
  className,
}: ActionCardProps) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ y: -6, scale: 1.02 }}
      whileTap={{ scale: 0.985 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className={cn(
        "group relative flex h-full w-full flex-col overflow-hidden rounded-2xl border border-sky-400/12",
        "bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-6 text-left shadow-[0_20px_60px_rgba(2,6,23,0.55)]",
        "transition-all duration-300 hover:border-sky-300/30 hover:shadow-[0_24px_80px_rgba(14,165,233,0.18)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950",
        className
      )}
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.16),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(59,130,246,0.12),transparent_32%)] opacity-90 transition-opacity duration-300 group-hover:opacity-100" />
      <div className="pointer-events-none absolute inset-[1px] rounded-[15px] bg-gradient-to-b from-white/[0.06] via-transparent to-transparent" />

      <div className="relative flex h-full flex-col">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-sky-300/15 bg-sky-400/10 shadow-[0_0_30px_rgba(56,189,248,0.16)] transition-all duration-300 group-hover:border-sky-300/30 group-hover:bg-sky-400/14">
            <Icon className="h-6 w-6 text-sky-300" />
          </div>
          <ArrowRight className="mt-1 h-5 w-5 shrink-0 text-slate-500 transition-all duration-300 group-hover:translate-x-1.5 group-hover:text-sky-300" />
        </div>

        <div className="space-y-2">
          <h3 className="text-lg font-semibold tracking-tight text-white">
            {title}
          </h3>
          <p className="max-w-sm text-sm leading-6 text-slate-400">
            {description}
          </p>
        </div>
      </div>
    </motion.button>
  );
}
