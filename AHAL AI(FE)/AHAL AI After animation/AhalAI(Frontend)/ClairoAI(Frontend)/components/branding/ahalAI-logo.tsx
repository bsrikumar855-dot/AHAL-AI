"use client";

import { cn } from "@/lib/utils";

type AihalLogoProps = {
  className?: string;
  iconClassName?: string;
  textClassName?: string;
  compact?: boolean;
};

function AihalGlyph({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 220 220"
      aria-hidden="true"
      className={cn("h-10 w-10", className)}
    >
      <defs>
        <linearGradient id="ahal-compact-ring" x1="42" y1="128" x2="178" y2="128">
          <stop offset="0%" stopColor="#f3be37" />
          <stop offset="48%" stopColor="#fff4c7" />
          <stop offset="100%" stopColor="#36ddff" />
        </linearGradient>
        <linearGradient id="ahal-compact-metal" x1="74" y1="34" x2="150" y2="164">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="24%" stopColor="#f6f8fb" />
          <stop offset="54%" stopColor="#dce6f1" />
          <stop offset="78%" stopColor="#8fd6ff" />
          <stop offset="100%" stopColor="#37d9ff" />
        </linearGradient>
        <linearGradient id="ahal-compact-beam" x1="110" y1="78" x2="110" y2="168">
          <stop offset="0%" stopColor="#16bfff" stopOpacity="0" />
          <stop offset="38%" stopColor="#16cfff" stopOpacity="0.95" />
          <stop offset="52%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#16cfff" stopOpacity="0" />
        </linearGradient>
        <filter
          id="ahal-compact-glow"
          x="-50%"
          y="-50%"
          width="200%"
          height="200%"
          colorInterpolationFilters="sRGB"
        >
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <path
        d="M46 150A66 66 0 1 1 174 150"
        fill="none"
        stroke="url(#ahal-compact-ring)"
        strokeWidth="4"
        strokeLinecap="round"
        filter="url(#ahal-compact-glow)"
      />

      <path
        d="M34 176Q110 154 186 176"
        fill="none"
        stroke="#3fdcff"
        strokeWidth="3.4"
        strokeLinecap="round"
        filter="url(#ahal-compact-glow)"
      />

      <path
        d="M110 42 70 148h12l28-73 28 73h12L110 42Z"
        fill="url(#ahal-compact-metal)"
        filter="url(#ahal-compact-glow)"
      />

      <rect
        x="108"
        y="84"
        width="4"
        height="68"
        rx="2"
        fill="url(#ahal-compact-beam)"
        filter="url(#ahal-compact-glow)"
      />
      <rect x="109.2" y="89" width="1.6" height="54" rx="0.8" fill="#ffffff" />

      {[
        [88, 122, 148],
        [97, 110, 146],
        [104, 102, 144],
        [116, 104, 144],
        [123, 112, 146],
        [132, 124, 148],
      ].map(([x, y1, y2]) => (
        <line
          key={x}
          x1={x}
          y1={y1}
          x2={x}
          y2={y2}
          stroke="#52dcff"
          strokeWidth="1.4"
          opacity="0.82"
        />
      ))}

      <circle cx="110" cy="150" r="6" fill="#7cebff" filter="url(#ahal-compact-glow)" />
      <circle cx="110" cy="150" r="2.6" fill="#ffffff" />
    </svg>
  );
}

