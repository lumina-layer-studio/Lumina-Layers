import type { ReactNode, KeyboardEventHandler } from "react";
import { AnimatePresence, motion, useIsPresent } from "framer-motion";
import "./ResourceDetailsPanel.css";

interface Props {
  open: boolean;
  as?: "aside" | "section";
  className: string;
  children: ReactNode;
  onKeyDown: KeyboardEventHandler<HTMLElement>;
  "aria-label"?: string;
  "data-testid"?: string;
}

function DetailSurface({ as = "section", children, ...props }: Omit<Props, "open">) {
  const present = useIsPresent();
  const Surface = as === "aside" ? motion.aside : motion.section;
  return <Surface {...props}
    className={`resource-detail-panel ${props.className}`}
    inert={!present}
    aria-hidden={!present || undefined}
    initial={{ opacity: 0, x: 12 }}
    animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: 8, transition: { duration: 0.16 } }}
    transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}>
    {children}
  </Surface>;
}

/** Keep the detail column in place until its exit finishes. */
export default function ResourceDetailsPanel({ open, ...props }: Props) {
  return <AnimatePresence initial={false}>
    {open && <DetailSurface key="detail" {...props} />}
  </AnimatePresence>;
}
