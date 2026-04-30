"use client";

import Image from "next/image";
import Link from "next/link";
import { motion, useScroll, useSpring } from "framer-motion";
import { useRef, useState, useEffect } from "react";
import {
  ArrowRight,
  Code2,
  FolderUp,
  GitBranch,
  Shield,
  Sparkles,
  Zap,
} from "lucide-react";

import { ParticleCanvas } from "@/components/animations/particles";
import {
  LineDivider,
  Reveal,
} from "@/components/animations/scroll-reveal";
import { TiltCard } from "@/components/animations/tilt-card";
import { WordReveal } from "@/components/animations/word-reveal";
import { AihalLogo } from "@/components/branding/ahalAI-logo";

const featureCards = [
  {
    icon: Code2,
    title: "Code Snippets",
    desc: "Paste any code and get instant AI analysis with structured insights",
    details:
      "Use Code Snippets when you want fast clarity on a specific block of code without sharing an entire codebase. It is ideal for debugging functions, understanding unfamiliar syntax, reviewing implementation choices, and getting a clean explanation of what a piece of logic is doing. Instead of manually tracing every line, you get focused insights that help you move from confusion to understanding in seconds.",
  },
  {
    icon: FolderUp,
    title: "Project Folders",
    desc: "Upload .zip project archives for full-stack architecture analysis",
    details:
      "Choose Project Folders when you need a broader view of how a local application is structured. By analyzing the contents of a zipped project, the system can identify architectural patterns, explain how files connect to each other, surface important modules, and help you understand where key responsibilities live. This is especially useful when onboarding to an existing codebase or reviewing a project before making major changes.",
  },
  {
    icon: GitBranch,
    title: "Repositories",
    desc: "Connect GitHub repos for deep multi-file intelligence extraction",
    details:
      "Repositories give you the deepest level of context by working across a connected GitHub project rather than a single file or upload. This makes it easier to reason about cross-file flows, shared dependencies, patterns reused throughout the app, and the overall intent behind the code. It is the best option when you want richer intelligence for large-scale systems, long-lived projects, or collaborative codebases that need more than surface-level analysis.",
  },
];

const heroOrbs = [
  {
    className:
      "left-[8%] top-[18%] h-72 w-72 bg-[radial-gradient(circle,_rgba(124,58,237,0.9)_0%,_rgba(124,58,237,0)_68%)]",
    duration: 7.5,
    delay: 0,
  },
  {
    className:
      "right-[10%] top-[12%] h-80 w-80 bg-[radial-gradient(circle,_rgba(6,182,212,0.85)_0%,_rgba(6,182,212,0)_70%)]",
    duration: 9,
    delay: 0.8,
  },
  {
    className:
      "bottom-[18%] left-[18%] h-64 w-64 bg-[radial-gradient(circle,_rgba(147,51,234,0.85)_0%,_rgba(147,51,234,0)_72%)]",
    duration: 6.8,
    delay: 1.3,
  },
  {
    className:
      "bottom-[12%] right-[16%] h-72 w-72 bg-[radial-gradient(circle,_rgba(124,58,237,0.8)_0%,_rgba(124,58,237,0)_72%)]",
    duration: 8.6,
    delay: 0.4,
  },
];

const tickerItems = [
  "Code Analysis",
  "GitHub Connect",
  "AI Insights",
  "Real-time",
  "Secure Processing",
];

function TickerBar() {
  const items = [...tickerItems, ...tickerItems, ...tickerItems, ...tickerItems];

  return (
    <div className="relative overflow-hidden py-5">
      <motion.div
        animate={{ x: ["0%", "-50%"] }}
        transition={{ duration: 40, ease: "linear", repeat: Infinity }}
        className="flex w-max items-center gap-4 pr-4"
      >
        {items.map((item, index) => (
          <div
            key={`${item}-${index}`}
            className="whitespace-nowrap rounded-full border border-slate-800/70 bg-slate-950/35 px-4 py-2 text-sm text-slate-300"
          >
            {item}
          </div>
        ))}
      </motion.div>
    </div>
  );
}

