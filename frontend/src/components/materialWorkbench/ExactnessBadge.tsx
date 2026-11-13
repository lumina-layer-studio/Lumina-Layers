import { useI18n } from "../../i18n/context";

interface ExactnessBadgeProps {
  isExact: boolean;
  testId?: string;
}

/**
 * Candidate completeness badge, separate from the match-error estimate.
 * 候选完整性标记，与匹配误差估计分开说明。
 */
export default function ExactnessBadge({ isExact, testId }: ExactnessBadgeProps) {
  const { t } = useI18n();
  return (
    <span
      data-testid={testId}
      title={t(isExact ? "material_gamut_exact_tooltip" : "material_gamut_estimated_tooltip")}
      className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
        isExact
          ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300"
          : "bg-amber-500/12 text-amber-700 dark:text-amber-300"
      }`}
    >
      {t(isExact ? "material_gamut_exact_badge" : "material_gamut_estimated_badge")}
    </span>
  );
}
