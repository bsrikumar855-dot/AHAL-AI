"use client";

import { Search, User } from "lucide-react";
import { ModeSwitch } from "@/components/ModeSwitch";

export function TopBar() {
  return (
    <header className="h-16 border-b border-white/5 glass-card flex items-center justify-between px-6">
      {/* Search */}
      <div className="relative max-w-md w-full">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text"
          placeholder="Search analyses..."
          className="w-full pl-10 pr-4 py-2 rounded-lg bg-white/5 border border-white/5 text-sm text-slate-300 placeholder-slate-500 focus:outline-none focus:border-violet-500/50 focus:bg-white/[0.07] transition-all"
        />
      </div>

      {/* Profile & Controls */}
      <div className="flex items-center gap-6">
        <ModeSwitch />
        <div className="h-6 w-px bg-slate-800" />
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-cyan-500 flex items-center justify-center">
          <User className="w-4 h-4 text-white" />
        </div>
      </div>
    </header>
  );
}
