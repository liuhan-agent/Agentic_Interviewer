"use client";

import React, { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const THUMB_SIZE_PX = 56;

function getPageScrollHeight() {
  return Math.max(
    document.documentElement.scrollHeight,
    document.body.scrollHeight,
  );
}

function getPageScrollTop() {
  return (
    window.scrollY ||
    document.documentElement.scrollTop ||
    document.body.scrollTop ||
    0
  );
}

export function LightScrollWheel() {
  const [progress, setProgress] = useState(0);
  const [canScroll, setCanScroll] = useState(false);
  const [dragging, setDragging] = useState(false);
  const trackRef = useRef<HTMLButtonElement>(null);
  const thumbRef = useRef<HTMLSpanElement>(null);
  const draggingRef = useRef(false);
  const progressRef = useRef(0);

  function syncThumbPosition(nextProgress: number) {
    const track = trackRef.current;
    const thumb = thumbRef.current;
    if (!track || !thumb) return;
    const travel = Math.max(
      0,
      track.getBoundingClientRect().height - THUMB_SIZE_PX,
    );
    const thumbTop = Math.min(1, Math.max(0, nextProgress)) * travel;
    thumb.style.transform = `translate3d(-50%, ${thumbTop}px, 0)`;
  }

  useEffect(() => {
    function updateProgress() {
      const maxScroll = Math.max(0, getPageScrollHeight() - window.innerHeight);
      const nextProgress =
        maxScroll > 0
          ? Math.min(1, Math.max(0, getPageScrollTop() / maxScroll))
          : 0;
      setCanScroll(maxScroll > 24);
      progressRef.current = nextProgress;
      setProgress(nextProgress);
      syncThumbPosition(nextProgress);
    }

    updateProgress();
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(updateProgress);
    resizeObserver?.observe(document.documentElement);
    resizeObserver?.observe(document.body);
    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", updateProgress);
    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("scroll", updateProgress);
      window.removeEventListener("resize", updateProgress);
    };
  }, []);

  useEffect(() => {
    syncThumbPosition(progressRef.current);
  }, [canScroll]);

  if (!canScroll) return null;

  function scrollToProgress(
    nextProgress: number,
    behavior: ScrollBehavior = "smooth",
  ) {
    const maxScroll = Math.max(0, getPageScrollHeight() - window.innerHeight);
    const bounded = Math.min(1, Math.max(0, nextProgress));
    progressRef.current = bounded;
    syncThumbPosition(bounded);
    setProgress(bounded);
    window.scrollTo({ top: maxScroll * bounded, behavior });
  }

  function scrollToPointer(clientY: number, behavior: ScrollBehavior = "auto") {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect) return;
    const travel = Math.max(1, rect.height - THUMB_SIZE_PX);
    scrollToProgress(
      (clientY - rect.top - THUMB_SIZE_PX / 2) / travel,
      behavior,
    );
  }

  function handlePointerDown(event: React.PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    draggingRef.current = true;
    setDragging(true);
    scrollToPointer(event.clientY);
  }

  function handlePointerMove(event: React.PointerEvent<HTMLButtonElement>) {
    if (!draggingRef.current) return;
    event.preventDefault();
    scrollToPointer(event.clientY);
  }

  function handlePointerUp(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    draggingRef.current = false;
    setDragging(false);
  }

  return (
    <aside
      aria-label="页面滚轮"
      className="group fixed top-10 right-3 bottom-8 z-40 hidden w-8 items-center justify-center opacity-40 transition-opacity duration-200 hover:opacity-100 md:flex"
    >
      <button
        ref={trackRef}
        type="button"
        aria-label="拖动滚轮跳转页面位置"
        aria-controls="app-main-content"
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={Math.round(progress * 100)}
        role="scrollbar"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        className={cn(
          "relative h-full w-8 cursor-grab touch-none select-none rounded-full p-0 active:cursor-grabbing",
          dragging ? "cursor-grabbing" : "",
        )}
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-1/2 top-0 h-0 w-0 -translate-x-1/2 border-x-[8px] border-b-[10px] border-x-transparent border-b-foreground/25 transition-colors group-hover:border-b-foreground/35"
        />
        <span
          aria-hidden="true"
          className={cn(
            "pointer-events-none absolute left-1/2 top-5 bottom-5 w-px -translate-x-1/2 rounded-full bg-foreground/[0.08] transition-[background-color,width] duration-150",
            dragging
              ? "w-1 bg-foreground/[0.14]"
              : "group-hover:w-1 group-hover:bg-foreground/[0.14]",
          )}
        />
        <span
          ref={thumbRef}
          className={cn(
            "pointer-events-none absolute left-1/2 top-0 h-14 w-4 rounded-full bg-foreground/25 shadow-sm will-change-transform transition-[background-color,width] duration-150",
            dragging ? "scale-105 bg-foreground/35" : "group-hover:bg-foreground/30",
          )}
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0 left-1/2 h-0 w-0 -translate-x-1/2 border-x-[8px] border-t-[10px] border-x-transparent border-t-foreground/25 transition-colors group-hover:border-t-foreground/35"
        />
      </button>
    </aside>
  );
}
