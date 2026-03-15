import { useState } from "react";
import type { Placement } from "@floating-ui/react";
import {
  useFloating,
  useHover,
  useDismiss,
  useRole,
  useInteractions,
  offset,
  flip,
  shift,
  autoUpdate,
  FloatingPortal,
} from "@floating-ui/react";
import { AnimatePresence, motion } from "framer-motion";
import { useI18n } from "../../i18n/context";

interface WikiTooltipProps {
  /** Trigger element to wrap */
  children: React.ReactNode;
  /** Tooltip title text */
  title: string;
  /** Tooltip description text */
  description: string;
  /** Optional wiki URL for external link */
  wikiUrl?: string;
  /** Preferred placement direction, default "top" */
  placement?: Placement;
  /** Hover delay in ms before showing, default 600 */
  delay?: number;
}

export default function WikiTooltip({
  children,
  title,
  description,
  wikiUrl,
  placement = "top",
  delay = 600,
}: WikiTooltipProps) {
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);

  // 1. useFloating — positioning engine + middleware
  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: setIsOpen,
    placement,
    middleware: [
      offset(8),
      flip(),
      shift({ padding: 8 }),
    ],
    whileElementsMounted: autoUpdate,
  });

  // 2. useHover — delay + safe hover bridge
  const hover = useHover(context, {
    delay: { open: delay, close: 150 },
    move: false,
  });

  // 3. useDismiss — close on Escape
  const dismiss = useDismiss(context);

  // 4. useRole — aria role="tooltip"
  const role = useRole(context, { role: "tooltip" });

  // 5. merge interactions
  const { getReferenceProps, getFloatingProps } = useInteractions([
    hover,
    dismiss,
    role,
  ]);

  // 6. render
  return (
    <>
      <span
        ref={refs.setReference}
        {...getReferenceProps()}
        style={{ display: "inline-block" }}
      >
        {children}
      </span>

      <FloatingPortal>
        <AnimatePresence>
          {isOpen && (
            <div
              ref={refs.setFloating}
              style={floatingStyles}
              {...getFloatingProps()}
              className="z-[9999]"
            >
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 4 }}
                transition={{ duration: 0.15 }}
                className="rounded-lg px-3 py-2.5 shadow-lg max-w-xs bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700"
              >
                <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {title}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {description}
                </div>
                {wikiUrl && (
                  <a
                    href={wikiUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-500 hover:text-blue-600 dark:text-blue-400 dark:hover:text-blue-300 mt-2 inline-flex items-center gap-1"
                  >
                    {t("wiki_tooltip_link")}
                  </a>
                )}
              </motion.div>
            </div>
          )}
        </AnimatePresence>
      </FloatingPortal>
    </>
  );
}
