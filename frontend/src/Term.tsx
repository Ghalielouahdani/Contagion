import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { explain } from "./lib/glossary";

const TIP_WIDTH = 280;

/**
 * A label with its plain-language definition on hover or keyboard focus (glossary.ts).
 * The tooltip is portalled to <body> and positioned against the viewport: clipping containers
 * (stat strips, scrolling tables) and animated, transformed parents never cut or shift it.
 * Without a definition the text renders unchanged.
 */
export function Term({ children, text }: { children: string; text?: string }) {
  const definition = text ?? explain(children);
  const id = useId();
  const anchor = useRef<HTMLSpanElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number; above: boolean } | null>(null);
  if (!definition) return <>{children}</>;

  const show = () => {
    const rect = anchor.current?.getBoundingClientRect();
    if (!rect) return;
    const above = rect.bottom + 140 > window.innerHeight;
    setPosition({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - TIP_WIDTH - 8)),
      top: above ? rect.top - 6 : rect.bottom + 6,
      above,
    });
  };
  const hide = () => setPosition(null);

  return (
    <span
      ref={anchor}
      className="term"
      tabIndex={0}
      aria-describedby={id}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {createPortal(
        <span
          role="tooltip"
          id={id}
          className="term-tip"
          data-open={position !== null}
          style={position ? { left: position.left, top: position.top, transform: position.above ? "translateY(-100%)" : undefined } : undefined}
        >
          {definition}
        </span>,
        document.body,
      )}
    </span>
  );
}
