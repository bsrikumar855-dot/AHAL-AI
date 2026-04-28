"use client";

import { useEffect, useRef } from "react";

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  baseSpeed: number;
  opacity: number;
  color: string;
}

const PARTICLE_COUNT = 120;
const CONNECTION_DISTANCE = 100;
const REPULSION_DISTANCE = 150;
const PARTICLE_COLORS = [
  "255, 255, 255",
  "245, 243, 255",
  "221, 214, 254",
  "196, 181, 253",
];

export function ParticleCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const animationRef = useRef<number>(0);
  const pointerRef = useRef({ x: 0, y: 0, active: false });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const createParticle = (width: number, height: number): Particle => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.12,
      vy: 0,
      radius: 1 + Math.random() * 2,
      baseSpeed: 0.3 + Math.random() * 0.9,
      opacity: 0.28 + Math.random() * 0.45,
      color:
        PARTICLE_COLORS[Math.floor(Math.random() * PARTICLE_COLORS.length)],
    });

    const resize = () => {
      const width = window.innerWidth;
      const height = window.innerHeight;
      const dpr = window.devicePixelRatio || 1;

      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      particlesRef.current = Array.from({ length: PARTICLE_COUNT }, () =>
        createParticle(width, height)
      );
    };

    const handlePointerMove = (event: MouseEvent) => {
      pointerRef.current = {
        x: event.clientX,
        y: event.clientY,
        active: true,
      };
    };

    const handlePointerLeave = () => {
      pointerRef.current.active = false;
    };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseleave", handlePointerLeave);

    const animate = () => {
      const width = window.innerWidth;
      const height = window.innerHeight;
      const pointer = pointerRef.current;

      ctx.clearRect(0, 0, width, height);

      for (const particle of particlesRef.current) {
        particle.vx *= 0.985;
        particle.vy *= 0.94;

        particle.vx += (Math.random() - 0.5) * 0.01;
        particle.vx = Math.max(-0.35, Math.min(0.35, particle.vx));

        if (pointer.active) {
          const dx = particle.x - pointer.x;
          const dy = particle.y - pointer.y;
          const distance = Math.hypot(dx, dy);

          if (distance < REPULSION_DISTANCE && distance > 0.001) {
            const force = (1 - distance / REPULSION_DISTANCE) * 0.9;
            particle.vx += (dx / distance) * force;
            particle.vy += (dy / distance) * force;
          }
        }

        particle.y -= particle.baseSpeed;
        particle.x += particle.vx;
        particle.y += particle.vy;

        if (particle.y < -particle.radius - 8) {
          particle.y = height + particle.radius + Math.random() * 24;
          particle.x = Math.random() * width;
          particle.vx = (Math.random() - 0.5) * 0.12;
          particle.vy = 0;
        }

        if (particle.x < -particle.radius - 12) {
          particle.x = width + particle.radius + 12;
        } else if (particle.x > width + particle.radius + 12) {
          particle.x = -particle.radius - 12;
        }
      }

      for (let i = 0; i < particlesRef.current.length; i += 1) {
        const a = particlesRef.current[i];

        for (let j = i + 1; j < particlesRef.current.length; j += 1) {
          const b = particlesRef.current[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const distance = Math.hypot(dx, dy);

          if (distance < CONNECTION_DISTANCE) {
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = `rgba(196, 181, 253, ${0.07 * (1 - distance / CONNECTION_DISTANCE)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      for (const particle of particlesRef.current) {
        const glow = ctx.createRadialGradient(
          particle.x,
          particle.y,
          0,
          particle.x,
          particle.y,
          particle.radius * 3.5
        );

        glow.addColorStop(0, `rgba(${particle.color}, ${particle.opacity})`);
        glow.addColorStop(
          0.5,
          `rgba(${particle.color}, ${particle.opacity * 0.28})`
        );
        glow.addColorStop(1, `rgba(${particle.color}, 0)`);

        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.radius * 3.5, 0, Math.PI * 2);
        ctx.fillStyle = glow;
        ctx.fill();

        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${particle.color}, ${Math.min(1, particle.opacity + 0.2)})`;
        ctx.fill();
      }

      animationRef.current = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseleave", handlePointerLeave);
      cancelAnimationFrame(animationRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none z-0"
      style={{ opacity: 0.65 }}
    />
  );
}