function FeatureCard({
  card,
  index,
  style,
  contentOpacity,
}: {
  card: (typeof featureCards)[number];
  index: number;
  style?: any;
  contentOpacity?: any;
}) {
  return (
    <Reveal direction="scale" delay={index * 0.1} className="w-full h-full">
      <TiltCard className="w-full h-full">
        <motion.div style={style} className="rounded-xl border p-6 text-left h-full">
          <motion.div style={{ opacity: contentOpacity }}>
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10">
              <card.icon className="h-5 w-5 text-violet-400" />
            </div>
            <h3 className="mb-2 font-semibold text-white">{card.title}</h3>
            <p className="text-sm leading-relaxed text-slate-400">{card.desc}</p>
          </motion.div>
        </motion.div>
      </TiltCard>
    </Reveal>
  );
}

export default function LandingPage() {
  const { scrollYProgress: globalScrollProgress } = useScroll();
  const scaleX = useSpring(globalScrollProgress, {
    stiffness: 100,
    damping: 30,
  });

  // ── A-Shape scroll animation (vanilla JS — no Framer Motion) ──
  const aShapeContainerRef = useRef<HTMLDivElement>(null);
  const [scrollP, setScrollP] = useState(0);

  useEffect(() => {
    function handleScroll() {
      const section = aShapeContainerRef.current;
      if (!section) return;
      const rect = section.getBoundingClientRect();
      const sectionH = section.offsetHeight;
      const viewH = window.innerHeight;

      const stickPoint = viewH * 0.15; // 15vh from top
      const scrolledPastStick = stickPoint - rect.top;
      const totalScroll = sectionH - viewH;

      const p = Math.max(0, Math.min(1, scrolledPastStick / totalScroll));
      setScrollP(p);
    }
    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("resize", handleScroll, { passive: true });
    handleScroll();
    return () => {
      window.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleScroll);
    };
  }, []);

  // Helpers
  function lerp(a: number, b: number, t: number) { return a + (b - a) * t; }
  function clamp(v: number, lo: number, hi: number) { return Math.max(lo, Math.min(hi, v)); }
  function inv(t: number, a: number, b: number) { return clamp((t - a) / (b - a), 0, 1); }
  function easeIO(t: number) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

  // Scroll timeline:
  //   p = 0.00–0.10  → cards are readable and stuck in place (short delay)
  //   p = 0.10–0.60  → cards morph into A shape
  //   p = 0.60–0.75  → arc + brand name fade in
  //   p = 0.75–1.00  → hold, then unstick
  const p = scrollP;
  const te = easeIO(inv(p, 0.10, 0.60));

  // Text fades out at the very start of the morph phase
  const textOp = clamp(1 - inv(p, 0.08, 0.20), 0, 1);

  const lx = lerp(0, 153, te), ly = lerp(0, 240, te);
  const lr = lerp(0, -32, te), lsx = lerp(1, 0.08, te), lsy = lerp(1, 2.0, te);

  const my = lerp(0, 400, te);
  const msx = lerp(1, 0.8, te), msy = lerp(1, 0.04, te);

  const rx = lerp(0, -153, te), ry = lerp(0, 240, te);
  const rr = lerp(0, 32, te), rsx = lerp(1, 0.08, te), rsy = lerp(1, 2.0, te);

  const bgR = Math.round(lerp(15, 245, te));
  const bgG = Math.round(lerp(10, 250, te));
  const bgB = Math.round(lerp(40, 255, te));
  const bgA = lerp(0.75, 1, te).toFixed(2);
  const cardBg = `rgba(${bgR},${bgG},${bgB},${bgA})`;

  const crossbarBg = `rgba(255, 255, 255, ${te})`; // White crossbar

  const bcR = Math.round(lerp(139, 100, te));
  const bcG = Math.round(lerp(92, 230, te));
  const bcB = Math.round(lerp(246, 255, te));
  const bcA = lerp(0.35, 1, te).toFixed(2);
  const cardBorder = `rgba(${bcR},${bcG},${bcB},${bcA})`;

  const arcOp = easeIO(inv(p, 0.58, 0.70));
  const nameOp = easeIO(inv(p, 0.65, 0.75));
  const nameY = lerp(100, 0, easeIO(inv(p, 0.65, 0.75)));
  const logoMerge = easeIO(inv(p, 0.56, 0.7));
  const cardsOpacity = clamp(1 - easeIO(inv(p, 0.54, 0.66)), 0, 1);
  const imageOpacity = logoMerge;
  const imageScale = lerp(0.9, 1.035, logoMerge);
  const imageY = lerp(26, 0, logoMerge);

  return (
    <div className="gradient-bg relative min-h-screen overflow-clip">
      <motion.div
        style={{ scaleX, transformOrigin: "left" }}
        className="fixed inset-x-0 top-0 z-50 h-[2px] bg-violet-500"
      />

      <ParticleCanvas />
      <div className="pointer-events-none absolute inset-0 z-0">
        {heroOrbs.map((orb) => (
          <motion.div
            key={orb.className}
            animate={{ y: [-30, 30] }}
            transition={{
              duration: orb.duration,
              delay: orb.delay,
              ease: "easeInOut",
              repeat: Infinity,
              repeatType: "mirror",
            }}
            className={`absolute rounded-full opacity-[0.15] blur-[80px] ${orb.className}`}
          />
        ))}
      </div>

      <header className="absolute inset-x-0 top-0 z-50">
        <Reveal>
          <nav className="flex items-center px-8 py-5">
            <AihalLogo compact />
          </nav>
        </Reveal>
      </header>

      <main className="relative z-10 text-center">
        <section className="flex min-h-[100dvh] flex-col items-center justify-center px-6">
          <Reveal className="mb-8">
            <span className="badge-pulse inline-flex items-center gap-2 rounded-full border border-violet-500/20 bg-violet-500/10 px-4 py-1.5 text-xs font-medium text-violet-300">
              <span className="h-2 w-2 animate-pulse rounded-full bg-violet-400" />
              AI-Powered Code Intelligence
            </span>
          </Reveal>

          <h1 className="max-w-4xl text-5xl font-extrabold leading-[1.1] tracking-tight sm:text-6xl md:text-7xl">
            <span className="text-white">
              <WordReveal text="Turn Code Into" />
            </span>{" "}
            <span className="gradient-text bg-gradient-to-r from-violet-400 via-purple-400 to-cyan-400 bg-clip-text text-transparent">
              <WordReveal text="Context" />
            </span>
          </h1>

          <Reveal>
            <p className="mt-8 max-w-2xl text-lg leading-relaxed text-slate-400 sm:text-xl">
              Intelligence that brings light to any codebase. Paste code, upload
              projects, or connect repositories for structured insights in seconds.
            </p>
          </Reveal>

          <Reveal className="mt-8">
            <Link href="/dashboard">
              <button className="btn-glow group relative inline-flex items-center gap-3 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 px-8 py-4 text-base font-semibold text-white shadow-2xl shadow-violet-500/20 transition-all hover:shadow-violet-500/40">
                Start Analyzing
                <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-0.5" />
              </button>
            </Link>
          </Reveal>
        </section>

        <section className="px-6 pb-32">
          <LineDivider className="w-full px-6" />

          <section className="mt-4 w-full max-w-6xl px-6 mx-auto">
            <Reveal>
              <TickerBar />
            </Reveal>
          </section>

          <LineDivider className="mt-4 w-full px-6" />
        </section>

        {/* A-Shape Scroll Section — desktop only */}
        <div
          ref={aShapeContainerRef}
          className="relative w-full"
          style={{ height: "200vh" }}
        >
          <div
            className="sticky w-full"
            style={{ top: "8vh" }}
          >
            <div className="relative mx-auto w-full max-w-4xl px-6">

              {/* Cards */}
              <div
                className="grid grid-cols-3 gap-5"
                style={{ opacity: cardsOpacity }}
              >

                {/* LEFT */}
                <div
                  className="rounded-xl p-6 border min-h-[148px]"
                  style={{
                    transformOrigin: "top right",
                    transform: `translate(${lx}px,${ly}px) rotate(${lr}deg) scaleX(${lsx}) scaleY(${lsy})`,
                    background: cardBg,
                    borderColor: cardBorder,
                  }}
                >
                  <div style={{ opacity: textOp }}>
                    <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10">
                      <Code2 className="h-5 w-5 text-violet-400" />
                    </div>
                    <h3 className="mb-2 font-semibold text-white text-sm">Code Snippets</h3>
                    <p className="text-xs leading-relaxed text-slate-400">
                      Paste any code and get instant AI analysis with structured insights
                    </p>
                  </div>
                </div>

                {/* CENTER */}
                <div
                  className="rounded-xl p-6 border min-h-[148px]"
                  style={{
                    transformOrigin: "center center",
                    transform: `translateY(${my}px) scaleX(${msx}) scaleY(${msy})`,
                      background: te > 0.8 ? "linear-gradient(to right, transparent, #ffffff, transparent)" : cardBg,
                    borderColor: te > 0.8 ? "transparent" : cardBorder,
                  }}
                >
                  <div style={{ opacity: textOp }}>
                    <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10">
                      <FolderUp className="h-5 w-5 text-violet-400" />
                    </div>
                    <h3 className="mb-2 font-semibold text-white text-sm">Project Folders</h3>
                    <p className="text-xs leading-relaxed text-slate-400">
                      Upload .zip archives for full-stack architecture analysis
                    </p>
                  </div>
                </div>

                {/* RIGHT */}
                <div
                  className="rounded-xl p-6 border min-h-[148px]"
                  style={{
                    transformOrigin: "top left",
                    transform: `translate(${rx}px,${ry}px) rotate(${rr}deg) scaleX(${rsx}) scaleY(${rsy})`,
                    background: cardBg,
                    borderColor: cardBorder,
                  }}
                >
                  <div style={{ opacity: textOp }}>
                    <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10">
                      <GitBranch className="h-5 w-5 text-violet-400" />
                    </div>
                    <h3 className="mb-2 font-semibold text-white text-sm">Repositories</h3>
                    <p className="text-xs leading-relaxed text-slate-400">
                      Connect GitHub repos for deep multi-file intelligence extraction
                    </p>
                  </div>
                </div>

              </div>

              <div
                className="pointer-events-none absolute inset-x-0 top-[1.5rem] flex justify-center"
                style={{
                  opacity: imageOpacity,
                  transform: `translateY(${imageY}px) scale(${imageScale})`,
                }}
              >
                <div className="w-full max-w-[48rem] px-6">
                  <Image
                    src="/branding/ahal-logo-chatgpt-transparent.png"
                    alt="Ahal AI logo"
                    width={1280}
                    height={1280}
                    priority
                    className="h-auto w-full object-contain"
                  />
                </div>
              </div>

            </div>
          </div>
        </div>

        <section className="px-6 pb-32 pt-[24rem] md:pt-[28rem] lg:pt-[32rem]">
          {/* Mobile Fallback Grid has been removed so only the animated cards show */}

          <LineDivider className="mt-12 w-full px-6" />

          <div className="mx-auto mt-10 flex w-full max-w-4xl flex-col gap-4 text-left">
            {featureCards.map((card) => (
              <Reveal key={`${card.title}-details`}>
                <div className="rounded-xl border border-slate-800/70 bg-slate-950/30 p-6">
                  <h4 className="text-base font-semibold tracking-wide text-violet-300">
                    <WordReveal text={card.title} />
                  </h4>
                  <Reveal>
                    <p className="mt-3 text-sm leading-7 text-slate-400 sm:text-base">
                      {card.details}
                    </p>
                  </Reveal>
                </div>
              </Reveal>
            ))}
          </div>

          <LineDivider className="mt-12 w-full px-6" />

          <Reveal className="mt-20">
            <div className="mx-auto flex max-w-4xl items-center gap-8 text-sm text-slate-500">
              <Reveal>
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-violet-500" />
                  <span>Real-time Analysis</span>
                </div>
              </Reveal>
              <div className="h-4 w-px bg-slate-700" />
              <Reveal delay={0.1}>
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4 text-cyan-500" />
                  <span>Secure Processing</span>
                </div>
              </Reveal>
              <div className="h-4 w-px bg-slate-700" />
              <Reveal delay={0.2}>
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-purple-500" />
                  <span>AI-Powered</span>
                </div>
              </Reveal>
            </div>
          </Reveal>
        </section>
      </main>
    </div>
  );
}
