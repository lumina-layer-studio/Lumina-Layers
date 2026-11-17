import { useId, useState } from "react";
import { motion } from "framer-motion";
import { useI18n } from "../../i18n/context";
import { dismissMaterialGuide, isMaterialGuideDismissed, requestMaterialTrial } from "../../stores/materialGuideStore";
import Button from "./Button";
import CloseButton from "./CloseButton";
import DisclosureChevron from "./DisclosureChevron";
import { wellClass } from "./panelPrimitives";

/** One-line invitation; compact keeps a permanent, explicitly opened help entry. */
export default function MaterialArchiveGuide({ compact = false, onFind = requestMaterialTrial }: {
  compact?: boolean;
  onFind?: () => void;
}) {
  const { t } = useI18n();
  const id = useId();
  const [dismissed, setDismissed] = useState(isMaterialGuideDismissed);
  const [opened, setOpened] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [closing, setClosing] = useState(false);
  const dismiss = () => {
    dismissMaterialGuide();
    setDismissed(true);
  };
  if (!opened) {
    if (dismissed && !compact) return null;
    return <div className="flex min-w-0 items-center justify-between gap-2">
      <Button label={t(compact ? "material_guide_learn" : "material_guide_hint")} size="sm" variant="ghost"
        className="-ml-2.5" onClick={() => { dismiss(); setOpened(true); }} />
      {!compact && <CloseButton label={t("material_guide_dismiss")} onClick={dismiss} />}
    </div>;
  }
  return <motion.section aria-label={t("material_guide_title")} data-testid="material-archive-guide"
    initial={false} animate={{ opacity: closing ? 0 : 1, height: closing ? 0 : "auto" }}
    transition={{ opacity: { duration: 0.2 }, height: { duration: 0.25, delay: closing ? 0.2 : 0 } }}
    onAnimationComplete={() => { if (closing) { setOpened(false); setClosing(false); setExpanded(false); } }}
    className="min-w-0 overflow-hidden">
    <div className={`${wellClass} p-4`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{t("material_guide_title")}</h3>
          <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{t("material_guide_body")}</p>
        </div>
        <CloseButton label={t("material_guide_dismiss")} onClick={() => {
          dismiss();
          setClosing(true);
        }} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button label={t("material_guide_find")} size="sm" variant="primary" onClick={onFind} />
        <button type="button" aria-expanded={expanded} aria-controls={id}
          onClick={() => setExpanded(!expanded)}
          className="ghost-control inline-flex min-h-8 items-center gap-1 rounded-lg px-2.5 text-xs font-medium">
          <DisclosureChevron expanded={expanded} />{t("material_guide_cards")}
        </button>
      </div>
      {expanded && <div id={id} className="mt-3 max-w-2xl space-y-2 border-t panel-divider pt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
        <p>{t("material_guide_explanation")}</p>
        <p>{t("material_guide_example")}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">{t("material_guide_conditions")}</p>
      </div>}
    </div>
  </motion.section>;
}
