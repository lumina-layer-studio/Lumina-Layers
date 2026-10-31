import CloseButton from "./CloseButton";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  closestCenter,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import Button from "./Button";
import CustomRecipeSidePanel, {
  type CustomRecipeSidePanelPaletteEntry,
} from "./CustomRecipeSidePanel";
import Dropdown from "./Dropdown";
import { useI18n } from "../../i18n/context";
import { workstationInputClass } from "./panelPrimitives";
import {
  fetchRegionRecipe,
  predictCustomRecipe,
} from "../../api/converter";
import { apiErrorToVisibleMessage } from "../../api/client";
import type {
  PredictFailureKind,
  RecipeHistoryItem,
  RecipeOverrideApplyResponse,
  RecipePredictResponse,
  VirtualMaterial,
} from "../../api/types";
import { useConverterStore } from "../../stores/converter";
import {
  applyRecipePattern,
  buildPaletteHint,
  validateRecipePattern,
} from "../../utils/recipePattern";
import { formatDisplayLayerLabelParts } from "../../utils/layerLabels";

interface PaletteOption {
  color: string;
  material?: string | null;
  /** 无井号的 hex，用于该通道的每层 swatch；为空则 swatch 用灰色兜底。 */
  hex?: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasCustomRecipeValidationPath(error: unknown): boolean {
  const response = isRecord(error) && isRecord(error.response) ? error.response : null;
  const data = isRecord(response?.data) ? response.data : null;
  const detail = data?.detail;
  if (!Array.isArray(detail)) {
    return false;
  }
  return detail.some((item) => {
    const loc = isRecord(item) ? item.loc : null;
    if (!Array.isArray(loc)) {
      return false;
    }
    const parts = loc.map((part) => String(part));
    return (
      parts.length === 2 &&
        parts[0] === "body" &&
        (parts[1] === "recipe" || parts[1] === "region_ids")
    ) || (
      parts.length === 4 &&
        parts[0] === "body" &&
        parts[1] === "virtual_materials" &&
        parts[3] === "hex"
    );
  });
}

function resolveCustomRecipeError(error: unknown, fallback: string): string {
  if (hasCustomRecipeValidationPath(error)) {
    return fallback;
  }
  return apiErrorToVisibleMessage(error, fallback);
}

interface Props {
  open: boolean;
  sessionId: string;
  palette: PaletteOption[];
  regionIds: string[];
  colorLayers: number;
  layerHeightMm: number;
  layerOrder: string;
  baseChannelIdx: number;
  /** 当前活跃区域的颜色（带 # 前缀），用于对话框顶部定位 swatch。 */
  currentRegionColorHex?: string | null;
  onClose: () => void;
  /**
   * Fires after a successful apply. ``virtualMaterials`` carries the
   * user-declared non-native primaries translated by
   * ``buildApiRecipePayload``; callers must persist this list alongside the
   * recipe so ``/generate`` can rebuild the extended palette — without it
   * the worker pipeline collapses virtual-index pixels back onto the LUT's
   * native channels (缺失 mesh / 3MF 丢对象 / 看起来像透明失效).
   *
   * apply 成功后触发。``virtualMaterials`` 是 ``buildApiRecipePayload`` 把
   * 用户挑选的非原生原色归并得到的列表；调用方必须把它和 recipe 一并持久化，
   * 否则 ``/generate`` 无法重建扩展调色板，worker 会把虚拟索引像素坍缩回 LUT
   * 原生通道（表现为 mesh 缺失 / 3MF 漏对象 / 透明失效）。
   */
  onApplied?: (
    response: RecipeOverrideApplyResponse,
    recipe: number[],
    colorLayers: number,
    layerHeightMm: number,
    virtualMaterials: VirtualMaterial[],
  ) => void;
}

interface RecipeRow {
  id: string;
  displayIdx: number;
}

function buildDefaultRecipe(
  length: number,
  displayPalette: DisplayPaletteEntry[],
  baseChannelIdx: number,
): number[] {
  // Default each layer to the displayPalette entry whose native LUT channel
  // matches the bundle's base channel (typically White). Falls back to the
  // first primary (White) when no native match exists.
  // 默认每层使用对应 LUT base 通道（通常是 White）的 displayPalette 条目；
  // 找不到原生匹配时回退到首位原色（White）。
  const defaultIdx = displayPalette.findIndex(
    (entry) => entry.native && entry.lutIndex === baseChannelIdx,
  );
  const safeIdx = defaultIdx >= 0 ? defaultIdx : 0;
  return Array.from({ length }, () => safeIdx);
}

function makeRecipeRows(
  recipe: number[],
  nextId: () => string,
): RecipeRow[] {
  return recipe.map((displayIdx) => ({
    id: nextId(),
    displayIdx,
  }));
}

function classifyPredictError(message: string): PredictFailureKind {
  const lower = message.toLowerCase();
  if (
    lower.includes("no predictive") ||
    lower.includes("forward") ||
    lower.includes("package-only") ||
    lower.includes("not present in the runtime")
  ) {
    return "no_forward_model";
  }
  return "unknown";
}

function toHexByte(value: number): string {
  const normalized = Math.max(0, Math.min(255, Math.round(value)));
  return normalized.toString(16).padStart(2, "0").toUpperCase();
}

/**
 * Canonical hex for the standard primary / secondary channel names used by
 * multi-material palettes. Applied as the *preferred* swatch colour so that
 * every layer picker visually reads like the classic CMYK + RGB swatch wall
 * (青品黄黑 / 白红绿蓝) regardless of what the underlying LUT stores for
 * that channel — only falling back to the LUT-supplied hex when the channel
 * name is unrecognised (e.g. "Sand", "Bone").
 *
 * 多材料调色板的标准通道名对应的规范色：作为首选的层 swatch 颜色，
 * 保证图标只看色即可辨认标准原色，不管 LUT 里记的是什么具体色样。
 */
const CANONICAL_PRIMARY_HEX: Record<string, string> = {
  cyan: "#00B7EB",
  magenta: "#E6007E",
  yellow: "#FFD400",
  black: "#111111",
  white: "#F5F5F5",
  red: "#E53935",
  green: "#43A047",
  blue: "#1E88E5",
  orange: "#FB8C00",
  purple: "#8E24AA",
  pink: "#EC407A",
  gray: "#9E9E9E",
  grey: "#9E9E9E",
  brown: "#795548",
};

/** Canonical primary order shown in the per-layer dropdown. 下拉固定显示的 8 原色顺序。 */
const DISPLAY_PRIMARY_ORDER = [
  "White",
  "Black",
  "Cyan",
  "Magenta",
  "Yellow",
  "Red",
  "Green",
  "Blue",
] as const;

const PRIMARY_NAME_ALIASES: Record<string, string[]> = {
  white: ["white", "w", "白", "白色"],
  black: ["black", "k", "黑", "黑色"],
  cyan: ["cyan", "c", "青", "青色", "天蓝", "浅蓝", "湖蓝"],
  magenta: ["magenta", "m", "品红", "洋红", "玫红", "紫红"],
  yellow: ["yellow", "y", "黄", "黄色"],
  red: ["red", "r", "红", "红色", "大红"],
  green: ["green", "g", "绿", "绿色"],
  blue: ["blue", "蓝", "蓝色", "克莱因蓝"],
  orange: ["orange", "橙", "橙色"],
  purple: ["purple", "紫", "紫色"],
  pink: ["pink", "粉", "粉色"],
  gray: ["gray", "grey", "灰", "灰色"],
  brown: ["brown", "棕", "棕色", "褐", "褐色"],
};

const PRIMARY_ALIAS_MATCH_ORDER = [
  "white",
  "black",
  "cyan",
  "magenta",
  "yellow",
  "red",
  "green",
  "blue",
  "orange",
  "purple",
  "pink",
  "gray",
  "brown",
] as const;

interface DisplayPaletteEntry {
  /** Canonical primary name, e.g. "Cyan". 通道规范名。 */
  color: string;
  /** Swatch hex (with leading #). 色块规范 hex。 */
  hex: string;
  /** Translated LUT channel index used for backend calls. 真正送后端的 LUT 通道索引。 */
  lutIndex: number;
  /** Whether the LUT natively carries this primary. LUT 是否原生支持该原色。 */
  native: boolean;
  /** Material tag to show in labels when LUT-sourced. 标签里用于提示的材料名。 */
  material?: string | null;
}

function hexToRgbTriple(hex: string): [number, number, number] | null {
  const raw = hex.replace("#", "").trim();
  if (raw.length !== 6) return null;
  const value = Number.parseInt(raw, 16);
  if (!Number.isFinite(value)) return null;
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

function normalizeHexValue(hex: string | null | undefined): string | null {
  if (!hex) return null;
  const raw = hex.replace("#", "").trim();
  return /^[0-9a-fA-F]{6}$/.test(raw) ? `#${raw.toUpperCase()}` : null;
}

function matchesAlias(text: string, alias: string): boolean {
  if (/^[a-z0-9]+$/i.test(alias)) {
    return new RegExp(`(^|[^a-z0-9])${alias}([^a-z0-9]|$)`, "i").test(text);
  }
  return text.includes(alias);
}

function nearestCanonicalPrimaryKey(hex: string | null | undefined): string | null {
  const normalized = normalizeHexValue(hex);
  if (!normalized) return null;
  const rgb = hexToRgbTriple(normalized);
  if (!rgb) return null;
  let bestKey: string | null = null;
  let bestDist = Number.POSITIVE_INFINITY;
  for (const key of PRIMARY_ALIAS_MATCH_ORDER) {
    const candidateHex = CANONICAL_PRIMARY_HEX[key];
    if (!candidateHex) continue;
    const candidate = hexToRgbTriple(candidateHex);
    if (!candidate) continue;
    const dr = rgb[0] - candidate[0];
    const dg = rgb[1] - candidate[1];
    const db = rgb[2] - candidate[2];
    const dist = dr * dr + dg * dg + db * db;
    if (dist < bestDist) {
      bestDist = dist;
      bestKey = key;
    }
  }
  return bestDist <= 6400 ? bestKey : null;
}

function inferCanonicalPrimaryKey(entry: PaletteOption | null | undefined): string | null {
  if (!entry) return null;
  const text = `${entry.color ?? ""} ${entry.material ?? ""}`.toLowerCase();
  for (const key of PRIMARY_ALIAS_MATCH_ORDER) {
    const aliases = PRIMARY_NAME_ALIASES[key] ?? [];
    if (aliases.some((alias) => matchesAlias(text, alias.toLowerCase()))) {
      return key;
    }
  }
  return nearestCanonicalPrimaryKey(entry.hex);
}

function findNativePrimaryIdx(
  lutPalette: PaletteOption[],
  primaryName: string,
  consumedLutIdx: Set<number>,
): number {
  const primaryKey = primaryName.toLowerCase();
  return lutPalette.findIndex(
    (entry, idx) =>
      !consumedLutIdx.has(idx) && inferCanonicalPrimaryKey(entry) === primaryKey,
  );
}

function inferBaseChannelIdx(
  lutPalette: PaletteOption[],
  baseChannelIdx: number,
  sourceVersion: string,
): number {
  if (sourceVersion === "material") {
    const whiteIdx = lutPalette.findIndex(
      (entry) => inferCanonicalPrimaryKey(entry) === "white",
    );
    if (whiteIdx >= 0) return whiteIdx;
  }
  if (lutPalette.length === 0) return Math.max(0, baseChannelIdx);
  return Math.max(0, Math.min(baseChannelIdx, lutPalette.length - 1));
}

function nearestLutChannelIdx(
  lutPalette: PaletteOption[],
  targetHex: string,
  fallbackIdx: number,
): number {
  if (lutPalette.length === 0) return 0;
  const target = hexToRgbTriple(targetHex);
  if (!target) {
    return Math.max(0, Math.min(fallbackIdx, lutPalette.length - 1));
  }
  let bestIdx = Math.max(0, Math.min(fallbackIdx, lutPalette.length - 1));
  let bestDist = Number.POSITIVE_INFINITY;
  for (let i = 0; i < lutPalette.length; i += 1) {
    const entry = lutPalette[i];
    // Prefer the canonical primary of the LUT channel name when resolving
    // distances; falls through to the LUT-stored hex_color otherwise.
    const inferredKey = inferCanonicalPrimaryKey(entry);
    const candidateHex =
      (inferredKey ? CANONICAL_PRIMARY_HEX[inferredKey] : null) ??
      normalizeHexValue(entry?.hex);
    if (!candidateHex) continue;
    const rgb = hexToRgbTriple(candidateHex);
    if (!rgb) continue;
    const dr = rgb[0] - target[0];
    const dg = rgb[1] - target[1];
    const db = rgb[2] - target[2];
    const dist = dr * dr + dg * dg + db * db;
    if (dist < bestDist) {
      bestDist = dist;
      bestIdx = i;
    }
  }
  return bestIdx;
}

/**
 * Build the 8-canonical-primary display palette shown in the per-layer
 * dropdown. Every primary is selectable regardless of what the underlying LUT
 * carries: primaries the LUT lacks are mapped to the nearest LUT channel by
 * RGB distance so the apply request stays in valid LUT-channel indices. Any
 * additional LUT channels (e.g. a 5th material) are appended after the eight
 * primaries so no LUT-native material gets hidden.
 *
 * 构造下拉固定显示的 8 原色 display palette。所有原色都可选，即使 LUT 没有；
 * LUT 缺的原色按 RGB 距离映射到最接近的 LUT 通道，保证送后端的仍是合法的
 * LUT 通道索引。LUT 里多出来的额外通道（例如第 5 种材料）会追加在 8 原色之后，
 * 避免屏蔽任何原生材料。
 */
function buildDisplayPalette(
  lutPalette: PaletteOption[],
  baseChannelIdx: number,
  sourceVersion: string,
): DisplayPaletteEntry[] {
  // 耗材档案模式下直接按原始顺序显示，不做 8 原色归类，避免名称重复和归类错误。
  // In material-archive mode, show materials in original order without
  // canonical-primary grouping to prevent duplicates and misclassification.
  if (sourceVersion === "material") {
    return lutPalette.map((entry, lutIdx) => {
      const name = (entry?.color ?? "").trim() || `Channel ${lutIdx + 1}`;
      const hex = normalizeHexValue(entry.hex) ?? "#808080";
      return {
        color: name,
        hex,
        lutIndex: lutIdx,
        native: true,
        material: entry.material ?? null,
      };
    });
  }

  const entries: DisplayPaletteEntry[] = [];
  const consumedLutIdx = new Set<number>();
  for (const name of DISPLAY_PRIMARY_ORDER) {
    const canonicalHex = CANONICAL_PRIMARY_HEX[name.toLowerCase()];
    const nativeIdx = findNativePrimaryIdx(lutPalette, name, consumedLutIdx);
    if (nativeIdx >= 0) {
      consumedLutIdx.add(nativeIdx);
      entries.push({
        color: name,
        hex: canonicalHex,
        lutIndex: nativeIdx,
        native: true,
        material: lutPalette[nativeIdx]?.material ?? null,
      });
    } else {
      const lutIndex = nearestLutChannelIdx(
        lutPalette,
        canonicalHex,
        baseChannelIdx,
      );
      entries.push({
        color: name,
        hex: canonicalHex,
        lutIndex,
        native: false,
        material: lutPalette[lutIndex]?.material ?? null,
      });
    }
  }
  // Keep any additional LUT channel not covered by the primaries so custom
  // bundles with exotic materials (e.g. "Gold", "Wood") remain reachable.
  lutPalette.forEach((entry, lutIdx) => {
    if (consumedLutIdx.has(lutIdx)) return;
    const name = (entry?.color ?? "").trim();
    if (!name) return;
    const canonicalKey = name.toLowerCase();
    if (
      entries.some(
        (existing) =>
          existing.native &&
          existing.color.toLowerCase() === canonicalKey,
      )
    ) {
      return;
    }
    const hex =
      CANONICAL_PRIMARY_HEX[inferCanonicalPrimaryKey(entry) ?? canonicalKey] ??
      normalizeHexValue(entry.hex) ??
      "#808080";
    entries.push({
      color: name,
      hex,
      lutIndex: lutIdx,
      native: true,
      material: entry.material ?? null,
    });
  });
  return entries;
}

function useStableByKey<T>(value: T, key: string): T {
  const ref = useRef<{ key: string; value: T } | null>(null);
  if (!ref.current || ref.current.key !== key) {
    ref.current = { key, value };
  }
  return ref.current.value;
}

interface SortableRecipeRowProps {
  row: RecipeRow;
  index: number;
  displayPalette: DisplayPaletteEntry[];
  colorOptions: { label: string; value: string }[];
  layerLabel: { label: string; viewerSuffix: string | null };
  removeLabel: string;
  dragHandleLabel: string;
  canRemove: boolean;
  onChangeLayer: (index: number, displayIdx: number) => void;
  onRemoveLayer: (index: number) => void;
}

function SortableRecipeRow({
  row,
  index,
  displayPalette,
  colorOptions,
  layerLabel,
  removeLabel,
  dragHandleLabel,
  canRemove,
  onChangeLayer,
  onRemoveLayer,
}: SortableRecipeRowProps) {
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: row.id });

