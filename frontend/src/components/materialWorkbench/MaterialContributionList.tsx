import type {
  MaterialGamutAccuracy,
  MaterialGamutContributionItem,
  MaterialGamutContributionsResponse,
  MaterialGamutLossGroup,
} from "../../api/types";
import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import { StatusBanner, groupHeaderClass } from "../ui/panelPrimitives";
import ExactnessBadge from "./ExactnessBadge";
import { formatDeltaE, formatLightness, formatPercent } from "./format";

const LOSS_GROUPS: readonly MaterialGamutLossGroup[] = ["neutral", "dark", "skin", "vivid"];

/**
 * Loss shading steps, weakest first. A change below the first step is not
 * visible and renders as a dash; each later step darkens the cell.
 */
const DELTA_E_STEPS = [1, 3, 8] as const;
const LIGHTNESS_STEPS = [1, 5, 15] as const;
/** Coverage is secondary: shown without shading, and only when it moves. */
const VISIBLE_COVERAGE_DROP = 0.5;
const SHADE_CLASSES = [
  "bg-blue-500/10 text-slate-800 dark:bg-blue-400/15 dark:text-slate-100",
  "bg-blue-500/25 text-slate-900 dark:bg-blue-400/30 dark:text-slate-50",
  "bg-blue-500/45 font-semibold text-slate-900 dark:bg-blue-400/50 dark:text-white",
] as const;

function meanFor(accuracy: MaterialGamutAccuracy, group: string): number | null {
  return accuracy.groups.find((entry) => entry.group === group)?.mean_delta_e ?? null;
}

/** Sort key: largest accuracy loss first; "nothing printable" ranks highest. */
function lossRank(item: MaterialGamutContributionItem): number {
  return item.largest_loss_delta_e ?? Number.POSITIVE_INFINITY;
}

function shadeIndex(change: number, steps: readonly number[]): number {
  let index = -1;
  steps.forEach((step, position) => {
    if (change >= step) index = position;
  });
  return index;
}

interface LossCellProps {
  change: number | null;
  steps: readonly number[];
  text: string;
  noChange: string;
}

function LossCell({ change, steps, text, noChange }: LossCellProps) {
  const shade = change == null ? -1 : shadeIndex(change, steps);
  return (
    <td className="px-1 py-1 text-right">
      {shade < 0 ? (
        <span className="inline-block px-2 py-0.5 text-slate-400 dark:text-slate-500">{noChange}</span>
      ) : (
        <span className={`inline-block min-w-[3.25rem] rounded-md px-2 py-0.5 ${SHADE_CLASSES[shade]}`}>{text}</span>
      )}
    </td>
  );
}

interface MaterialContributionListProps {
  data: MaterialGamutContributionsResponse | null;
  loading: boolean;
  error: string | null;
}

/**
 * Material × color-group table: how much worse each group gets without a
 * material, with darker cells for bigger losses; baseline values in row one.
 * 耗材 × 颜色组表格：去掉某耗材后各组变差多少，损失越大底色越深；首行为基线值。
 */
export default function MaterialContributionList({ data, loading, error }: MaterialContributionListProps) {
  const { t } = useI18n();
  const items = data ? [...data.items].sort((a, b) => lossRank(b) - lossRank(a)) : [];
  const noChange = t("material_gamut_contrib_no_change");
  const baseline = data?.baseline_accuracy;
  const headerCell = "px-3 pb-2 text-right font-medium text-slate-500 dark:text-slate-400";

  return (
    <div data-testid="material-gamut-contributions" className="flex flex-col gap-3">
      <div>
        <div className="flex items-center justify-between gap-3">
          <p className={groupHeaderClass}>{t("material_gamut_contrib_header")}</p>
          {data ? <ExactnessBadge isExact={data.is_complete} testId="material-gamut-contrib-exactness" /> : null}
        </div>
        {data ? (
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {tRuntime("material_gamut_contrib_description", { layers: data.layer_count })}
          </p>
        ) : null}
      </div>
      {loading ? <StatusBanner tone="info">{t("material_gamut_contrib_loading")}</StatusBanner> : null}
      {error ? <StatusBanner tone="error">{error}</StatusBanner> : null}
      {data && baseline ? (
        <div className="overflow-x-auto">
          <table className="text-xs tabular-nums">
            <thead>
              <tr>
                <th className="pb-2 pr-4 text-left font-medium text-slate-500 dark:text-slate-400">
                  {t("material_gamut_contrib_col_material")}
                </th>
                {LOSS_GROUPS.map((group) => (
                  <th key={group} className={headerCell} title={t(`material_gamut_group_${group}`)}>
                    {t(`material_gamut_group_short_${group}`)}
                  </th>
                ))}
                <th className={headerCell}>{t("material_gamut_contrib_col_darkest")}</th>
                <th className={headerCell}>{t("material_gamut_contrib_col_coverage")}</th>
              </tr>
            </thead>
            <tbody>
              <tr data-testid="material-gamut-contribution-baseline" className="panel-divider border-b">
                <td className="py-1.5 pr-4 text-slate-600 dark:text-slate-300">{t("material_gamut_contrib_baseline")}</td>
                {LOSS_GROUPS.map((group) => {
                  const value = meanFor(baseline, group);
                  return (
                    <td key={group} className="px-3 py-1.5 text-right text-slate-600 dark:text-slate-300">
                      {value == null ? noChange : formatDeltaE(value)}
                    </td>
                  );
                })}
                <td className="px-3 py-1.5 text-right text-slate-600 dark:text-slate-300">
                  {baseline.darkest_lightness == null ? noChange : formatLightness(baseline.darkest_lightness)}
                </td>
                <td className="px-3 py-1.5 text-right text-slate-600 dark:text-slate-300">
                  {formatPercent(data.baseline.percent)}%
                </td>
              </tr>
              {items.map((item) => {
                const without = item.accuracy_without;
                const darkBefore = baseline.darkest_lightness;
                const darkAfter = without.darkest_lightness;
                const darkChange = darkBefore != null && darkAfter != null ? darkAfter - darkBefore : null;
                const coverageDrop = Math.max(0, item.drop_percent);
                return (
                  <tr key={item.directory_name} data-testid="material-gamut-contribution-item">
                    <td className="max-w-[14rem] truncate py-1 pr-4 text-sm text-slate-800 dark:text-slate-100">
                      {item.material_name}
                    </td>
                    {LOSS_GROUPS.map((group) => {
                      const before = meanFor(baseline, group);
                      const after = meanFor(without, group);
                      const change = before != null && after != null ? after - before : null;
                      return (
                        <LossCell
                          key={group}
                          change={change}
                          steps={DELTA_E_STEPS}
                          text={change == null ? noChange : `+${formatDeltaE(change)}`}
                          noChange={noChange}
                        />
                      );
                    })}
                    <LossCell
                      change={darkChange}
                      steps={LIGHTNESS_STEPS}
                      text={darkChange == null ? noChange : `+${formatLightness(darkChange)}`}
                      noChange={noChange}
                    />
                    <td className="px-3 py-1 text-right text-slate-600 dark:text-slate-300">
                      {coverageDrop >= VISIBLE_COVERAGE_DROP ? (
                        `−${formatPercent(coverageDrop)}`
                      ) : (
                        <span className="text-slate-400 dark:text-slate-500">{noChange}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
