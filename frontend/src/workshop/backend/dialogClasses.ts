import { cardPadClass, cx } from "../../components/ui/panelPrimitives";

/**
 * Backend dialogs take their shell from the shared card primitive: the one
 * bordered layer, 16px radius, and the card shadow token (DESIGN.md).
 * 后端弹窗外壳沿用共享卡片原语：唯一一层边框、16px 圆角与卡片阴影令牌。
 */
export const backendDialogShellClass = cx(
  cardPadClass,
  "panel-default-surface max-h-[90vh] w-full overflow-y-auto",
);

/** Dialog title level: 15px semibold. 弹窗标题层级。 */
export const backendDialogTitleClass =
  "text-[15px] font-semibold text-slate-900 dark:text-slate-50";