  const displayEntry = displayPalette[row.displayIdx];
  const resolvedHex = displayEntry?.hex ?? null;
  const swatchStyle = resolvedHex ? { backgroundColor: resolvedHex } : undefined;
  const swatchFallbackClass = resolvedHex ? "" : "bg-slate-300 dark:bg-slate-600";
  const swatchTitle = displayEntry?.color ?? "";

  return (
    <div
      ref={setNodeRef}
      className={`grid gap-2 rounded-2xl border border-slate-200/80 bg-slate-100/70 p-3 transition-colors dark:border-slate-700/70 dark:bg-slate-900/50 lg:grid-cols-[auto_auto_auto_minmax(0,1fr)_auto] lg:items-center ${
        isDragging
          ? "relative z-10 border-blue-400/70 bg-blue-50/60 opacity-60 shadow-lg dark:border-blue-500/60 dark:bg-blue-500/10"
          : ""
      }`}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
      }}
    >
      <button
        ref={setActivatorNodeRef}
        type="button"
        data-testid={`recipe-layer-drag-handle-${index}`}
        className="touch-none grid h-9 w-5 shrink-0 cursor-grab select-none grid-cols-2 place-content-center gap-x-1 gap-y-1 rounded-lg text-slate-400 transition-colors hover:bg-slate-200/70 hover:text-slate-600 active:cursor-grabbing dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
        aria-label={dragHandleLabel}
        {...attributes}
        {...listeners}
      >
        {Array.from({ length: 6 }).map((_, dotIndex) => (
          <span
            key={dotIndex}
            aria-hidden="true"
            className="h-1 w-1 rounded-full bg-current"
          />
        ))}
      </button>
      <div className="min-w-[4.5rem] text-sm font-medium leading-tight text-slate-700 dark:text-slate-200">
        <span className="block">{layerLabel.label}</span>
        {layerLabel.viewerSuffix && (
          <span className="block text-xs font-normal text-slate-500 dark:text-slate-400">
            {layerLabel.viewerSuffix}
          </span>
        )}
      </div>
      <div
        data-testid={`recipe-layer-swatch-${index}`}
        title={swatchTitle}
        className={`h-6 w-6 rounded-lg border border-slate-300/80 dark:border-slate-600/80 ${swatchFallbackClass}`}
        style={swatchStyle}
      />
      <Dropdown
        label=""
        value={String(row.displayIdx)}
        options={colorOptions}
        onChange={(next) => onChangeLayer(index, Number(next))}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          label={removeLabel}
          variant="secondary"
          size="sm"
          onClick={() => onRemoveLayer(index)}
          disabled={!canRemove}
          tone="danger"
        />
      </div>
    </div>
  );
}

