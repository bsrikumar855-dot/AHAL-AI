import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Mode = "offline" | "online" | "smart";

interface AppState {
  mode: Mode;
  setMode: (mode: Mode) => void;
}

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      mode: "offline",
      setMode: (mode) => set({ mode }),
    }),
    {
      name: "clairo-mode-storage",
    }
  )
);
