"use client";

import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useSpring,
} from "framer-motion";

interface TiltCardProps {
  children: React.ReactNode;
  className?: string;
}

export function TiltCard({ children, className }: TiltCardProps) {
  const rotateX = useMotionValue(0);
  const rotateY = useMotionValue(0);
  const glowX = useMotionValue(0);
  const glowY = useMotionValue(14);

  const springRotateX = useSpring(rotateX, {
    stiffness: 180,
    damping: 18,
    mass: 0.8,
  });
  const springRotateY = useSpring(rotateY, {
    stiffness: 180,
    damping: 18,
    mass: 0.8,
  });
  const springGlowX = useSpring(glowX, { stiffness: 140, damping: 20 });
  const springGlowY = useSpring(glowY, { stiffness: 140, damping: 20 });

  const transform = useMotionTemplate`perspective(600px) rotateX(${springRotateX}deg) rotateY(${springRotateY}deg)`;
  const boxShadow = useMotionTemplate`${springGlowX}px ${springGlowY}px 32px rgba(139, 92, 246, 0.18), 0 0 0 1px rgba(139, 92, 246, 0.16)`;

  const handleMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const offsetX = (event.clientX - bounds.left) / bounds.width - 0.5;
    const offsetY = (event.clientY - bounds.top) / bounds.height - 0.5;

    rotateX.set(-offsetY * 16);
    rotateY.set(offsetX * 16);
    glowX.set(offsetX * 24);
    glowY.set(16 + offsetY * 24);
  };

  const handleMouseLeave = () => {
    rotateX.set(0);
    rotateY.set(0);
    glowX.set(0);
    glowY.set(14);
  };

  return (
    <motion.div
      style={{ transform, boxShadow }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className={className}
    >
      {children}
    </motion.div>
  );
}