export default function CustomRecipeDialog({
  open,
  sessionId,
  palette,
  regionIds,
  colorLayers,
  layerHeightMm,
  layerOrder,
  baseChannelIdx,
  currentRegionColorHex,
  onClose,
  onApplied,
}: Props) {
  const { t, lang } = useI18n();
  const customRecipeHistory = useConverterStore(
    (state) => state.customRecipeHistory,
  );
  const pushCustomRecipeHistory = useConverterStore(
    (state) => state.pushCustomRecipeHistory,
  );
  const sourceVersion = useConverterStore((state) => state.source_version);
  const selectedLutInfo = useConverterStore((state) => state.selectedLutInfo);
  const dynamicMaterialEnabled = useConverterStore(
    (state) => state.materialDynamicLayerCountEnabled,
  );
  const selectedMaterialDirNames = useConverterStore(
    (state) => state.selectedMaterialDirNames,
  );
  // recipe state stores displayPalette indices (not LUT channel indices) so
  // the dropdown always echoes the exact primary the user clicked, even on a
  // sparse LUT where that primary physically maps to a substitute channel.
  // Translation to LUT indices happens only at network / history boundaries.
  // recipe state 保存的是 displayPalette 索引（不是 LUT 通道索引），保证下拉
  // 永远回显用户实际点击的原色；即使在稀疏 LUT 下用户选的原色物理上会被
  // 代用为别的通道，UI 也不会反漫到代用通道上。翻译到 LUT 索引仅发生在
  // 网络请求和历史条目边界。
  const rowIdCounterRef = useRef(0);
  const nextRecipeRowId = useCallback((): string => {
    rowIdCounterRef.current += 1;
    return `recipe-layer-${rowIdCounterRef.current}`;
  }, []);
  const [recipeRows, setRecipeRows] = useState<RecipeRow[]>(() =>
    makeRecipeRows(Array.from({ length: colorLayers }, () => 0), nextRecipeRowId),
  );
  const recipe = useMemo(
    () => recipeRows.map((row) => row.displayIdx),
    [recipeRows],
  );
  const [pattern, setPattern] = useState("");
  const [prediction, setPrediction] = useState<RecipePredictResponse | null>(
    null,
  );
  // 最近一次预测是否来自 forward model；任何编辑都会清零，写入历史时使用。
  // Tracks whether the latest predict call came from a forward model; any edit
  // invalidates it. Persisted into history entries.
  const [lastPredictFromModel, setLastPredictFromModel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<
    PredictFailureKind | "general"
  >("general");
  const [isPredicting, setIsPredicting] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [pendingUpgrade, setPendingUpgrade] = useState(false);
  // 仅用于客户端撤销：每次配方编辑前把当前 recipe 入栈。
  // Edit-level undo stack (client-side only): snapshot prior to each edit.
  const [editStack, setEditStack] = useState<number[][]>([]);
  // 成功应用后的瞬时提示；非空时在右栏展示「已应用」banner。
  // Non-null after a successful apply; dismissed by next edit or close.
  const [appliedAt, setAppliedAt] = useState<number | null>(null);
  // 最新一次应用的预测 RGB，用来在顶部“当前区域” swatch 即时同步新色，
  // 避免因存储 selectedRegions.colorHex 未刷新而颜色脱同步。
  // Mirrors the predicted RGB of the latest apply so the header swatch stays
  // in sync even before the store's selectedRegions.colorHex is refreshed.
  const [appliedRegionHex, setAppliedRegionHex] = useState<string | null>(
    null,
  );
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const paletteKey = JSON.stringify(
    palette.map((entry) => [
      entry.color,
      entry.material ?? null,
      entry.hex ?? null,
    ]),
  );
  const stablePalette = useStableByKey<PaletteOption[]>(
    palette.map((entry) => ({ ...entry })),
    paletteKey,
  );
  const selectedMaterialDirNamesKey = JSON.stringify(selectedMaterialDirNames);
  const stableSelectedMaterialDirNames = useStableByKey(
    [...selectedMaterialDirNames],
    selectedMaterialDirNamesKey,
  );
  const regionIdsKey = JSON.stringify(regionIds);
  const stableRegionIds = useStableByKey(
    regionIds.filter((regionId) => regionId.length > 0),
    regionIdsKey,
  );
  const initializationKey = `${sessionId}|${regionIdsKey}|${layerOrder}`;
  const initializedKeyRef = useRef<string | null>(null);
  const requestVersionRef = useRef(0);
  const draftVersionRef = useRef(0);
  const draftEditedRef = useRef(false);

  // 8 原色的 display palette：LUT 有就用原生通道，缺的按最近 RGB 映射。
  // 下拉与 pattern 输入都基于此，保证视觉上永远是 8 原色。
  // Display palette: native channel when the LUT has it, nearest-RGB substitute
  // otherwise. Both the dropdown and the pattern input are keyed off this so
  // users always see the 8 canonical primaries regardless of LUT capability.
  // Declared before the open-effect because that effect both consumes
  // ``displayPalette`` in its body AND lists it as a dependency — TypeScript
  // would flag the direct dep-array reference as a TDZ access otherwise.
  // 必须声明在打开 effect 前面：该 effect 的 body 和 deps 都会直接引用
  // ``displayPalette``，TS 会把后置声明判为暂时性死区访问而报错。
  const effectivePalette = useMemo<PaletteOption[]>(() => {
    if (stablePalette.length > 0) {
      return stablePalette;
    }
    if (
      sourceVersion !== "material" ||
      stableSelectedMaterialDirNames.length === 0
    ) {
      return stablePalette;
    }
    return stableSelectedMaterialDirNames.map((dirName) => {
      const normalized = dirName.replace(/\\/g, "/");
      const displayName = normalized.split("/").filter(Boolean).pop() ?? dirName;
      return {
        color: displayName,
        material: dirName,
        hex: null,
      };
    });
  }, [stablePalette, stableSelectedMaterialDirNames, sourceVersion]);

  const resolvedBaseChannelIdx = useMemo(
    () => inferBaseChannelIdx(effectivePalette, baseChannelIdx, sourceVersion),
    [effectivePalette, baseChannelIdx, sourceVersion],
  );

  const displayPalette = useMemo(
    () => buildDisplayPalette(effectivePalette, resolvedBaseChannelIdx, sourceVersion),
    [effectivePalette, resolvedBaseChannelIdx, sourceVersion],
  );

  const markDraftEdited = () => {
    draftEditedRef.current = true;
    draftVersionRef.current += 1;
  };

  useEffect(() => {
    if (!open) {
      initializedKeyRef.current = null;
      requestVersionRef.current += 1;
      draftVersionRef.current += 1;
      draftEditedRef.current = false;
      setPendingUpgrade(false);
      setEditStack([]);
      setAppliedAt(null);
      setAppliedRegionHex(null);
      setActiveDragId(null);
      return;
    }
    if (initializedKeyRef.current === initializationKey) {
      return;
    }
    initializedKeyRef.current = initializationKey;
    requestVersionRef.current += 1;
    draftVersionRef.current += 1;
    const requestVersion = requestVersionRef.current;
    const seedDraftVersion = draftVersionRef.current;
    draftEditedRef.current = false;
    // Seed an immediate synchronous default so the dropdowns never render
    // empty while the region-recipe fetch is in flight. The fetch below
    // replaces this with the region's real matched stack when available.
    // 立即填一个同步默认（全白/base），避免异步请求进行中下拉是空状态；
    // 后端的真实 recipe 回来后会覆盖它。
    const defaultRecipe = buildDefaultRecipe(
      colorLayers,
      displayPalette,
      resolvedBaseChannelIdx,
    );
    setRecipeRows(makeRecipeRows(defaultRecipe, nextRecipeRowId));
    setPattern("");
    setPrediction(null);
    setLastPredictFromModel(false);
    setError(null);
    setErrorKind("general");
    setPendingUpgrade(false);
    setEditStack([]);
    setAppliedAt(null);
    setActiveDragId(null);
    // Region changed → drop the stale “applied” swatch so the prop’s hex wins.
    setAppliedRegionHex(null);

    // Fetch the region's actual per-layer stack so the dropdowns pre-populate
    // with the matched recipe instead of all-White. This is the fix for the
    // user-reported "永远默认全白" regression: before, opening the dialog
    // discarded the pipeline's match and "Apply" silently overwrote a good
    // recipe with White. We fall back to the synchronous default if the
    // session has no session id / no regions / the fetch errors — the dialog
    // must remain usable even when sampling fails.
    // 拉取该区域当前真实的逐层堆叠，预设下拉框，修复用户反馈的"自定义
    // 配方永远默认全白"问题。原先打开对话框就丢掉了 pipeline 已匹配的
    // 配方，Apply 后覆盖成全白。若 session/region 缺失或请求失败，保留
    // 上面的同步默认，保证对话框依旧可用。
    if (!sessionId || stableRegionIds.length === 0) return;
    fetchRegionRecipe({
      session_id: sessionId,
      region_ids: stableRegionIds,
      layer_order: layerOrder,
    })
      .then((response) => {
        if (
          requestVersionRef.current !== requestVersion ||
          initializedKeyRef.current !== initializationKey ||
          draftEditedRef.current ||
          draftVersionRef.current !== seedDraftVersion
        ) {
          return;
        }
        // Multiple selected regions → use the first region's recipe as the
        // dropdown seed. This mirrors the existing "Apply overwrites every
        // selected region with the single recipe the user edited" contract;
        // showing region 0's stack is better than guessing a mode.
        // 多区域选中时用第一个区域的 recipe 做预设，和现有 apply 语义
        // （所有选中区域被同一 recipe 覆盖）一致。
        const firstEntry = response.recipes[0];
        if (!firstEntry || firstEntry.recipe.length === 0) return;
        // Translate LUT channel indices to displayPalette indices so the
        // dropdowns echo the primary the user actually sees (e.g. White on
        // a sparse LUT). Prefer native (LUT channel == primary) entries,
        // fall back to the nearest-RGB substitute, finally to index 0 —
        // matches ``findDisplayIdxForLutIdx`` exactly. Inlined here because
        // that callback is defined after this effect in the component body;
        // keeping the logic local also avoids threading yet another ref
        // through the effect's deps.
        // 把后端返回的 LUT 通道索引翻译成 displayPalette 索引，让下拉显
        // 示用户实际点击的原色；与 ``findDisplayIdxForLutIdx`` 行为对齐。
        // 此处内联，因为 callback 定义在本 effect 之后。
        const nativeMap = new Map<number, number>();
        const anyMap = new Map<number, number>();
        displayPalette.forEach((entry, idx) => {
          if (entry.native && !nativeMap.has(entry.lutIndex)) {
            nativeMap.set(entry.lutIndex, idx);
          }
          if (!anyMap.has(entry.lutIndex)) {
            anyMap.set(entry.lutIndex, idx);
          }
        });
        const translate = (lutIdx: number): number =>
          nativeMap.get(lutIdx) ?? anyMap.get(lutIdx) ?? 0;
        const translated = firstEntry.recipe.map(translate);
        // Size the recipe to the dialog's expected ``colorLayers`` so the
        // per-layer rows stay aligned. Pad side matches the backend's
        // ``pad_recipe_to_layer_count`` contract (Top2Bottom pads at the
        // end = bottom, Bottom2Top pads at the start = bottom); truncate
        // from the side where the bottom-most padding lives so user-visible
        // top layers always survive resizing.
        // 把 recipe 调整到对话框期望的 colorLayers 长度：Top2Bottom 在末
        // 尾补 / 从末尾裁，Bottom2Top 在开头补 / 从开头裁，跟后端 pad
        // 语义一致，保证可见的顶层不被截掉。
        // Dynamic material responses already carry the authoritative actual
        // recipe length. Do not expand it back to the maximum print width;
        // the backend adds substrate-side backing material after submission.
        // 动态耗材返回的是权威实际层数，不能在编辑器里重新扩成最大打印宽度；
        // 提交后由后端在非观赏面补齐基板耗材。
        const targetLen =
          sourceVersion === "material" && dynamicMaterialEnabled
            ? firstEntry.recipe.length
            : colorLayers;
        const defaultRecipe = buildDefaultRecipe(
          targetLen,
          displayPalette,
          resolvedBaseChannelIdx,
        );
        let sized: number[];
        if (translated.length === targetLen) {
          sized = translated;
        } else if (translated.length < targetLen) {
          const padCount = targetLen - translated.length;
          const filler = defaultRecipe.slice(0, padCount);
          sized =
            layerOrder === "Top2Bottom"
              ? [...translated, ...filler]
              : [...filler, ...translated];
        } else {
          sized =
            layerOrder === "Top2Bottom"
              ? translated.slice(0, targetLen)
              : translated.slice(translated.length - targetLen);
        }
        setRecipeRows(makeRecipeRows(sized, nextRecipeRowId));
      })
      .catch(() => {
        // Silent: the synchronous default already covers the UI.
        // 静默：前面已经写了同步默认值，兜底不报错。
      });
  }, [
    open,
    initializationKey,
    resolvedBaseChannelIdx,
    colorLayers,
    sessionId,
    layerOrder,
    displayPalette,
    dynamicMaterialEnabled,
    stableRegionIds,
    nextRecipeRowId,
    sourceVersion,
  ]);

  const snapshotBeforeEdit = useCallback(() => {
    markDraftEdited();
    setEditStack((prev) => [...prev, recipeRows.map((row) => row.displayIdx)]);
    setAppliedAt(null);
    setLastPredictFromModel(false);
  }, [recipeRows]);

  const handleUndo = () => {
    if (editStack.length === 0) return;
    markDraftEdited();
    setEditStack((prev) => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      const restored = next.pop();
      if (restored) {
        setRecipeRows(makeRecipeRows(restored, nextRecipeRowId));
      }
      setPendingUpgrade(false);
      setAppliedAt(null);
      setLastPredictFromModel(false);
      return next;
    });
  };

  const findDisplayIdxForLutIdx = useCallback(
    (lutIdx: number): number => {
      const nativeHit = displayPalette.findIndex(
        (entry) => entry.native && entry.lutIndex === lutIdx,
      );
      if (nativeHit >= 0) return nativeHit;
      const anyHit = displayPalette.findIndex(
        (entry) => entry.lutIndex === lutIdx,
      );
      return anyHit >= 0 ? anyHit : 0;
    },
    [displayPalette],
  );

  const colorOptions = useMemo(
    () =>
      displayPalette.map((entry, index) => ({
        // 用户指定：下拉 label 直接显示原色名，不再暴露 "→ 代用通道" 的翻译细节。
        // Per user request: show only the canonical primary name in the dropdown,
        // without the "→ substitute channel" translation hint.
        label: entry.color,
        value: String(index),
      })),
    [displayPalette],
  );

  const paletteHint = useMemo(
    () => buildPaletteHint(displayPalette),
    [displayPalette],
  );
  const canApply = stableRegionIds.length > 0 && recipe.length > 0;
  // 预测能力按「来源是否有前向模型」判断，而不是按来源类型一刀切：
  // - material 来源走 Beer-Lambert 前向模型，始终可预测；
  // - legacy/native LUT 只有在确实携带预测式运行时（supports_predictive_match）
  //   时才可预测，避免误伤带前向模型的 LUT。
  // Prediction gating follows the source's forward-model capability, not its
  // type: material sources always predict via Beer-Lambert; legacy/native LUTs
  // predict only when they carry a predictive runtime.
  const canPredictRecipe =
    sourceVersion === "material" ||
    Boolean(selectedLutInfo?.supports_predictive_match);
  const shouldConfirmUpgrade = pendingUpgrade && recipe.length > colorLayers;

  const updateLayer = (index: number, displayIdx: number) => {
    snapshotBeforeEdit();
    setRecipeRows((current) => {
      const next = [...current];
      const row = next[index];
      if (row) {
        next[index] = { ...row, displayIdx };
      }
      return next;
    });
    setPendingUpgrade(false);
  };

  const handleAddLayer = () => {
    snapshotBeforeEdit();
    const defaultDisplayIdx = displayPalette.findIndex(
      (entry) => entry.native && entry.lutIndex === resolvedBaseChannelIdx,
    );
    const safeIdx = defaultDisplayIdx >= 0 ? defaultDisplayIdx : 0;
    setRecipeRows((current) => [
      ...current,
      { id: nextRecipeRowId(), displayIdx: safeIdx },
    ]);
    setPendingUpgrade(false);
  };

  const handleRemoveLayer = (index: number) => {
    snapshotBeforeEdit();
    setRecipeRows((current) =>
      current.filter((_, currentIndex) => currentIndex !== index),
    );
    setPendingUpgrade(false);
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragId(String(event.active.id));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const activeId = String(event.active.id);
    const overId = event.over ? String(event.over.id) : null;
    setActiveDragId(null);
    if (!overId || activeId === overId) return;
    const oldIndex = recipeRows.findIndex((row) => row.id === activeId);
    const newIndex = recipeRows.findIndex((row) => row.id === overId);
    if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return;
    snapshotBeforeEdit();
    setRecipeRows((current) => arrayMove(current, oldIndex, newIndex));
    setPendingUpgrade(false);
  };

  const handleDragCancel = () => {
    setActiveDragId(null);
  };

  const handleApplyPattern = () => {
    const invalidChar = validateRecipePattern(pattern, displayPalette);
    if (invalidChar) {
      setErrorKind("general");
      setError(
        t("recipe_custom_pattern_invalid").replace("{char}", invalidChar),
      );
      return;
    }
    snapshotBeforeEdit();
    setError(null);
    setErrorKind("general");
    setPendingUpgrade(false);
    // Pattern runs against the display palette (8 primaries) and recipe state
    // is already in displayPalette indices, so no translation needed here.
    // pattern 基于 displayPalette（8 原色）解析，recipe state 本身就是
    // displayPalette 索引，无需再翻译。
    setRecipeRows((current) => {
      const nextRecipe = applyRecipePattern(
        pattern,
        displayPalette,
        current.length,
        current.map((row) => row.displayIdx),
      );
      return current.map((row, index) => ({
        ...row,
        displayIdx: nextRecipe[index] ?? row.displayIdx,
      }));
    });
  };

  // Translate a displayPalette-indexed recipe into backend-ready channel
  // indices. Native primaries keep their real LUT channel; non-native primaries
  // get appended to a ``virtual_materials`` list and referenced by index
  // ``palette.length + k`` so the backend knows to render them as extra
  // materials rather than silently substituting the nearest LUT channel.
  // 把 displayPalette 索引翻译成后端通道索引：原生原色用真实 LUT 通道；
  // 非原生原色则按 (name, hex) 去重加入 virtual_materials 列表，并用
  // ``palette.length + k`` 引用，后端据此扩展调色板而不是偷偷代用。
  const buildApiRecipePayload = useCallback(
    (
      displayRecipe: number[],
    ): { apiRecipe: number[]; virtualMaterials: VirtualMaterial[] } => {
      const lutPaletteLength = effectivePalette.length;
      const virtualMaterials: VirtualMaterial[] = [];
      const virtualLookup = new Map<string, number>();
      const apiRecipe: number[] = [];
      for (const displayIdx of displayRecipe) {
        const entry = displayPalette[displayIdx];
        if (!entry) {
          apiRecipe.push(resolvedBaseChannelIdx);
          continue;
        }
        if (entry.native) {
          apiRecipe.push(entry.lutIndex);
          continue;
        }
        const hex = entry.hex.startsWith("#") ? entry.hex : `#${entry.hex}`;
        const key = `${entry.color.trim().toLowerCase()}|${hex.toLowerCase()}`;
        let globalIdx = virtualLookup.get(key);
        if (globalIdx === undefined) {
          globalIdx = lutPaletteLength + virtualMaterials.length;
          virtualMaterials.push({ name: entry.color, hex });
          virtualLookup.set(key, globalIdx);
        }
        apiRecipe.push(globalIdx);
      }
      return { apiRecipe, virtualMaterials };
    },
    [displayPalette, effectivePalette.length, resolvedBaseChannelIdx],
  );

  const handlePredict = async () => {
    if (!canPredictRecipe) {
      return;
    }
    setIsPredicting(true);
    setError(null);
    setErrorKind("general");
    try {
      const { apiRecipe, virtualMaterials } = buildApiRecipePayload(recipe);
      const response = await predictCustomRecipe({
        session_id: sessionId,
        recipe: apiRecipe,
        layer_order: layerOrder,
        color_layers: recipe.length,
        layer_height_mm: layerHeightMm,
        ...(virtualMaterials.length > 0
          ? { virtual_materials: virtualMaterials }
          : {}),
      });
      setPrediction(response);
      setLastPredictFromModel(true);
    } catch (err) {
      const message = resolveCustomRecipeError(
        err,
        t("recipe_custom_predict_failed"),
      );
      const kind = classifyPredictError(message);
      setErrorKind(kind);
      setError(
        kind === "no_forward_model"
          ? t("recipe_custom_predict_no_forward_model")
          : message || t("recipe_custom_predict_failed"),
      );
    } finally {
      setIsPredicting(false);
    }
  };

  const handleApply = async () => {
    if (!canApply) {
      setErrorKind("general");
      setError(t("recipe_custom_region_required"));
      return;
    }
    setIsApplying(true);
    setError(null);
    setErrorKind("general");
    try {
      const { apiRecipe, virtualMaterials } = buildApiRecipePayload(recipe);
      const response = await useConverterStore.getState().commitRecipeOverride({
        session_id: sessionId,
        recipe: apiRecipe,
        layer_order: layerOrder,
        color_layers: recipe.length,
        layer_height_mm: layerHeightMm,
        region_ids: stableRegionIds,
        ...(virtualMaterials.length > 0
          ? { virtual_materials: virtualMaterials }
          : {}),
      });
      if (!response) {
        throw new Error(useConverterStore.getState().error ?? t("recipe_custom_apply_failed"));
      }
      onApplied?.(response, apiRecipe, recipe.length, layerHeightMm, virtualMaterials);
      // Keep the per-layer visual intent (the 8-primary picks) alongside the
      // LUT-translated recipe so the side-panel history row echoes exactly
      // what the user clicked — even when a sparse LUT forces a substitute
      // channel on the backend.
      // 同时保存每层的视觉原色 hex，历史条目里展示的是用户点的"黑/红/..."，
      // 而不是稀疏 LUT 代用后的 LUT 通道色。
      const displayHexes = recipe.map(
        (displayIdx) => displayPalette[displayIdx]?.hex ?? "#808080",
      );
      const displayLabels = recipe.map(
        (displayIdx) => displayPalette[displayIdx]?.color ?? "?",
      );
      const historyEntry: RecipeHistoryItem = {
        id: `${apiRecipe.join("-")}@${layerOrder}`,
        recipe: [...apiRecipe],
        layerOrder,
        predictedRgb: [
          Number(response.rgb[0] ?? 0),
          Number(response.rgb[1] ?? 0),
          Number(response.rgb[2] ?? 0),
        ],
        predictedLab: [
          Number(response.lab[0] ?? 0),
          Number(response.lab[1] ?? 0),
          Number(response.lab[2] ?? 0),
        ],
        hex:
          response.rgb.length === 3
            ? `#${response.rgb.slice(0, 3).map(toHexByte).join("")}`
            : "#808080",
        fromModel: lastPredictFromModel,
        createdAtMs: Date.now(),
        displayHexes,
        displayLabels,
        // Snapshot the virtuals so history replay through
        // ``applyCustomRecipeFromHistory`` can forward them to backend
        // validation and the worker palette extension — otherwise replay
        // would 422 on ``recipe[i] >= LUT.N``.
        // 记下本次 apply 的虚拟耗材，保证历史重放时后端 422 校验能通过、
        // worker 也能重建虚拟材料注册表，避免重放后模型缺对象 / 透明失效。
        ...(virtualMaterials.length > 0
          ? {
              virtualMaterials: virtualMaterials.map((material) => ({
                name: material.name,
                hex: material.hex,
              })),
            }
          : {}),
      };
      pushCustomRecipeHistory(historyEntry);
      setPendingUpgrade(false);
      setEditStack([]);
      setAppliedAt(Date.now());
      if (response.rgb.length >= 3) {
        setAppliedRegionHex(
          `#${response.rgb.slice(0, 3).map(toHexByte).join("")}`,
        );
      }
    } catch (err) {
      setErrorKind("unknown");
      setError(resolveCustomRecipeError(err, t("recipe_custom_apply_failed")));
    } finally {
      setIsApplying(false);
    }
  };

  const handleApplyClick = () => {
    if (!canApply) {
      setErrorKind("general");
      setError(t("recipe_custom_region_required"));
      return;
    }
    if (recipe.length > colorLayers && !pendingUpgrade) {
      setPendingUpgrade(true);
      return;
    }
    setPendingUpgrade(false);
    void handleApply();
  };

  const sidePalette: CustomRecipeSidePanelPaletteEntry[] = effectivePalette.map(
    (entry) => ({
      color: entry.color,
      hex: entry.hex ?? null,
    }),
  );

  const handleApplyHistory = (historyId: string) => {
    const entry = customRecipeHistory.find((item) => item.id === historyId);
    if (!entry) return;
    snapshotBeforeEdit();
    // Prefer the persisted per-layer primary names (displayLabels) to restore
    // the user's original 8-primary picks; fall back to the LUT-index path for
    // legacy entries lacking that field. Otherwise a sparse LUT (e.g. CMYW)
    // would snap "Black" back to whichever native channel it was substituted
    // into (e.g. Magenta) — losing the original intent on reload.
    // 优先用持久化的每层原色名（displayLabels）还原用户当时选的 8 原色；旧
    // 条目没有该字段时回退到 LUT 索引路径。否则稀疏 LUT（如 CMYW）上"黑"
    // 会被回弹到当时代用的原生通道（例如 Magenta），丢失用户意图。
    const byName = (label: string | undefined): number => {
      if (!label) return -1;
      const target = label.trim().toLowerCase();
      return displayPalette.findIndex(
        (e) => e.color.trim().toLowerCase() === target,
      );
    };
    const restored = entry.recipe.map((lutIdx, idx) => {
      const labelHit = byName(entry.displayLabels?.[idx]);
      if (labelHit >= 0) return labelHit;
      return findDisplayIdxForLutIdx(lutIdx);
    });
    setRecipeRows(makeRecipeRows(restored, nextRecipeRowId));
    setPendingUpgrade(false);
    setError(null);
    setErrorKind("general");
    setAppliedAt(Date.now());
    void useConverterStore
      .getState()
      .applyCustomRecipeFromHistory(historyId, stableRegionIds);
  };

  if (!open) return null;

  const errorToneClass =
    errorKind === "no_forward_model"
      ? "border-slate-300/80 bg-slate-100/70 text-slate-600 dark:border-slate-700/70 dark:bg-slate-800/50 dark:text-slate-300"
      : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-300";

  const headerRegionHex = appliedRegionHex ?? currentRegionColorHex ?? null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4"
      style={{
        backgroundColor: "var(--surface-scrim)",
      }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("recipe_custom_title")}
        className="max-h-[90vh] w-full max-w-5xl overflow-hidden rounded-[28px] border border-slate-200 shadow-2xl dark:border-slate-700"
        style={{ backgroundColor: "var(--surface-panel-strong)" }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="max-h-[90vh] overflow-y-auto overscroll-y-contain p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            {headerRegionHex && (
              <span
                data-testid="recipe-current-region-swatch"
                className="h-11 w-11 shrink-0 rounded-2xl border border-slate-300/80 shadow-[var(--shadow-control)] dark:border-slate-600/80"
                style={{ backgroundColor: headerRegionHex }}
                title={headerRegionHex.toUpperCase()}
              />
            )}
            <div>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
                {t("recipe_custom_title")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("recipe_custom_layer_count").replace(
                  "{count}",
                  String(recipe.length),
                )}
                {stableRegionIds.length > 1
                  ? " · " +
                    t("recipe_custom_region_multiple").replace(
                      "{count}",
                      String(stableRegionIds.length),
                    )
                  : stableRegionIds.length === 1
                    ? " · " + t("recipe_custom_current_region")
                    : ""}
              </p>
            </div>
          </div>
          <CloseButton label={t("recipe_custom_close")} onClick={onClose} />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="flex flex-col gap-3">
            <div className="rounded-2xl border border-slate-200/80 bg-slate-100/70 p-3 text-xs text-slate-500 dark:border-slate-700/70 dark:bg-slate-900/50 dark:text-slate-400">
              {t("recipe_custom_pattern_hint")}
              <div className="mt-2 font-mono">{paletteHint}</div>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={pattern}
                onChange={(event) => setPattern(event.target.value)}
                placeholder={t("recipe_custom_pattern_placeholder")}
                className={`min-h-10 flex-1 ${workstationInputClass}`}
              />
              <Button
                label={t("recipe_custom_pattern_apply")}
                variant="secondary"
                onClick={handleApplyPattern}
              />
            </div>

            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              modifiers={[restrictToVerticalAxis]}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
              onDragCancel={handleDragCancel}
            >
              <SortableContext
                items={recipeRows.map((row) => row.id)}
                strategy={verticalListSortingStrategy}
              >
                <div className="flex flex-col gap-3">
                  {recipeRows.map((row, index) => (
                    <SortableRecipeRow
                      key={row.id}
                      row={row}
                      index={index}
                      displayPalette={displayPalette}
                      colorOptions={colorOptions}
                      layerLabel={formatDisplayLayerLabelParts(index, t, lang)}
                      removeLabel={t("recipe_custom_remove_layer")}
                      dragHandleLabel={t("recipe_custom_drag_handle_label")}
                      canRemove={recipeRows.length > 1}
                      onChangeLayer={updateLayer}
                      onRemoveLayer={handleRemoveLayer}
                    />
                  ))}
                </div>
              </SortableContext>
              <DragOverlay dropAnimation={null}>
                {activeDragId ? (
                  <div className="rounded-2xl border border-blue-400/70 bg-blue-50/95 p-3 text-sm font-medium text-slate-700 shadow-xl dark:border-blue-500/60 dark:bg-slate-900/95 dark:text-slate-200">
                    {
                      formatDisplayLayerLabelParts(
                        Math.max(
                          0,
                          recipeRows.findIndex((row) => row.id === activeDragId),
                        ),
                        t,
                        lang,
                      ).label
                    }
                  </div>
                ) : null}
              </DragOverlay>
            </DndContext>

            {shouldConfirmUpgrade && (
              <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
                {t("recipe_custom_layer_upgrade_warning")
                  .replace("{old}", String(colorLayers))
                  .replace("{new}", String(recipe.length))}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                label={t("recipe_custom_add_layer")}
                variant="secondary"
                onClick={handleAddLayer}
                disabled={recipe.length >= 10}
              />
              <Button
                label={t("recipe_custom_undo")}
                variant="secondary"
                onClick={handleUndo}
                disabled={editStack.length === 0}
              />
              <Button
                label={
                  isPredicting
                    ? t("recipe_custom_predicting")
                    : t("recipe_custom_predict")
                }
                variant="secondary"
                onClick={() => void handlePredict()}
                disabled={isPredicting || !canPredictRecipe}
                loading={isPredicting}
              />
              <Button
                label={
                  shouldConfirmUpgrade
                    ? t("recipe_custom_layer_upgrade_confirm")
                    : isApplying
                      ? t("recipe_custom_applying")
                      : t("recipe_custom_apply")
                }
                onClick={handleApplyClick}
                disabled={!canApply || isApplying}
                loading={isApplying}
                variant="primary"
              />
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-3 rounded-2xl border border-slate-200/80 bg-slate-100/70 p-4 dark:border-slate-700/70 dark:bg-slate-900/50">
              <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("recipe_custom_preview_color")}
              </div>
              {!canPredictRecipe ? (
                <div className="rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 text-xs text-slate-600 dark:border-slate-700/70 dark:bg-slate-800/50 dark:text-slate-300">
                  {t("recipe_custom_predict_no_forward_model")}
                </div>
              ) : prediction ? (
                <>
                  <div
                    className="h-24 rounded-2xl border border-slate-200/80 shadow-[var(--shadow-control)] dark:border-slate-700/70"
                    style={{
                      backgroundColor:
                        prediction.rgb.length === 3
                          ? `rgb(${prediction.rgb.join(",")})`
                          : "transparent",
                    }}
                  />
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {t("recipe_custom_rgb_label")}: {prediction.rgb.join(", ")}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {t("recipe_custom_lab_label")}:{" "}
                    {prediction.lab
                      .map((value) => value.toFixed(2))
                      .join(", ")}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {prediction.source}
                    {prediction.runtime_mode_key
                      ? ` · ${prediction.runtime_mode_key}`
                      : ""}
                  </div>
                </>
              ) : (
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {t("recipe_custom_predict_hint")}
                </div>
              )}

              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("recipe_custom_region_count").replace(
                  "{count}",
                  String(stableRegionIds.length),
                )}
              </div>
              {appliedAt && !error && (
                <div
                  data-testid="recipe-applied-banner"
                  className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300"
                >
                  {t("recipe_custom_applied_toast")}
                </div>
              )}
              {error && (
                <div
                  data-testid="recipe-error-banner"
                  className={`rounded-2xl border px-3 py-2 text-sm ${errorToneClass}`}
                >
                  {error}
                </div>
              )}
            </div>

            <CustomRecipeSidePanel
              palette={sidePalette}
              regionIds={stableRegionIds}
              history={customRecipeHistory}
              onApplyHistory={handleApplyHistory}
            />
          </div>
        </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
