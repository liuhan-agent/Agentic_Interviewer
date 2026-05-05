import * as React from "react";

import { cn } from "@/lib/utils";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  autoResize?: boolean;
  maxAutoResizeHeight?: number;
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  (
    {
      className,
      autoResize = true,
      maxAutoResizeHeight = 360,
      onInput,
      style,
      value,
      defaultValue,
      rows,
      ...props
    },
    ref,
  ) => {
    const innerRef = React.useRef<HTMLTextAreaElement | null>(null);

    const setRef = React.useCallback(
      (node: HTMLTextAreaElement | null) => {
        innerRef.current = node;
        if (typeof ref === "function") {
          ref(node);
        } else if (ref) {
          ref.current = node;
        }
      },
      [ref],
    );

    const resize = React.useCallback(() => {
      if (!autoResize) return;
      const node = innerRef.current;
      if (!node) return;

      node.style.height = "auto";
      const nextHeight = Math.min(node.scrollHeight, maxAutoResizeHeight);
      node.style.height = `${nextHeight}px`;
      node.style.overflowY =
        node.scrollHeight > maxAutoResizeHeight ? "auto" : "hidden";
    }, [autoResize, maxAutoResizeHeight]);

    React.useLayoutEffect(() => {
      resize();
    }, [resize, value, defaultValue, rows]);

    const handleInput = (event: React.FormEvent<HTMLTextAreaElement>) => {
      resize();
      onInput?.(event);
    };

    return (
      <textarea
        className={cn(
          "flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        ref={setRef}
        rows={rows}
        value={value}
        defaultValue={defaultValue}
        onInput={handleInput}
        style={style}
        {...props}
      />
    );
  },
);
Textarea.displayName = "Textarea";

export { Textarea };
