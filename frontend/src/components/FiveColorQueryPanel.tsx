import CloseButton from "./ui/CloseButton";
import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useMemo, useCallback, useState } from "react"
import type { FormEvent } from "react"
import type { BaseColorEntry, FiveColorMatchResponse, FiveColorQueryResponse } from "../api/types"
import {
  hasCompleteFiveColorSelection,
  resolveFiveColorRecipeLength,
  useFiveColorStore,
} from "../stores/fiveColorStore"
import { useConverterStore } from "../stores/converter"
import {
  apiErrorToVisibleMessage,
  buildApiResourceUrl,
  downloadResourceBlob,
} from "../api/client"
import Dropdown from "./ui/Dropdown"
import { useWorkspaceMode } from "../hooks/useWorkspaceMode"
import { useI18n } from "../i18n/context"
import FiveColorCanvas from "./FiveColorCanvas"
import Button from "./ui/Button"
import { UI_COLOR_TOKENS } from "../theme/uiTokens"
import {
  StatusBanner,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives"

const RAW_STATUS_CODE_ERROR = /^Request failed with status code \d{3}$/i

export default function FiveColorQueryPanel() {
  const { t } = useI18n()
  const workspace = useWorkspaceMode()
  const [targetHex, setTargetHex] = useState("")
  const {
    lutName, baseColors, combinations, selectedIndices, queryResult,
    isLoading, error,
    loadBaseColors, addSelection, removeLastSelection,
    clearSelection, reverseSelection, submitQuery, matchColorByHex, clearError,
    collectedRecipes, swatchBlockSize, swatchGap, swatchCols, swatchStructureMode,
    isGeneratingSwatch, swatchDownloadUrl, swatchPreviewUrl,
    addToCollection, removeFromCollection, clearCollection,
    setSwatchBlockSize, setSwatchGap, setSwatchCols, setSwatchStructureMode, generateSwatch,
  } = useFiveColorStore()

  const catalogLuts = useConverterStore((s) => s.lutList)
  const lutList = lutName && !catalogLuts.includes(lutName) ? [...catalogLuts, lutName] : catalogLuts
  const fetchLutList = useConverterStore((s) => s.fetchLutList)
  const [isDownloadingSwatch, setIsDownloadingSwatch] = useState(false)
  const [swatchDownloadError, setSwatchDownloadError] = useState<string | null>(null)

  useEffect(() => {
    if (lutList.length === 0) void fetchLutList()
  }, [fetchLutList, lutList.length])

  const handleLutChange = (name: string) => {
    if (name) {
      setSwatchDownloadError(null)
      clearError()
      void loadBaseColors(name)
    }
  }

  const selectionLimit = useMemo(
    () => resolveFiveColorRecipeLength(combinations, selectedIndices),
    [combinations, selectedIndices],
  )
  const canSubmitSelection = useMemo(
    () => hasCompleteFiveColorSelection(combinations, selectedIndices),
    [combinations, selectedIndices],
  )
  const hasSelection = selectedIndices.length > 0
  const hasReachedSelectionLimit = selectedIndices.length === selectionLimit
  const canReverse = canSubmitSelection
  const matchResult = isFiveColorMatchResponse(queryResult) ? queryResult : null
  const isRecipeUnavailable = queryResult?.reason === "recipe_unavailable"

  const canAddToCollection = queryResult?.found && queryResult.result_hex
  const isAlreadyCollected = useMemo(() => {
    if (!queryResult?.found || !queryResult.result_hex) return false
    return collectedRecipes.some(
      (r) =>
        r.selectedIndices.join(",") === selectedIndices.join(",") &&
        r.resultHex === queryResult.result_hex
    )
  }, [collectedRecipes, selectedIndices, queryResult])

  const handleGenerateSwatch = useCallback(() => {
    setSwatchDownloadError(null)
    void generateSwatch()
  }, [generateSwatch])

  const handleClearCollection = useCallback(() => {
    setSwatchDownloadError(null)
    clearCollection()
  }, [clearCollection])

  const handleClearVisibleError = useCallback(() => {
    setSwatchDownloadError(null)
    clearError()
  }, [clearError])

  const handleDownloadSwatch = useCallback(async () => {
    if (!swatchDownloadUrl || isDownloadingSwatch) return
    setIsDownloadingSwatch(true)
    setSwatchDownloadError(null)
    let objectUrl: string | null = null
    try {
      const blob = await downloadResourceBlob(buildApiResourceUrl(swatchDownloadUrl))
      objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = objectUrl
      anchor.download = "five-color-swatch.3mf"
      anchor.style.display = "none"
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (err) {
      setSwatchDownloadError(
        apiErrorToVisibleMessage(err, t("five_color_error_download_swatch_failed")),
      )
    } finally {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
      setIsDownloadingSwatch(false)
    }
  }, [isDownloadingSwatch, swatchDownloadUrl, t])

  const handleTargetMatch = useCallback((event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const value = targetHex.trim()
    if (!value) return
    void matchColorByHex(value)
  }, [matchColorByHex, targetHex])

  const validNextIndices = useMemo(() => {
    if (hasReachedSelectionLimit) return null
    if (!combinations) return null
    if (combinations.length === 0) return []

    const len = selectedIndices.length
    const valid = new Set<number>()

    for (const combo of combinations) {
      let match = true
      for (let i = 0; i < len; i++) {
        if (combo[i] !== selectedIndices[i]) {
          match = false
          break
        }
      }
      if (match && len < selectionLimit) {
        valid.add(combo[len])
      }
    }
    return Array.from(valid)
  }, [combinations, selectedIndices, hasReachedSelectionLimit, selectionLimit])

  const canvasSlices = useMemo(
    () => selectedIndices.map((idx) => {
      const c = baseColors.find((b) => b.index === idx)
      return c ? { hex: c.hex, name: c.name } : { hex: UI_COLOR_TOKENS.fiveColorFallbackHex, name: "?" }
    }),
    [selectedIndices, baseColors],
  )

  return (
    <motion.div
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex h-full w-full min-h-0"
    >
      <aside className={`${resolvePanelSurfaceClass(workspace.mode)} h-auto w-full overflow-y-auto xl:h-full xl:w-[400px] xl:shrink-0 2xl:w-[480px]`}>
        <div className="flex flex-col gap-5">
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div className="flex flex-col gap-3">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_palette")}</h3>
              <Dropdown
                label={t("five_color_lut_label")}
                value={lutName}
                options={lutList.map((n) => ({ label: n, value: n }))}
                onChange={handleLutChange}
                placeholder={t("five_color_lut_placeholder")}
              />
            </div>

            <div className="pr-1">
              {baseColors.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {combinations && combinations.length > 0 && (
                    <div className="flex flex-col gap-1 px-2">
                      <div className="text-xs text-blue-600 dark:text-blue-400 font-medium">
                        {t("five_color_combinations_loaded").replace("{count}", String(combinations.length))}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {t("five_color_combinations_hint")}
                      </div>
                    </div>
                  )}
                  <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3"}`}>
                    {baseColors.map((color) => {
                      const isSelected = selectedIndices.includes(color.index)
                      const selOrder = selectedIndices.indexOf(color.index)
                      const isValidNext = validNextIndices === null || validNextIndices.includes(color.index)
                      const disabled = hasReachedSelectionLimit || !isValidNext

                      return (
                        <button
                          key={color.index}
                          onClick={() => addSelection(color.index)}
                          disabled={disabled}
                          className={`group relative flex flex-col items-center gap-1 rounded-[20px] border p-2 transition-all ${
                            isSelected
                              ? disabled
                                ? "border-blue-400/50 bg-blue-500/5 ring-2 ring-blue-500/10 opacity-60"
                                : "border-blue-400 bg-blue-500/10 ring-2 ring-blue-500/20"
                              : isValidNext
                                ? "border-transparent bg-slate-100/60 hover:border-slate-300 hover:bg-slate-100/80 dark:bg-slate-900/45 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
                                : "border-transparent bg-slate-100/30 opacity-40 grayscale"
                          } ${disabled ? "cursor-not-allowed" : "cursor-pointer"}`}
                          aria-label={t("five_color_select_color").replace("{name}", color.name).replace("{hex}", color.hex)}
                        >
                          <div
                            className="h-11 w-11 rounded-2xl border border-slate-200/80 shadow-[var(--shadow-control)] transition-transform group-hover:scale-105 dark:border-slate-700/80"
                            style={{ backgroundColor: color.hex }}
                          />
                          {isSelected && (
                            <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-blue-500 text-xs font-bold text-white">
                              {selOrder + 1}
                            </span>
                          )}
                          <span className="w-full truncate text-center text-[11px] leading-tight text-slate-500 dark:text-slate-400">
                            {color.name}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ) : lutName ? (
                <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_no_base_colors")}</p>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_select_lut_first")}</p>
              )}
            </div>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <div className="flex flex-col gap-1">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_match_title")}</h3>
              <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{t("five_color_match_desc")}</p>
            </div>

            <form className="flex flex-col gap-3" onSubmit={handleTargetMatch}>
              <label className="flex flex-col gap-1.5" htmlFor="five-color-target-hex">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("five_color_match_input_label")}
                </span>
                <input
                  id="five-color-target-hex"
                  value={targetHex}
                  onChange={(event) => setTargetHex(event.target.value)}
                  placeholder={t("five_color_match_input_placeholder")}
                  className="min-h-11 rounded-2xl border border-slate-200/80 bg-slate-100 px-3.5 py-2 text-sm font-mono text-slate-800 shadow-[var(--shadow-control)] outline-none transition-all focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/72 dark:text-slate-100"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <Button
                type="submit"
                disabled={!lutName || targetHex.trim().length === 0 || isLoading}
                label={isLoading ? t("five_color_query_loading") : t("five_color_match_button")}
              />
            </form>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_actions")}</h3>

            <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-1" : "grid-cols-2"}`}>
              <Button
                onClick={() => void submitQuery()}
                disabled={!canSubmitSelection || isLoading}
                label={isLoading ? t("five_color_query_loading") : t("five_color_query")}
                className={workspace.isCompact ? "" : "col-span-2"}
                variant="primary"
              />
              {canAddToCollection && (
                <Button
                  onClick={addToCollection}
                  disabled={isAlreadyCollected}
                  label={isAlreadyCollected ? t("five_color_already_in_list") : t("five_color_add_to_list")}
                  variant="secondary"
                  className={workspace.isCompact ? "" : "col-span-2"}
                />
              )}
              <Button
                onClick={removeLastSelection}
                disabled={!hasSelection}
                label={t("five_color_undo")}
                variant="secondary"
              />
              <Button
                onClick={reverseSelection}
                disabled={!canReverse}
                label={t("five_color_reverse")}
                variant="secondary"
              />
              <Button
                onClick={clearSelection}
                disabled={!hasSelection}
                label={t("five_color_clear")}
                variant="secondary"
                className={workspace.isCompact ? "" : "col-span-2"}
              />
            </div>
          </section>

          {/* Recipe Collection Section */}
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("five_color_collection_title")}
              </h3>
              {collectedRecipes.length > 0 && (
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {t("five_color_collection_count").replace("{count}", String(collectedRecipes.length))}
                </span>
              )}
            </div>

            {collectedRecipes.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                {t("five_color_collection_empty")}
              </p>
            ) : (
              <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
                <AnimatePresence initial={false}>
                  {collectedRecipes.map((recipe) => (
                    <motion.div
                      key={recipe.id}
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.2 }}
                      className="group flex items-center gap-2 rounded-xl border border-slate-200/80 bg-slate-100/80 p-2 shadow-sm dark:border-slate-700/80 dark:bg-slate-900/70"
                    >
                      <div
                        className="h-8 w-8 shrink-0 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm"
                        style={{ backgroundColor: recipe.resultHex }}
                      />
                      <div className="flex flex-1 flex-col min-w-0">
                        <span className="truncate text-xs font-medium text-slate-700 dark:text-slate-200">
                          {recipe.label}
                        </span>
                        <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500">
                          {recipe.resultHex}
                        </span>
                      </div>
                      <button
                        onClick={() => removeFromCollection(recipe.id)}
                        className="shrink-0 rounded-full p-1 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400"
                        aria-label={t("five_color_remove_recipe")}
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      </button>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            )}

            {collectedRecipes.length > 0 && (
              <div className="flex flex-col gap-3 pt-1">
                <>
                  <div className="grid grid-cols-3 gap-2">
                      <label className="flex flex-col gap-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_block_size")}</span>
                        <input
                          type="number"
                          min={5}
                          max={50}
                          step={1}
                          value={swatchBlockSize}
                          onChange={(e) => setSwatchBlockSize(Number(e.target.value))}
                          className="h-9 rounded-lg border border-slate-200 bg-slate-100 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_gap")}</span>
                        <input
                          type="number"
                          min={0.5}
                          max={10}
                          step={0.5}
                          value={swatchGap}
                          onChange={(e) => setSwatchGap(Number(e.target.value))}
                          className="h-9 rounded-lg border border-slate-200 bg-slate-100 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_cols")}</span>
                        <input
                          type="number"
                          min={0}
                          max={20}
                          step={1}
                          value={swatchCols}
                          onChange={(e) => setSwatchCols(Number(e.target.value))}
                          className="h-9 rounded-lg border border-slate-200 bg-slate-100 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                      </label>
                  </div>

                  <div className="flex flex-col gap-1">
                      <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_structure")}</span>
                      <div className="grid grid-cols-2 gap-1.5">
                        {(["Single-sided", "Double-sided"] as const).map((mode) => {
                          const isActive = swatchStructureMode === mode
                          const labelKey = mode === "Single-sided" ? "five_color_swatch_single_sided" : "five_color_swatch_double_sided"
                          return (
                            <button
                              key={mode}
                              type="button"
                              onClick={() => setSwatchStructureMode(mode)}
                              className={`h-9 rounded-lg border text-xs font-medium transition-all ${
                                isActive
                                  ? "border-blue-400 bg-blue-500/10 text-blue-600 ring-1 ring-blue-500/20 dark:border-blue-500 dark:text-blue-400"
                                  : "border-slate-200 bg-slate-100 text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600"
                              }`}
                            >
                              {t(labelKey)}
                            </button>
                          )
                        })}
                      </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                      <Button
                        onClick={handleGenerateSwatch}
                        disabled={isGeneratingSwatch}
                        loading={isGeneratingSwatch}
                        label={isGeneratingSwatch ? t("five_color_generating_swatch") : t("five_color_generate_swatch")}
                        variant="primary"
                      />
                      {swatchDownloadUrl && (
                        <Button
                          onClick={() => void handleDownloadSwatch()}
                          disabled={isDownloadingSwatch}
                          loading={isDownloadingSwatch}
                          label={t("five_color_download_swatch")}
                          variant="secondary"
                        />
                      )}
                      {!swatchDownloadUrl && (
                        <Button
                          onClick={handleClearCollection}
                          label={t("five_color_collection_clear")}
                          variant="secondary"
                        />
                      )}
                  </div>

                  {swatchPreviewUrl && (
                    <div className="rounded-xl border border-slate-200/80 overflow-hidden shadow-sm dark:border-slate-700/80">
                      <img
                        src={buildApiResourceUrl(swatchPreviewUrl)}
                        alt={t("five_color_swatch_legend_alt")}
                        className="w-full h-auto"
                      />
                    </div>
                  )}
                </>

                {swatchDownloadUrl && (
                  <Button
                    onClick={handleClearCollection}
                    label={t("five_color_collection_clear")}
                    variant="secondary"
                  />
                )}
              </div>
            )}
          </section>
        </div>
      </aside>

      <div className={`relative min-h-0 flex-1 overflow-hidden border-slate-200/70 dark:border-slate-800/80 flex flex-col bg-slate-50 dark:bg-slate-950 ${workspace.isWide ? "border-t 2xl:border-l 2xl:border-t-0" : "border-t"}`}>
        {(swatchDownloadError || error || queryResult) && (
          <div className="flex-none border-b border-slate-200/70 bg-slate-100/70 p-4 sm:p-5 lg:p-7 dark:border-slate-800/80 dark:bg-slate-900/50">
            {(swatchDownloadError || error) && (
              <StatusBanner
                tone="error"
                action={
                  <CloseButton label={t("five_color_close_error")} onClick={handleClearVisibleError} />
                }
              >
                {swatchDownloadError ?? (error ? resolveFiveColorError(error, t) : null)}
              </StatusBanner>
            )}

            {queryResult && queryResult.found && (
              <div className="flex flex-col gap-4">
                <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
                  <StatusBanner tone="success" className="w-full sm:w-auto flex-1">
                    {t("five_color_result_panel")}
                  </StatusBanner>

                  <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-100/80 p-2.5 shadow-sm shrink-0 dark:border-slate-700 dark:bg-slate-900">
                    <div
                      className="h-10 w-16 sm:w-20 rounded-[12px] border border-slate-200 dark:border-slate-700 shadow-[var(--shadow-control)]"
                      style={{ backgroundColor: queryResult.result_hex ?? undefined }}
                    />
                    <div className="flex flex-col">
                      <span className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-100">{queryResult.result_hex}</span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {t("five_color_result_lut_row_index")}: {queryResult.row_index}
                      </span>
                    </div>
                  </div>
                </div>
                {matchResult && (
                  <MatchColorDetails
                    result={matchResult}
                    baseColors={baseColors}
                    t={t}
                  />
                )}
              </div>
            )}

            {queryResult && !queryResult.found && (
              <div className="flex flex-col gap-2">
                <StatusBanner tone="warning">
                  {isRecipeUnavailable ? t("five_color_match_recipe_unavailable_title") : t("five_color_not_found")}
                </StatusBanner>
                {queryResult.message && (
                  <div className="rounded-lg border border-slate-200 bg-slate-100 p-3 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300">
                    {resolveFiveColorFailureMessage(queryResult, t)}
                  </div>
                )}
                {!isRecipeUnavailable && (
                  <div className="text-xs text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-900/50 rounded-lg p-3 border border-slate-200 dark:border-slate-700">
                    <div className="font-medium mb-1">{t("five_color_not_found_suggestions_title")}</div>
                    <ul className="list-disc list-inside space-y-0.5 ml-1">
                      <li>{t("five_color_not_found_tip_reverse")}</li>
                      <li>{t("five_color_not_found_tip_change")}</li>
                      <li>{t("five_color_not_found_tip_gray")}</li>
                    </ul>
                  </div>
                )}
                {matchResult && (
                  <MatchColorDetails
                    result={matchResult}
                    baseColors={baseColors}
                    t={t}
                  />
                )}
              </div>
            )}
          </div>
        )}

        <div className="relative flex-1 min-h-0 flex flex-col items-center justify-center overflow-hidden p-4 sm:p-8 pt-12 sm:pt-16">
          <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-blue-500/5 to-transparent pointer-events-none" />
          <div className="relative flex w-full max-w-2xl flex-1 items-center justify-center translate-y-4">
            <div className="h-full w-full">
              <FiveColorCanvas
                slices={canvasSlices}
                resultHex={queryResult?.found ? queryResult.result_hex : null}
                isLoading={isLoading}
                layerCount={selectionLimit}
              />
            </div>
          </div>
          <p className="relative mt-8 mb-4 text-sm font-medium text-slate-500 dark:text-slate-400 bg-slate-100/80 dark:bg-slate-800/80 px-4 py-2 rounded-full shadow-sm backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50">
            {baseColors.length > 0
              ? t("five_color_selection_progress").replace("{count}", String(selectedIndices.length)).replace("{total}", String(selectionLimit))
              : t("five_color_select_lut_first")}
          </p>
        </div>
      </div>
    </motion.div>
  )
}

