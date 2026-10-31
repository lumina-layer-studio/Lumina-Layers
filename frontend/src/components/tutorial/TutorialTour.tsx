import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, JSX, SyntheticEvent } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/context";
import { TUTORIAL_STEPS } from "../../data/tutorialSteps";
import type { TutorialStep } from "../../data/tutorialSteps";
import { useDialogFocusTrap } from "../../hooks/useDialogFocusTrap";
import { findTutorialAnchorElement, useTutorialAnchor } from "../../hooks/useTutorialAnchor";
import { useTutorialStore } from "../../stores/tutorialStore";
import Button from "../ui/Button";
import { computeTutorialCardPosition } from "./tutorialPlacement";
import { PrintSizeIllustration, TutorialPalettes } from "./TutorialVisuals";
import type { TutorialRect, TutorialSize } from "./tutorialPlacement";

/** Extra room drawn around the spotlighted element. 高亮框相对目标的外扩距离。 */
const SPOTLIGHT_PADDING_PX = 6;
const SPOTLIGHT_RADIUS_PX = 14;
const DEFAULT_CARD_SIZE: TutorialSize = { width: 380, height: 280 };

function readViewport(): TutorialSize {
  return { width: window.innerWidth, height: window.innerHeight };
}

function useViewportSize(): TutorialSize {
  const [viewport, setViewport] = useState<TutorialSize>(readViewport);
  useEffect(() => {
    const handleResize = () => setViewport(readViewport());
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);
  return viewport;
}

const stopEvent = (event: SyntheticEvent) => event.stopPropagation();

const MODAL_SELECTOR = '[role="dialog"][aria-modal="true"], [role="alertdialog"]';

/**
 * True while a dialog the user opened (device picker, crop, a confirmation…)
 * is on screen and is not the step's own target. The tour then steps aside so
 * the dialog can be used, and comes back when it closes.
 * 用户打开的对话框（设备选择、裁剪、确认框等）在屏幕上、且不是本步目标时为真。
 * 此时引导让开，对话框关闭后再回来。
 */
function hasForeignModal(anchor: TutorialStep["anchor"]): boolean {
  const target = findTutorialAnchorElement(anchor);
  return Array.from(document.querySelectorAll<HTMLElement>(MODAL_SELECTOR)).some(
    (modal) =>
      !modal.closest('[data-testid="tutorial-tour"]') &&
      !(target && modal.contains(target)) &&
      modal.getClientRects().length > 0,
  );
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  );
}

/**
 * Transparent layer that blocks the app. With a `hole`, it is built from four
 * strips around the hole so pointer and wheel input inside it reach the app.
 * 屏蔽界面的透明层；传入 `hole` 时改为围绕镂空的四条遮挡，镂空内的指针和滚轮
 * 操作可以传到下方界面。
 */
function TutorialClickShield({
  hole,
  dimmed,
}: {
  hole: TutorialRect | null;
  dimmed: boolean;
}) {
  const shieldProps = {
    onClick: stopEvent,
    onPointerDown: stopEvent,
  };
  if (!hole) {
    return (
      <div
        className="pointer-events-auto absolute inset-0"
        style={dimmed ? { background: "var(--surface-scrim)" } : undefined}
        data-testid="tutorial-click-shield"
        {...shieldProps}
      />
    );
  }
  const top = Math.max(0, hole.top);
  const bottom = hole.top + hole.height;
  const strips: CSSProperties[] = [
    { top: 0, left: 0, right: 0, height: top },
    { top: bottom, left: 0, right: 0, bottom: 0 },
    { top, left: 0, width: Math.max(0, hole.left), height: hole.height },
    { top, left: hole.left + hole.width, right: 0, height: hole.height },
  ];
  return (
    <>
      {strips.map((style, index) => (
        <div
          key={index}
          className="pointer-events-auto absolute"
          style={style}
          data-testid="tutorial-click-shield-part"
          {...shieldProps}
        />
      ))}
    </>
  );
}

