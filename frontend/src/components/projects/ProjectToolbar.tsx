import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useI18n } from "../../i18n/context";
import { useOutsideInteraction } from "../../hooks/useOutsideInteraction";
import Button from "../ui/Button";
import { HeaderTooltip } from "../ui/HeaderTooltip";
import { HEADER_MENU_DIVIDER_CLASS, HEADER_MENU_ITEM_CLASS, HEADER_MENU_PANEL_CLASS } from "../ui/headerControls";

interface ProjectToolbarProps {
  name: string;
  dirty: boolean;
  busy: boolean;
  saving: boolean;
  status: string;
  notice: string | null;
  onCenter: () => void;
  onNew: () => void;
  onOpen: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onExport: () => void;
  shareCard?: { onExport: () => void; disabledReason: string | null };
}

const toolbarButtonClass = "ghost-control inline-flex h-8 min-w-0 shrink-0 items-center justify-center gap-2 rounded-lg px-2 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]";

interface MenuItem { label: string; action: () => void; disabled?: boolean; description?: string | null }

function ProjectMenu({ label, iconOnly = false, items }: { label: string; iconOnly?: boolean; items: MenuItem[] }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const close = useCallback(() => setMenuOpen(false), []);
  useOutsideInteraction(root, close, menuOpen);
  useEffect(() => {
    if (menuOpen) menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [menuOpen]);
  const select = (action: () => void) => {
    setMenuOpen(false);
    trigger.current?.focus();
    action();
  };
  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setMenuOpen(false);
      trigger.current?.focus();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = [...(menu.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  };
  return <div ref={root} className="relative">
    <HeaderTooltip label={label} suppressed={menuOpen}>
      <button ref={trigger} type="button" className={`${toolbarButtonClass} ${iconOnly ? "w-8 px-0" : ""}`} aria-label={label} aria-haspopup="menu" aria-expanded={menuOpen} aria-controls={menuOpen ? menuId : undefined} onClick={() => setMenuOpen(value => !value)} onKeyDown={event => { if (event.key === "ArrowDown") { event.preventDefault(); setMenuOpen(true); } }}>
        {iconOnly ? <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></svg> : <>{label}<span aria-hidden="true">⌄</span></>}
      </button>
    </HeaderTooltip>
    {menuOpen && <div ref={menu} id={menuId} role="menu" aria-label={label} onKeyDown={onMenuKeyDown} className={`${HEADER_MENU_PANEL_CLASS} w-64`}>
      {items.map((item, index) => <div key={item.label}>
        {index > 0 && <div className={HEADER_MENU_DIVIDER_CLASS} />}
        <button type="button" role="menuitem" disabled={item.disabled} aria-describedby={item.description ? `${menuId}-${index}` : undefined} className={`${HEADER_MENU_ITEM_CLASS} disabled:cursor-not-allowed disabled:opacity-50`} onClick={() => select(item.action)}>{item.label}</button>
        {item.description && <p id={`${menuId}-${index}`} className="px-3 pb-2 text-xs leading-5 text-[var(--surface-text-muted)]">{item.description}</p>}
      </div>)}
    </div>}
  </div>;
}

export default function ProjectToolbar({ name, dirty, busy, saving, status, notice, onCenter, onNew, onOpen, onSave, onSaveAs, onExport, shareCard }: ProjectToolbarProps) {
  const { t } = useI18n();
  const displayName = name === "Untitled" ? t("project_untitled") : name;
  return <div data-testid="project-bar" className="flex shrink-0 items-center gap-1.5 text-xs">
    <HeaderTooltip label={`${t("project_center")} · ${displayName} · ${status}`}>
      <button type="button" aria-label={`${t("project_center")}: ${displayName} · ${status}`} onClick={onCenter} className={toolbarButtonClass}>
        <svg aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-[var(--surface-text-muted)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
        <span className="hidden max-w-32 truncate lg:inline xl:max-w-44">{displayName}</span>
        {dirty && <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />}
      </button>
    </HeaderTooltip>
    <span aria-hidden="true" className="mx-1 h-4 border-l panel-divider" />
    {notice && <span role="status" className="hidden max-w-36 truncate text-[var(--surface-text-muted)] 2xl:inline">{notice}</span>}
    <Button label={t("project_open_short")} size="sm" variant="ghost" onClick={onOpen} disabled={busy} />
    <Button label={t("project_save")} size="sm" variant="primary" onClick={onSave} disabled={busy} loading={saving} />
    <ProjectMenu label={t("project_export")} items={[
      { label: t("project_export_bundle"), action: onExport, disabled: busy, description: t("project_export_bundle_detail") },
      ...(shareCard ? [{ label: t("recipe_export_btn"), action: shareCard.onExport, disabled: busy || Boolean(shareCard.disabledReason), description: shareCard.disabledReason ?? t("project_export_card_detail") }] : []),
    ]} />
    <ProjectMenu label={t("project_more")} iconOnly items={[
      { label: t("project_new"), action: onNew, disabled: busy },
      { label: t("project_save_as"), action: onSaveAs, disabled: busy },
    ]} />
  </div>;
}