function isFiveColorMatchResponse(result: FiveColorQueryResponse | null): result is FiveColorMatchResponse {
  return Boolean(result && "target_hex" in result && "coordinate" in result && "neighborhood" in result)
}

function MatchColorDetails({
  result,
  baseColors,
  t,
}: {
  result: FiveColorMatchResponse
  baseColors: BaseColorEntry[]
  t: (key: string) => string
}) {
  const coordinate = result.coordinate
  const recipeIndices = result.selected_indices
  const gridCols = Math.max(result.neighborhood[0]?.length ?? 1, 1)
  const formatRgb = (rgb: [number, number, number] | null) =>
    rgb ? t("five_color_match_rgb_value").replace("{value}", rgb.join(", ")) : ""

  return (
    <div className="grid gap-4 rounded-2xl border border-slate-200/80 bg-slate-100/80 p-4 shadow-sm dark:border-slate-700/80 dark:bg-slate-900/70 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <ColorMatchChip
            label={t("five_color_match_target")}
            hex={result.target_hex}
            rgbText={formatRgb(result.target_rgb)}
          />
          <ColorMatchChip
            label={t("five_color_match_matched")}
            hex={result.matched_hex}
            rgbText={formatRgb(result.matched_rgb)}
          />
        </div>

        <div className="grid gap-2 text-xs text-slate-600 dark:text-slate-300 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200/70 bg-slate-100/70 px-3 py-2 dark:border-slate-700/70 dark:bg-slate-950/40">
            <span className="font-medium text-slate-800 dark:text-slate-100">{t("five_color_match_delta")}</span>
            <span className="ml-2 font-mono">{result.delta_e == null ? "-" : result.delta_e.toFixed(2)}</span>
          </div>
          <div
            data-testid="five-color-match-coordinate"
            className="rounded-xl border border-slate-200/70 bg-slate-100/70 px-3 py-2 dark:border-slate-700/70 dark:bg-slate-950/40"
          >
            <span className="font-medium text-slate-800 dark:text-slate-100">{t("five_color_match_position")}</span>
            <span className="ml-2">
              {t("five_color_match_card").replace("{card}", coordinate.card_label)}
              {" · "}
              {t("five_color_match_row").replace("{row}", String(coordinate.display_row))}
              {" · "}
              {t("five_color_match_col").replace("{col}", String(coordinate.display_col))}
            </span>
          </div>
        </div>

        {recipeIndices.length > 0 && (
          <div className="flex flex-col gap-2" data-testid="five-color-match-recipe">
            <span className="text-xs font-medium text-slate-700 dark:text-slate-200">
              {t("five_color_match_recipe")}
            </span>
            <div
              className="grid gap-1.5"
              style={{ gridTemplateColumns: `repeat(${Math.max(1, Math.min(recipeIndices.length, 6))}, minmax(0, 1fr))` }}
            >
              {recipeIndices.map((idx, order) => {
                const baseColor = baseColors.find((color) => color.index === idx)
                return (
                  <div
                    key={`${idx}-${order}`}
                    data-testid="five-color-match-recipe-layer"
                    className="min-h-14 rounded-xl border border-slate-200/80 bg-slate-100/70 p-1.5 text-center shadow-sm dark:border-slate-700/80 dark:bg-slate-950/40"
                  >
                    <div
                      className="mx-auto h-6 w-full max-w-10 rounded-lg border border-slate-200/80 dark:border-slate-700/80"
                      style={{ backgroundColor: baseColor?.hex ?? UI_COLOR_TOKENS.fiveColorFallbackHex }}
                    />
                    <div className="mt-1 truncate text-[10px] text-slate-500 dark:text-slate-400">
                      {baseColor?.name ?? `#${idx}`}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-slate-700 dark:text-slate-200">
          {t("five_color_match_neighborhood")}
        </span>
        <div
          data-testid="five-color-match-neighborhood"
          className="grid w-[180px] gap-1"
          style={{ gridTemplateColumns: `repeat(${gridCols}, minmax(0, 1fr))` }}
        >
          {result.neighborhood.flat().map((cell, index) => {
            const label = cell.hex
              ? [
                  cell.hex,
                  t("five_color_match_card").replace("{card}", cell.card_label ?? ""),
                  t("five_color_match_row").replace("{row}", String(cell.display_row ?? "")),
                  t("five_color_match_col").replace("{col}", String(cell.display_col ?? "")),
                ].join(" · ")
              : t("five_color_match_empty_cell")
            return (
              <div
                key={`${cell.row_index ?? "empty"}-${index}`}
                data-testid="five-color-match-cell"
                aria-label={label}
                title={label}
                className={`h-8 rounded-lg border shadow-sm ${
                  cell.hex
                    ? "border-slate-200/80 dark:border-slate-700/80"
                    : "border-dashed border-slate-200/80 bg-slate-100/40 dark:border-slate-700/80 dark:bg-slate-950/30"
                } ${cell.is_match ? "ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50 dark:ring-offset-slate-900" : ""}`}
                style={{ backgroundColor: cell.hex ?? undefined }}
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}

function resolveFiveColorFailureMessage(
  result: FiveColorQueryResponse,
  t: (key: string) => string,
): string {
  if (result.reason === "recipe_unavailable") {
    return t("five_color_match_recipe_unavailable")
  }
  return t("five_color_not_found_message")
}

function resolveFiveColorError(
  error: string,
  t: (key: string) => string,
): string {
  const normalized = error.trim()
  if (normalized.startsWith("five_color_")) {
    return t(normalized)
  }
  if (!normalized || RAW_STATUS_CODE_ERROR.test(normalized)) {
    return t("five_color_error_generic")
  }
  return normalized
}

function ColorMatchChip({
  label,
  hex,
  rgbText,
}: {
  label: string
  hex: string | null
  rgbText: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200/70 bg-slate-100/70 p-2 dark:border-slate-700/70 dark:bg-slate-950/40">
      <div
        className="h-9 w-12 rounded-lg border border-slate-200/80 shadow-sm dark:border-slate-700/80"
        style={{ backgroundColor: hex ?? undefined }}
      />
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-700 dark:text-slate-200">{label}</div>
        <div className="truncate font-mono text-sm font-semibold text-slate-900 dark:text-slate-50">{hex ?? "-"}</div>
        {rgbText && <div className="truncate text-[10px] text-slate-500 dark:text-slate-400">{rgbText}</div>}
      </div>
    </div>
  )
}
