/**
 * Small visuals shown inside tutorial cards: recommended palettes and the
 * print-size illustration.
 * 引导卡片中的小型图示：推荐配色和打印尺寸示意图。
 */
import type { JSX } from "react";
import { useI18n } from "../../i18n/context";
import type { TutorialPalette, TutorialSwatch } from "../../data/tutorialSteps";

/** Clear filament: a checkerboard behind a dashed ring. 透明耗材：棋盘格加虚线圈。 */
const CLEAR_SWATCH_BACKGROUND =
  "repeating-conic-gradient(var(--palette-white) 0% 25%, var(--surface-outline) 0% 50%) 50% / 8px 8px";

function Swatch({ swatch }: { swatch: TutorialSwatch }): JSX.Element {
  const { t } = useI18n();
  const clear = swatch.color === null;
  return (
    <li className="flex w-8 flex-col items-center gap-1">
      <span
        aria-hidden="true"
        className={
          clear
            ? "h-5 w-5 rounded-full border-2 border-dashed border-slate-400 dark:border-slate-500"
            : "h-5 w-5 rounded-full ring-1 ring-black/15 dark:ring-white/25"
        }
        style={{ background: clear ? CLEAR_SWATCH_BACKGROUND : (swatch.color ?? undefined) }}
      />
      <span className="text-[11px] leading-none text-slate-600 dark:text-slate-300">
        {t(swatch.labelKey)}
      </span>
    </li>
  );
}

export function TutorialPalettes({
  palettes,
}: {
  palettes: readonly TutorialPalette[];
}): JSX.Element {
  const { t } = useI18n();
  return (
    <div className="mt-3 flex flex-col gap-2.5" data-testid="tutorial-palettes">
      {palettes.map((palette) => (
        <section
          key={palette.titleKey}
          className="rounded-xl border border-slate-200/80 bg-slate-100/60 px-3 py-2.5 dark:border-slate-700/60 dark:bg-slate-900/50"
        >
          <h3 className="text-xs font-semibold text-slate-700 dark:text-slate-200">
            {t(palette.titleKey)}
          </h3>
          <ul className="mt-2 flex flex-wrap gap-x-0.5 gap-y-2" aria-label={t(palette.titleKey)}>
            {palette.swatches.map((swatch) => (
              <Swatch key={swatch.labelKey} swatch={swatch} />
            ))}
          </ul>
          {palette.noteKey ? (
            <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
              {t(palette.noteKey)}
            </p>
          ) : null}
        </section>
      ))}
    </div>
  );
}

// A small "sunset" picture (sky, sun, hills) sampled on a grid. A finer grid
// stands for the same picture printed larger: more printed cells, more detail.
// 用网格采样的小画面（天空、太阳、山丘）。网格越细代表同一张图打得越大：色块越多，细节越清楚。
const SCENE_COLORS = [
  "var(--palette-cyan)",
  "var(--palette-yellow)",
  "var(--palette-crimson)",
  "var(--palette-green)",
  "var(--palette-white)",
] as const;

function sceneColorIndex(x: number, y: number): number {
  const sunDx = x - 0.62;
  const sunDy = y - 0.38;
  if (sunDx * sunDx + sunDy * sunDy < 0.035) return 1;
  if ((sunDx * sunDx + sunDy * sunDy) < 0.06) return 2;
  const hill = 0.72 + 0.1 * Math.sin(x * 7.5);
  if (y > hill) return 3;
  const cloudDx = (x - 0.25) / 1.8;
  const cloudDy = y - 0.22;
  if (cloudDx * cloudDx + cloudDy * cloudDy < 0.006) return 4;
  return 0;
}

function SampledScene({ cells, size }: { cells: number; size: number }): JSX.Element {
  const cell = size / cells;
  const rects: JSX.Element[] = [];
  for (let row = 0; row < cells; row += 1) {
    for (let col = 0; col < cells; col += 1) {
      const index = sceneColorIndex((col + 0.5) / cells, (row + 0.5) / cells);
      rects.push(
        <rect
          key={`${row}-${col}`}
          x={col * cell}
          y={row * cell}
          width={cell + 0.05}
          height={cell + 0.05}
          style={{ fill: SCENE_COLORS[index] }}
        />,
      );
    }
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="rounded-md ring-1 ring-black/10 dark:ring-white/20"
      aria-hidden="true"
    >
      {rects}
    </svg>
  );
}

export function PrintSizeIllustration(): JSX.Element {
  const { t } = useI18n();
  return (
    <figure
      className="mt-3 rounded-xl border border-slate-200/80 bg-slate-100/60 px-3 py-3 dark:border-slate-700/60 dark:bg-slate-900/50"
      data-testid="tutorial-illustration-print-size"
    >
      <div className="flex items-end justify-center gap-5">
        <div className="flex flex-col items-center gap-1.5">
          <SampledScene cells={8} size={44} />
          <span className="text-[11px] text-slate-600 dark:text-slate-300">{t("tutorial_size_small")}</span>
        </div>
        <span aria-hidden="true" className="pb-8 text-slate-400">→</span>
        <div className="flex flex-col items-center gap-1.5">
          <SampledScene cells={28} size={96} />
          <span className="text-[11px] text-slate-600 dark:text-slate-300">{t("tutorial_size_large")}</span>
        </div>
      </div>
      <figcaption className="mt-2 text-center text-xs leading-5 text-slate-500 dark:text-slate-400">
        {t("tutorial_size_caption")}
      </figcaption>
    </figure>
  );
}
