import type { MaterialGamutAccuracy } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { deltaEQualityKey } from "../colorQuickReplace/recipeSuggestionUtils";
import { groupHeaderClass, wellPadClass } from "../ui/panelPrimitives";
import LightnessRangeStrip from "./LightnessRangeStrip";
import { formatDeltaE } from "./format";

/**
 * Average error of the closest printable color per color group, with a
 * plain-word verdict, plus the printable lightness strip.
 * 逐颜色组的最接近可打印颜色平均色差（附文字判断），以及可打印亮度条。
 */
export default function MatchAccuracyList({ accuracy }: { accuracy: MaterialGamutAccuracy }) {
  const { t } = useI18n();
  const { darkest_lightness: darkest, lightest_lightness: lightest } = accuracy;

  return (
    <div data-testid="material-gamut-accuracy" className="flex flex-col gap-3">
      <div>
        <p className={groupHeaderClass}>{t("material_gamut_accuracy_header")}</p>
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {t("material_gamut_accuracy_description")}
        </p>
      </div>
      <dl className={`${wellPadClass} grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-5`}>
        {accuracy.groups.map((entry) => (
          <div key={entry.group} data-testid="material-gamut-accuracy-group" className="flex min-w-0 flex-col">
            <dt className="truncate text-xs text-slate-600 dark:text-slate-300">
              {t(`material_gamut_group_${entry.group}`)}
            </dt>
            {entry.mean_delta_e == null ? (
              <dd className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("material_gamut_no_printable_colors")}
              </dd>
            ) : (
              <dd className="mt-0.5 flex flex-col">
                <span className="text-xl font-semibold tabular-nums text-slate-900 dark:text-slate-50">
                  {formatDeltaE(entry.mean_delta_e)}
                  <span className="ml-1 text-xs font-normal text-slate-500 dark:text-slate-400">
                    {t("material_gamut_delta_e_unit")}
                  </span>
                </span>
                <span className="text-xs text-slate-500 dark:text-slate-400">{t(deltaEQualityKey(entry.mean_delta_e))}</span>
              </dd>
            )}
          </div>
        ))}
      </dl>
      {darkest != null && lightest != null ? <LightnessRangeStrip darkest={darkest} lightest={lightest} /> : null}
    </div>
  );
}