function AihalFullLogo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 900 760"
      aria-hidden="true"
      className={cn("h-auto w-full", className)}
    >
      <defs>
        <linearGradient id="ahal-ring" x1="246" y1="220" x2="654" y2="220">
          <stop offset="0%" stopColor="#f3be37" />
          <stop offset="48%" stopColor="#fff5c9" />
          <stop offset="100%" stopColor="#38deff" />
        </linearGradient>
        <linearGradient id="ahal-metal" x1="348" y1="118" x2="548" y2="442">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="22%" stopColor="#f8fafc" />
          <stop offset="50%" stopColor="#dde6f0" />
          <stop offset="76%" stopColor="#95d8ff" />
          <stop offset="100%" stopColor="#34dcff" />
        </linearGradient>
        <linearGradient id="ahal-beam" x1="450" y1="220" x2="450" y2="470">
          <stop offset="0%" stopColor="#10c8ff" stopOpacity="0" />
          <stop offset="34%" stopColor="#1dd6ff" stopOpacity="0.95" />
          <stop offset="50%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#19d1ff" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="ahal-ai" x1="680" y1="570" x2="796" y2="570">
          <stop offset="0%" stopColor="#2fd8ff" />
          <stop offset="100%" stopColor="#5eb6ff" />
        </linearGradient>
        <filter
          id="ahal-glow"
          x="-40%"
          y="-40%"
          width="180%"
          height="180%"
          colorInterpolationFilters="sRGB"
        >
          <feGaussianBlur stdDeviation="6" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter
          id="ahal-soft-glow"
          x="-60%"
          y="-60%"
          width="220%"
          height="220%"
          colorInterpolationFilters="sRGB"
        >
          <feGaussianBlur stdDeviation="12" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <path
        d="M250 386A204 204 0 1 1 650 386"
        fill="none"
        stroke="url(#ahal-ring)"
        strokeWidth="8"
        strokeLinecap="round"
        filter="url(#ahal-glow)"
      />

      <path
        d="M182 512Q450 438 718 512"
        fill="none"
        stroke="#42dcff"
        strokeWidth="6"
        strokeLinecap="round"
        filter="url(#ahal-glow)"
      />

      <path
        d="M450 132 278 458h28l144-270 144 270h28L450 132Z"
        fill="url(#ahal-metal)"
        filter="url(#ahal-glow)"
      />

      <rect
        x="444"
        y="266"
        width="12"
        height="188"
        rx="6"
        fill="url(#ahal-beam)"
        filter="url(#ahal-soft-glow)"
      />
      <rect x="448.2" y="278" width="3.6" height="154" rx="1.8" fill="#ffffff" />

      {[
        [406, 358, 450],
        [422, 320, 446],
        [436, 288, 444],
        [464, 288, 444],
        [478, 318, 446],
        [494, 356, 450],
      ].map(([x, y1, y2]) => (
        <line
          key={x}
          x1={x}
          y1={y1}
          x2={x}
          y2={y2}
          stroke="#55ddff"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.88"
        />
      ))}

      <circle cx="450" cy="456" r="11" fill="#72e7ff" filter="url(#ahal-glow)" />
      <circle cx="450" cy="456" r="5" fill="#ffffff" />

      <g transform="translate(160 544)">
        <path
          d="M0 78 35 0h20l35 78h-16l-10-22H26L16 78Z"
          fill="url(#ahal-metal)"
        />
        <path d="M34 45h23l-5 11H29Z" fill="#ffffff" />

        <path d="M150 0h15v33h52V0h15v78h-15V46h-52v32h-15Z" fill="url(#ahal-metal)" />

        <path
          d="M304 78 339 0h20l35 78h-16l-10-22h-38l-10 22Z"
          fill="url(#ahal-metal)"
        />
        <path d="M338 45h23l-5 11h-23Z" fill="#ffffff" />

        <path d="M454 0h15v64h62v14h-77Z" fill="url(#ahal-metal)" />

        <path
          d="M606 78 638 6h18l32 72h-15l-8-18h-34l-8 18Z"
          fill="url(#ahal-ai)"
        />
        <path d="M636 45h22l-4 10h-22Z" fill="#41ddff" />
        <path d="M716 0h15v78h-15Z" fill="url(#ahal-ai)" />
      </g>

      <text
        x="450"
        y="674"
        textAnchor="middle"
        fill="#ffffff"
        fontSize="31"
        letterSpacing="10"
        style={{ textTransform: "uppercase" }}
      >
        INTELLIGENCE THAT BRINGS
      </text>
      <text
        x="646"
        y="674"
        fill="#f3c23e"
        fontSize="31"
        letterSpacing="10"
        style={{ textTransform: "uppercase" }}
      >
        LIGHT
      </text>

      <path
        d="M270 720H630"
        stroke="#1e5171"
        strokeWidth="2"
        opacity="0.8"
      />
      <circle cx="450" cy="720" r="6" fill="#4fe0ff" filter="url(#ahal-glow)" />
    </svg>
  );
}

export function AihalLogo({
  className,
  iconClassName,
  textClassName,
  compact = false,
}: AihalLogoProps) {
  if (compact) {
    return (
      <div className={cn("flex items-center gap-2.5", className)}>
        <div className={cn("shrink-0", iconClassName)}>
          <AihalGlyph className="h-11 w-11" />
        </div>
        <div
          className={cn(
            "text-sm font-medium tracking-[0.24em] text-slate-100",
            textClassName
          )}
        >
          AHAL{" "}
          <span className="bg-gradient-to-r from-cyan-300 to-sky-500 bg-clip-text text-transparent">
            AI
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className={cn(className, textClassName)}>
      <AihalFullLogo />
    </div>
  );
}
