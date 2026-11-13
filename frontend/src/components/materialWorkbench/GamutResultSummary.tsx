import type { MaterialGamutCoverageResponse, MaterialGamutSource } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import { cardDividerClass, groupHeaderClass, wellPadClass } from "../ui/panelPrimitives";
import ExactnessBadge from "./ExactnessBadge";
import MatchAccuracyList from "./MatchAccuracyList";
import { formatCandidateCount, formatPercent } from "./format";

function sourceText(source: MaterialGamutSource): string {
  const budget = source.candidate_budget != null ? formatCandidateCount(source.candidate_budget) : "";
  return tRuntime(`material_gamut_source_${source.kind}`, { budget });
}

interface CoverageBarProps {
  label: string;
  percent: number;
  testId?: string;
}

function CoverageBar({ label, percent, testId }: CoverageBarProps) {
  return (
    <div data-testid={testId} className="flex items-center gap-3 text-xs">
      <span className="w-20 shrink-0 text-slate-600 dark:text-slate-300">{label}</span>
      <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-800">
        <div
          className="h-full rounded-full bg-blue-500 dark:bg-blue-400"
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      <span className="w-12 shrink-0 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {formatPercent(percent)}%
      </span>
    </div>
  );
}

/**
 * Headline coverage, color source, match accuracy, and per-layer-cap bars.
 * 主覆盖率、颜色来源、匹配精度与逐层数上限覆盖条。
 */
export default function GamutResultSummary({ result }: { result: MaterialGamutCoverageResponse }) {
  const { t } = useI18n();
  const { coverage, source } = result;

  return (
    <div data-testid="material-gamut-summary" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className={groupHeaderClass}>{t("material_gamut_result_label")}</p>
          <p
            data-testid="material-gamut-percent"
            className="mt-1 text-4xl font-semibold tabular-nums tracking-tight text-slate-900 dark:text-slate-50"
          >
            {formatPercent(coverage.percent)}%
          </p>
        </div>
        <ExactnessBadge isExact={source.is_complete} testId="material-gamut-exactness" />
      </div>

      <div className={`${wellPadClass} flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300`}>
        <span>
          {tRuntime("material_gamut_result_detail", {
            reached: coverage.reached_cell_count.toLocaleString(),
            total: coverage.reference_cell_count.toLocaleString(),
            cell: result.cell_size_delta_e,
            colors: result.color_count.toLocaleString(),
          })}
        </span>
        <span data-testid="material-gamut-source">{sourceText(source)}</span>
      </div>

      <div className={`${cardDividerClass} pt-4`}>
        <MatchAccuracyList accuracy={result.accuracy} />
      </div>

      {result.layer_cap_coverage.length > 0 ? (
        <div className={`${cardDividerClass} flex flex-col gap-2 pt-4`}>
          <div>
            <p className={groupHeaderClass}>{t("material_gamut_layer_caps_header")}</p>
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
              {t("material_gamut_layer_caps_description")}
            </p>
          </div>
          {result.layer_cap_coverage.map((cap) => (
            <CoverageBar
              key={cap.layer_count}
              testId="material-gamut-layer-cap"
              label={tRuntime("material_gamut_layer_cap_label", { count: cap.layer_count })}
              percent={cap.coverage.percent}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
