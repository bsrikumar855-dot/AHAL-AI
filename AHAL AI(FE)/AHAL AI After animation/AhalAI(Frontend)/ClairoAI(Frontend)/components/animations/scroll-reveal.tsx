"use client";

import { motion, useInView } from "framer-motion";
import { useEffect, useRef, useState } from "react";

type RevealDirection = "up" | "scale";

interface RevealProps {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  direction?: RevealDirection;
}

const EASE: [number, number, number, number] = [0.4, 0, 0.2, 1];

export function Reveal({
  children,
  className,
  delay = 0,
  direction = "up",
}: RevealProps) {
  const initial =
    direction === "scale"
      ? { opacity: 0, y: 30, scale: 0.96 }
      : { opacity: 0, y: 30 };

  const animate =
    direction === "scale"
      ? { opacity: 1, y: 0, scale: 1 }
      : { opacity: 1, y: 0 };

  return (
    <motion.div
      initial={initial}
      whileInView={animate}
      viewport={{ once: true, margin: "-60px 0px -60px 0px" }}
      transition={{ duration: 0.6, delay, ease: EASE }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function LineDivider({ className }: { className?: string }) {
  return (
    <Reveal className={className}>
      <div className="mx-auto h-px w-full max-w-6xl bg-gradient-to-r from-transparent via-slate-700 to-transparent" />
    </Reveal>
  );
}

interface CountUpProps {
  target: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function CountUp({
  target,
  duration = 1.2,
  prefix = "",
  suffix = "",
  className,
}: CountUpProps) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const isInView = useInView(ref, { once: true, margin: "-60px" });
  const [value, setValue] = useState(0);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted || !isInView) return;

    let frame = 0;
    const start = performance.now();

    const easeOutCubic = (progress: number) => 1 - Math.pow(1 - progress, 3);

    const update = (now: number) => {
      const progress = Math.min(1, (now - start) / (duration * 1000));
      setValue(Math.round(target * easeOutCubic(progress)));

      if (progress < 1) {
        frame = window.requestAnimationFrame(update);
      }
    };

    frame = window.requestAnimationFrame(update);

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [duration, isInView, mounted, target]);

  if (!mounted) {
    return (
      <span ref={ref} className={className}>
        {prefix}
        {target}
        {suffix}
      </span>
    );
  }

  return (
    <span ref={ref} className={className}>
      {prefix}
      {value}
      {suffix}
    </span>
  );
}
