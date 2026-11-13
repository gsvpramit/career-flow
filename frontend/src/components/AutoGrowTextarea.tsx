import React, { useLayoutEffect, useRef, useCallback, useEffect } from "react";

export interface AutoGrowTextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  value: string;
  minHeight?: number;
}

export const AutoGrowTextarea: React.FC<AutoGrowTextareaProps> = ({
  value,
  minHeight = 36,
  style,
  className = "",
  onChange,
  ...props
}) => {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const computed = window.getComputedStyle(el);
    const borderTop = parseFloat(computed.borderTopWidth) || 0;
    const borderBottom = parseFloat(computed.borderBottomWidth) || 0;
    // Add border and a safe buffer so browser never renders a vertical scrollbar
    const nextH = Math.max(el.scrollHeight + borderTop + borderBottom + 3, minHeight);
    el.style.height = `${nextH}px`;
  }, [minHeight]);

  useLayoutEffect(() => {
    autoResize();
  }, [value, autoResize]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    const handleResize = () => autoResize();
    window.addEventListener("resize", handleResize);
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(() => autoResize());
      ro.observe(el);
    }
    return () => {
      window.removeEventListener("resize", handleResize);
      ro?.disconnect();
    };
  }, [autoResize]);

  return (
    <textarea
      ref={textareaRef}
      value={value}
      onChange={(e) => {
        onChange?.(e);
        autoResize();
      }}
      className={`auto-grow-textarea ${className}`}
      style={{
        width: "100%",
        boxSizing: "border-box",
        resize: "none",
        overflow: "hidden",
        minHeight,
        fieldSizing: "content" as any,
        lineHeight: "1.45",
        ...style,
      }}
      {...props}
    />
  );
};