function TutorialControlList({ step }: { step: TutorialStep }) {
  const { t } = useI18n();
  if (!step.controlHints || step.controlHints.length === 0) {
    return null;
  }
  return (
    <dl
      className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1.5 rounded-xl border border-slate-200/80 bg-slate-100/60 px-3 py-2.5 text-xs leading-5 dark:border-slate-700/60 dark:bg-slate-900/50"
      aria-label={t("tutorial_controls_label")}
      data-testid="tutorial-controls"
    >
      {step.controlHints.map((hint) => (
        <div key={hint.gestureKey} className="contents">
          <dt className="justify-self-start rounded-md border border-slate-300/80 bg-slate-100 px-2 py-0.5 font-semibold text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200">
            {t(hint.gestureKey)}
          </dt>
          <dd className="text-slate-600 dark:text-slate-300">{t(hint.effectKey)}</dd>
        </div>
      ))}
    </dl>
  );
}

function TutorialStepDetails({ step }: { step: TutorialStep }) {
  const { t } = useI18n();
  return (
    <>
      <TutorialControlList step={step} />
      {step.palettes && step.palettes.length > 0 ? (
        <TutorialPalettes palettes={step.palettes} />
      ) : null}
      {step.illustration === "print-size" ? <PrintSizeIllustration /> : null}
      {step.interactive && !step.controlHints ? (
        <p
          className="mt-3 text-xs leading-5 text-blue-700 dark:text-blue-300"
          data-testid="tutorial-interactive-hint"
        >
          {t(step.advance ? "tutorial_interactive_auto_hint" : "tutorial_interactive_hint")}
        </p>
      ) : null}
      {step.flowKeys && step.flowKeys.length > 0 ? (
        <ol
          className="mt-3 flex flex-wrap items-center gap-1.5"
          aria-label={t("tutorial_flow_label")}
          data-testid="tutorial-flow"
        >
          {/* Numbered chips instead of arrows so the order stays readable
              however the row wraps. */}
          {step.flowKeys.map((key, index) => (
            <li
              key={key}
              className="flex items-center gap-1.5 rounded-full bg-blue-50 py-1 pl-1 pr-2.5 text-xs font-medium text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
            >
              <span
                aria-hidden="true"
                className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-semibold text-white dark:bg-blue-500"
              >
                {index + 1}
              </span>
              {t(key)}
            </li>
          ))}
        </ol>
      ) : null}
      {step.needKey || step.fitKey ? (
        <dl className="mt-3 flex flex-col gap-1.5 rounded-xl border border-slate-200/80 bg-slate-100/60 px-3 py-2 text-xs leading-5 dark:border-slate-700/60 dark:bg-slate-900/50">
          {step.needKey ? (
            <div>
              <dt className="inline font-semibold text-slate-700 dark:text-slate-200">
                {t("tutorial_need_label")}
              </dt>
              <dd className="inline text-slate-600 dark:text-slate-300">{t(step.needKey)}</dd>
            </div>
          ) : null}
          {step.fitKey ? (
            <div>
              <dt className="inline font-semibold text-slate-700 dark:text-slate-200">
                {t("tutorial_fit_label")}
              </dt>
              <dd className="inline text-slate-600 dark:text-slate-300">{t(step.fitKey)}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </>
  );
}

/**
 * Spotlight tour: dims the app, outlines the current step's element, and
 * shows an explanation card beside it.
 * 分步高亮引导：压暗界面、框出当前步骤的元素，并在旁边显示说明卡片。
 *
 * Outside the spotlight the app is blocked so a stray click cannot start a
 * job. Steps marked `interactive` leave the spotlight usable, so the user can
 * set things up right there (pick a device, choose materials, set the layer
 * height…) but never has to. When the user opens a dialog from the spotlight
 * the tour steps aside until it closes. When the element cannot be found the
 * card is centered and the tour continues.
 * 高亮区域外的界面被屏蔽，避免误触启动任务。标记为 `interactive` 的步骤放开高亮
 * 区域，用户可以直接在引导里完成设置（选设备、选耗材、设层高等），但不强制。用户
 * 从高亮区域打开对话框时，引导暂时让开，关闭后再回来。找不到目标元素时卡片居中显示。
 */
export default function TutorialTour(): JSX.Element | null {
  const { t } = useI18n();
  const stepIndex = useTutorialStore((s) => s.stepIndex);
  const next = useTutorialStore((s) => s.next);
  const back = useTutorialStore((s) => s.back);
  const skip = useTutorialStore((s) => s.skip);
  const step = TUTORIAL_STEPS[stepIndex] ?? TUTORIAL_STEPS[0];
  const isFirst = stepIndex === 0;
  const isLast = stepIndex === TUTORIAL_STEPS.length - 1;

  const anchor = useTutorialAnchor(step.anchor);
  const viewport = useViewportSize();
  const cardRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [cardSize, setCardSize] = useState<TutorialSize>(DEFAULT_CARD_SIZE);
  const [suspended, setSuspended] = useState(false);
  // Interactive steps let focus move into the spotlight (e.g. a search box).
  // 可操作的步骤允许焦点进入高亮区域（例如搜索框）。
  useDialogFocusTrap(cardRef, !step.interactive && !suspended);

  useEffect(() => {
    const check = () => {
      const foreign = hasForeignModal(step.anchor);
      setSuspended((previous) => (previous === foreign ? previous : foreign));
    };
    check();
    const timer = window.setInterval(check, 150);
    return () => window.clearInterval(timer);
  }, [step.anchor]);

  // Card height changes with each step's copy; re-measure whenever it resizes.
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) {
      return;
    }
    const measure = () => {
      const width = card.offsetWidth;
      const height = card.offsetHeight;
      if (width <= 0) {
        return;
      }
      setCardSize((prev) =>
        prev.width === width && prev.height === height ? prev : { width, height },
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(card);
    return () => observer.disconnect();
    // Re-attach when the card mounts again after the tour stepped aside.
    // 引导让开后卡片重新挂载时需要重新测量。
  }, [suspended]);

  useEffect(() => {
    if (!suspended) cardRef.current?.focus({ preventScroll: true });
  }, [stepIndex, anchor.status, suspended]);

  // Each step starts reading from the top of its (possibly scrolled) copy.
  useEffect(() => {
    bodyRef.current?.scrollTo?.({ top: 0 });
  }, [stepIndex]);

  useEffect(() => {
    if (suspended) {
      // A dialog the user opened has the keyboard (Escape closes it, not the tour).
      // 用户打开的对话框处理键盘（Esc 关闭对话框而不是引导）。
      return undefined;
    }
    // Capture phase + stopPropagation: the tour owns these keys, so a dialog it
    // has opened underneath (the material picker) does not also react to
    // Escape. Arrow keys inside a text field keep moving the caret.
    // 捕获阶段并阻止传播：这些按键由引导处理，避免其下方打开的对话框（耗材选择框）
    // 同时响应 Esc；在输入框里按方向键仍用于移动光标。
    const handleKeyDown = (event: KeyboardEvent) => {
      // Checked at key time too: a dialog may have just opened before React
      // has re-run this effect. 按键时再检查一次：对话框可能刚打开、本效果尚未重跑。
      if (hasForeignModal(step.anchor)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        skip("escape");
      } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        if (isEditableTarget(event.target)) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.key === "ArrowRight") next();
        else back();
      } else if (event.key === "Tab" && !step.interactive) {
        event.stopPropagation();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [next, back, skip, suspended, step.interactive, step.anchor]);

  if (typeof document === "undefined" || suspended) {
    return null;
  }

  const spotlight =
    anchor.status === "found" && anchor.rect
      ? {
          top: anchor.rect.top - SPOTLIGHT_PADDING_PX,
          left: anchor.rect.left - SPOTLIGHT_PADDING_PX,
          width: anchor.rect.width + SPOTLIGHT_PADDING_PX * 2,
          height: anchor.rect.height + SPOTLIGHT_PADDING_PX * 2,
        }
      : null;
  const position = computeTutorialCardPosition(spotlight, cardSize, viewport, {
    inside: Boolean(step.cardInside),
  });
  const showCard = anchor.status !== "searching";
  const passThroughHole = step.interactive && spotlight ? spotlight : null;

  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-[10005]" data-testid="tutorial-tour">
      {/* Click shield: blocks the app outside the spotlight. Interactive steps
          leave the spotlight open so the user can set things up there. The
          tour sits above dialogs (z 9999–10000) but below dropdown menus
          (z 10010), so a dropdown opened in the spotlight stays usable. */}
      <TutorialClickShield hole={passThroughHole} dimmed={!spotlight} />

      {spotlight ? (
        <>
          {/* Dim layer with a rounded cut-out. The app disables box-shadow
              globally, so the scrim is drawn with an SVG mask instead. The
              cut-out and outline are positioned directly (no animation) so
              they always stay on the same element; framer-motion treats SVG
              `x`/`y` as transforms, which drifted the cut-out on fast steps. */}
          <svg aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full">
            <defs>
              <mask id="tutorial-spotlight-mask">
                <rect width="100%" height="100%" fill="white" />
                <rect
                  data-testid="tutorial-spotlight-cutout"
                  x={spotlight.left}
                  y={spotlight.top}
                  width={spotlight.width}
                  height={spotlight.height}
                  rx={SPOTLIGHT_RADIUS_PX}
                  fill="black"
                />
              </mask>
            </defs>
            <rect
              width="100%"
              height="100%"
              mask="url(#tutorial-spotlight-mask)"
              style={{ fill: "var(--surface-scrim)" }}
            />
          </svg>
          <div
            aria-hidden="true"
            data-testid="tutorial-spotlight"
            className="pointer-events-none absolute border-2 border-blue-500 dark:border-blue-400"
            style={{ ...spotlight, borderRadius: SPOTLIGHT_RADIUS_PX }}
          />
        </>
      ) : null}

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-step-title"
        aria-describedby="tutorial-step-body"
        tabIndex={-1}
        data-testid="tutorial-card"
        data-side={position.side}
        className="pointer-events-auto absolute flex max-h-[calc(100dvh-32px)] w-[min(380px,calc(100vw-32px))] flex-col rounded-2xl border shadow-2xl outline-none"
        style={{
          top: position.top,
          left: position.left,
          visibility: showCard ? "visible" : "hidden",
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
      >
        {/* Header and actions stay pinned; only the copy scrolls on short
            windows, so Skip and Next/Done are always reachable. */}
        <div className="flex shrink-0 items-center justify-between gap-3 px-5 pt-5">
          <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">
            {t("tutorial_progress_label")} · {stepIndex + 1} / {TUTORIAL_STEPS.length}
          </span>
          <button
            type="button"
            data-testid="tutorial-skip-button"
            onClick={() => skip("skip_button")}
            className="rounded-lg px-2 py-1 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            {t("tutorial_skip")}
          </button>
        </div>

        <div
          ref={bodyRef}
          className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain px-5"
          data-testid="tutorial-card-body"
        >
          <h2
            id="tutorial-step-title"
            className="mt-2 text-base font-semibold text-slate-800 dark:text-slate-100"
          >
            {t(step.titleKey)}
          </h2>
          <p
            id="tutorial-step-body"
            className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-600 dark:text-slate-300"
          >
            {t(step.bodyKey)}
          </p>

          <TutorialStepDetails step={step} />
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 px-5 pb-5 pt-4">
          {!isFirst ? (
            <Button label={t("tutorial_back")} variant="secondary" size="sm" onClick={back} />
          ) : null}
          <Button
            label={isLast ? t("tutorial_done") : t("tutorial_next")}
            variant="primary"
            size="sm"
            onClick={next}
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
