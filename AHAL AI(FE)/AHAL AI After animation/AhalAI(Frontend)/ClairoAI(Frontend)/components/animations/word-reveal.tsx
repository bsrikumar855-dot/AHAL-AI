"use client";

import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";

interface WordRevealProps {
  text: string;
  className?: string;
  wordClassName?: string;
}

export function WordReveal({
  text,
  className,
  wordClassName,
}: WordRevealProps) {
  const words = useMemo(() => text.split(" "), [text]);
  return (
    <motion.span
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-60px 0px -60px 0px" }}
      className={className}
    >
      {words.map((word, index) => (
        <span key={`${word}-${index}`} className="inline-block overflow-hidden align-top">
          <motion.span
            variants={{
              hidden: { opacity: 0, y: 20 },
              visible: { opacity: 1, y: 0 },
            }}
            transition={{
              duration: 0.6,
              delay: index * 0.08,
              ease: [0.4, 0, 0.2, 1],
            }}
            className={`inline-block ${wordClassName ?? ""}`}
          >
            {word}
            {index < words.length - 1 ? "\u00A0" : ""}
          </motion.span>
        </span>
      ))}
    </motion.span>
  );
}
