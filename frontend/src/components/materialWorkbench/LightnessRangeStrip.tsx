import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import { formatLightness } from "./format";

interface LightnessRangeStripProps {
  darkest: number;
  lightest: number;
}

/**
 * Data color, not UI chrome: the strip is the L* axis itself, from black (0)
 * to white (100), so it must stay the same in light and dark themes.
 */
const LIGHTNESS_AXIS_GRADIENT = "linear-gradient(to right, rgb(0 0 0), rgb(255 255 255))";

const clampPercent = (lightness: number) => Math.min(100, Math.max(0, lightness));

/**
 * Black-to-white strip with the unprintable ends washed out.
 * 黑到白的亮度条，无法打印的两端被淡化。
 */
export default function LightnessRangeStrip({ darkest, lightest }: LightnessRangeStripProps) {
  const { t } = useI18n();
  const low = clampPercent(darkest);
  const high = clampPercent(lightest);

  return (
    <div data-testid="material-gamut-lightness-range" className="flex max-w-md flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-slate-600 dark:text-slate-300">{t("material_gamut_lightness_label")}</span>
        <span className="tabular-nums text-slate-800 dark:text-slate-100">
          {tRuntime("material_gamut_lightness_range", {
            darkest: formatLightness(darkest),
            lightest: formatLightness(lightest),
          })}
        </span>
      </div>
      <div className="relative h-3 overflow-hidden rounded-full" style={{ background: LIGHTNESS_AXIS_GRADIENT }}>
        <div
          className="absolute inset-y-0 left-0 bg-slate-100/85 dark:bg-slate-900/85"
          style={{ width: `${low}%` }}
        />
        <div
          className="absolute inset-y-0 right-0 bg-slate-100/85 dark:bg-slate-900/85"
          style={{ width: `${100 - high}%` }}
        />
        <div
          className="absolute inset-y-0 rounded-full ring-1 ring-slate-400/70 dark:ring-slate-500/70"
          style={{ left: `${low}%`, width: `${Math.max(0, high - low)}%` }}
        />
      </div>
      <div className="flex justify-between text-[11px] text-slate-500 dark:text-slate-400">
        <span>{t("material_gamut_lightness_black")}</span>
        <span>{t("material_gamut_lightness_white")}</span>
      </div>
    </div>
  );
}
