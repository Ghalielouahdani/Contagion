/**
 * Motion primitives shared by the app, taken from nickpyl.space (see theme/motion.css):
 * - InteractiveLabel: text that springs to 1.03 on hover and sweeps a colour gradient through its letters;
 * - useCountUp / Figure: Fuse-style figures that count to their value, cents greyed;
 * - withViewTransition: zoom between two states through the View Transitions API (section-preview).
 */
import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

type Bezier = [number, number, number, number];
export const EASE: Bezier = [0.22, 1, 0.36, 1];
export const EASE_REVEAL: Bezier = [0.25, 0.1, 0.25, 1];
export const SPRING = { type: "spring", stiffness: 170, damping: 22, mass: 0.9 } as const;

/** Reveal used for blocks of copy: blur(8px) -> sharp, like the reference's page-reveal. */
export const reveal = (delay = 0) => ({
  initial: { opacity: 0, filter: "blur(8px)" },
  animate: { opacity: 1, filter: "blur(0px)", transition: { duration: 0.52, ease: EASE_REVEAL, delay } },
  exit: { opacity: 0, filter: "blur(8px)", transition: { duration: 0.28, ease: "easeInOut" as const } },
});

export function InteractiveLabel({ children }: { children: string }) {
  return (
    <span className="interactive-label">
      {children}
      <span className="interactive-label-gradient" aria-hidden="true">{children}</span>
    </span>
  );
}

/** Animates from the previous value to `target` (0 on first render). Instant under reduced motion. */
export function useCountUp(target: number, duration = 1.1, delay = 0) {
  const reduce = useReducedMotion();
  const [value, setValue] = useState(reduce ? target : 0);
  const from = useRef(reduce ? target : 0);
  useEffect(() => {
    if (reduce || !Number.isFinite(target)) {
      setValue(target);
      from.current = target;
      return;
    }
    const controls = animate(from.current, target, {
      duration,
      delay,
      ease: EASE,
      onUpdate: (v) => {
        from.current = v;
        setValue(v);
      },
    });
    return () => controls.stop();
  }, [target, duration, delay, reduce]);
  return value;
}

export function splitMoney(value: number) {
  const sign = value < 0 ? "−" : "";
  const abs = Math.abs(value);
  const whole = Math.floor(abs + 1e-9);
  const cents = Math.round((abs - whole) * 100);
  const carry = cents === 100;
  return {
    whole: `${sign}$${(carry ? whole + 1 : whole).toLocaleString("en-US")}`,
    cents: `.${String(carry ? 0 : cents).padStart(2, "0")}`,
  };
}

/** Fuse-style money figure: dollars in ink, cents greyed; counts up to its value. */
export function Figure({ value, delay = 0, className = "" }: { value: number; delay?: number; className?: string }) {
  const shown = useCountUp(value, 1.1, delay);
  const { whole, cents } = splitMoney(shown);
  return (
    <span className={`np-figure ${className}`} aria-label={`${splitMoney(value).whole}${splitMoney(value).cents}`}>
      {whole}
      <span className="np-cents">{cents}</span>
    </span>
  );
}

type TransitionDocument = Document & { startViewTransition?: (update: () => void) => unknown };

/** Runs a state update inside a View Transition when the browser supports it and motion is allowed. */
export function withViewTransition(update: () => void) {
  const doc = document as TransitionDocument;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (!doc.startViewTransition || reduce) {
    update();
    return;
  }
  doc.startViewTransition(() => flushSync(update));
}
