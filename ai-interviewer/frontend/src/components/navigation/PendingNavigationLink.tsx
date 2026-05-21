"use client";

import Link, { type LinkProps } from "next/link";
import { usePathname } from "next/navigation";
import {
  useEffect,
  useState,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

type PendingNavigationLinkProps = LinkProps &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, keyof LinkProps | "href"> & {
    pendingClassName?: string;
    pendingLabel?: ReactNode;
    showPendingIcon?: boolean;
    spinnerClassName?: string;
  };

function isModifiedNavigation(event: MouseEvent<HTMLAnchorElement>) {
  return (
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    event.button !== 0
  );
}

function getHrefPathname(href: LinkProps["href"]) {
  if (typeof href === "string") {
    return href.split("?")[0]?.split("#")[0] || "/";
  }

  return href.pathname ?? null;
}

export function PendingNavigationLink({
  children,
  className,
  href,
  onClick,
  pendingClassName,
  pendingLabel,
  showPendingIcon = true,
  spinnerClassName,
  target,
  ...props
}: PendingNavigationLinkProps) {
  const pathname = usePathname();
  const [isPending, setIsPending] = useState(false);

  useEffect(() => {
    if (isPending && getHrefPathname(href) === pathname) {
      setIsPending(false);
    }
  }, [href, isPending, pathname]);

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);

    if (
      event.defaultPrevented ||
      isPending ||
      isModifiedNavigation(event) ||
      (target && target !== "_self") ||
      getHrefPathname(href) === pathname
    ) {
      return;
    }

    setIsPending(true);
  }

  return (
    <Link
      {...props}
      href={href}
      target={target}
      onClick={handleClick}
      aria-busy={isPending || undefined}
      aria-disabled={isPending || undefined}
      data-pending={isPending ? "" : undefined}
      className={cn(
        className,
        isPending && "pointer-events-none opacity-80",
        isPending && pendingClassName,
      )}
    >
      {isPending && showPendingIcon && (
        <Loader2
          aria-hidden="true"
          className={cn("h-4 w-4 shrink-0 animate-spin", spinnerClassName)}
        />
      )}
      {isPending && pendingLabel ? pendingLabel : children}
    </Link>
  );
}
