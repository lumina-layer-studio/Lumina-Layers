"""Lumina Studio API — Response Pydantic models.
Lumina Studio API — 响应 Pydantic 数据模型。

All API endpoint response schemas are defined here.
所有 API 端点的响应 Schema 均在此定义。
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from api.schemas.dynamic_material import DynamicMaterialResultResponse
from api.schemas.converter import RecipeOverrideItem, SelectionDocumentResponse
from api.schemas.lut import (
    LutCoverageStatsResponse,
    LutHullPoint,
    LutPlotPoint,
    LutPlotPoint3D,
    PaletteEntrySchema,
)

_MATERIAL_PATH_RESPONSE_KEYS = frozenset(
    {"archive_path", "stage_a_params_path", "cache_file_path"}
)


def public_material_response_item(item: dict[str, object]) -> dict[str, object]:
    """Return a material response item without server-local paths.
    返回不包含服务端本地路径的耗材响应项。
    """
    return {
        key: value
        for key, value in item.items()
        if key not in _MATERIAL_PATH_RESPONSE_KEYS
    }


class _NoPublic3mfDiskPathMixin(BaseModel):
    """Redact server-local generated 3MF paths from public responses.
    从公开响应中移除服务器本地生成 3MF 路径。
    """

    @field_validator("threemf_disk_path", mode="before", check_fields=False)
    @classmethod
    def _redact_threemf_disk_path(cls, _value: object) -> None:
        return None


class CalibrationResponse(_NoPublic3mfDiskPathMixin):
    """校准板生成响应。"""

    status: str
    message: str
    download_url: str
    preview_url: Optional[str] = None
    layer_urls: Optional[list[str]] = None
    threemf_disk_path: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class SingleStageJobResponse(BaseModel):
    """Single-stage job summary."""

    color: str
    color_name: str
    material: str
    substrate_id: str
    substrate_display_name: str
    filename: str


class SingleStageCoverageResponse(BaseModel):
    """Coverage summary per substrate."""

    substrate_id: str
    colors: list[str]


class SingleStageDatasetItemResponse(BaseModel):
    """Dataset summary for a single substrate/color pair."""

    substrate_id: str
    color_name: str
    image_count: int = 0
    label_count: Optional[int] = None
    calibration: Optional[dict[str, Any]] = None


class SingleStageDatasetSummaryResponse(BaseModel):
    """Aggregate single-stage dataset summary."""

    substrate_count: int
    color_count: int
    dataset_count: int
    image_count: int
    label_count: Optional[int] = None
    substrates: list[str] = Field(default_factory=list)
    coverage: list[SingleStageCoverageResponse] = Field(default_factory=list)
    datasets: list[SingleStageDatasetItemResponse] = Field(default_factory=list)
    uploaded_dataset: Optional[dict[str, Any]] = None


class StageAFitSummaryResponse(BaseModel):
    """Summary of a completed Stage A fit."""

    substrate_count: int
    channel_count: int
    substrates: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    overall_validation: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class SingleStageKitResponse(BaseModel):
    """Single-stage kit generation response."""

    status: str
    message: str
    kit_download_url: str
    preview_url: Optional[str] = None
    manifest_url: str
    jobs: list[SingleStageJobResponse] = Field(default_factory=list)


class SingleStageExtractResponse(BaseModel):
    """Single-stage dataset extraction response."""

    session_id: str
    status: str
    message: str
    stage_json_url: str
    warnings: list[str] = Field(default_factory=list)
    dataset_summary: SingleStageDatasetSummaryResponse


class StageAFitResponse(BaseModel):
    """Stage A fitting response."""

    status: str
    message: str
    stage_a_params_url: str
    fit_summary: StageAFitSummaryResponse


class GradientCardSampleBoxResponse(BaseModel):
    """Warped sample ROI geometry for gradient-card extraction."""

    row: int
    col: int
    x: int
    y: int
    width: int
    height: int
    thickness_layers: int


class GradientCardMaterialSummaryResponse(BaseModel):
    """Summary of extracted gradient-card material data."""

    sample_count: int
    per_substrate_sample_count: int
    grid_rows: int
    grid_cols: int
    layer_height_mm: float
    warp_width_px: int | None = None
    warp_height_px: int | None = None
    thickness_layers: list[int] = Field(default_factory=list)
    sample_boxes: list[GradientCardSampleBoxResponse] = Field(default_factory=list)
    white_zero_rgb: list[int] = Field(default_factory=list)
    black_zero_rgb: list[int] = Field(default_factory=list)
    estimated_rgb: list[int] = Field(default_factory=list)
    estimated_k: list[float] = Field(default_factory=list)


class AggregationRunScoreResponse(BaseModel):
    """Per-run diagnostic score in the multi-run selection block.
    多 run 选择诊断中单个 run 的评分信息。

    Mirrors :func:`_select_runs_for_refit`'s ``run_scores`` entries so the
    frontend can render a per-run breakdown without re-implementing the
    bias scoring logic.
    """

    index: int
    is_fresh: bool = False
    bias_flag_count: int = 0
    bias_flags: list[str] = Field(default_factory=list)
    structural_flag_count: int = 0
    structural_flags: list[str] = Field(default_factory=list)
    white_c0_avg: float | None = None
    image_source: str | None = None
    cross_val_rmse: float | None = None


class AggregationExcludedRunResponse(BaseModel):
    """One run excluded from the joint refit, with reason and flags."""

    index: int
    reason: str
    bias_flags: list[str] = Field(default_factory=list)
    structural_flags: list[str] = Field(default_factory=list)
    cross_val_rmse: float | None = None


class AggregationSelectionResponse(BaseModel):
    """Full selection diagnostic block for the multi-run aggregator.
    多 run 聚合的完整选择诊断块。

    Surfaced to the frontend so the "merge diagnostics" panel can
    explain which runs participated in the joint refit and why others
    were dropped (bias filter or cross-val ranking).
    """

    selected_indices: list[int] = Field(default_factory=list)
    excluded_runs: list[AggregationExcludedRunResponse] = Field(default_factory=list)
    selection_strategy: str = "bias_filter_v1"
    run_scores: list[AggregationRunScoreResponse] = Field(default_factory=list)
    fresh_index: int | None = None


class SavedMaterialSummaryResponse(BaseModel):
    """Public summary of a saved material archive.
    已保存耗材档案的公开摘要。

    Server-side archive paths stay internal. Public callers receive stable
    directory identifiers and temporary file URLs from enclosing responses.
    """

    material_name: str
    directory_name: str
    brand: str | None = None
    verification_count: int = 1
    created_at: str | None = None
    updated_at: str | None = None
    # Aggregation diagnostics carried alongside the identity fields so a
    # single response payload covers both "where is the file" and "how
    # was it merged". Both are optional: legacy archives or single-run
    # saves may omit them.
    # 聚合诊断信息附在身份字段旁，单一响应覆盖"文件在哪"和"如何合并"。
    aggregation_method: str | None = None
    aggregation_selection: AggregationSelectionResponse | None = None


class OrientationCandidateResponse(BaseModel):
    """One orientation candidate in the ranking."""

    white_orientation: str
    black_orientation: str
    anchor_penalty: float = 0.0
    mean_delta_e: float
    rmse_linear: float
    max_delta_e: float


class SubstrateOrientationInfoResponse(BaseModel):
    """Per-substrate orientation diagnostics.
    单基底方向诊断信息。

    Surfaced to the frontend so the user can tell when the auto-detector
    fell back to ``identity`` due to a flat (low-signal) substrate, or when
    a manual override is currently in effect.
    """

    signal_strength: float = 0.0
    flat: bool = False
    manual_override: str | None = None
    locked_to: str | None = None


class OrientationRankingResponse(BaseModel):
    """Orientation detection reliability ranking."""

    orientation_reliable: bool
    delta_e_gap: float
    top_candidates: list[OrientationCandidateResponse] = Field(default_factory=list)
    white_signal_strength: float | None = None
    black_signal_strength: float | None = None
    white_orientation_info: SubstrateOrientationInfoResponse | None = None
    black_orientation_info: SubstrateOrientationInfoResponse | None = None


class GradientCardStageAExtractResponse(BaseModel):
    """Gradient-card Stage A extraction response."""

    session_id: str
    status: str
    message: str
    stage_a_params_url: str
    white_warp_preview_url: str | None = None
    black_warp_preview_url: str | None = None
    fit_summary: StageAFitSummaryResponse
    material_summary: GradientCardMaterialSummaryResponse
    orientation_ranking: OrientationRankingResponse | None = None
    warnings: list[str] = Field(default_factory=list)


class GradientCardMaterialSaveResponse(BaseModel):
    """Gradient-card material archive save response."""

    status: str
    message: str
    material_file_url: str
    stage_a_params_url: str
    material_summary: SavedMaterialSummaryResponse


class GradientCardMaterialDeleteResponse(BaseModel):
    """Gradient-card material archive delete response."""

    status: str
    message: str
    directory_name: str
    material_name: str


class GradientCardMaterialUpdateResponse(BaseModel):
    """Gradient-card material archive metadata update response."""

    status: str
    message: str
    material: "SavedMaterialLibraryItemResponse"


class SavedMaterialVerificationHistoryItemResponse(BaseModel):
    """Summary row for a single saved material verification run."""

    verification_index: int
    captured_at: str | None = None
    mean_delta_e: float | None = None
    rmse_linear: float | None = None
    estimated_rgb: list[int] = Field(default_factory=list)
    estimated_k: list[float] = Field(default_factory=list)
    e_values: list[float] = Field(default_factory=list)
    k_values: list[float] = Field(default_factory=list)
    white_c0_values: list[float] = Field(default_factory=list)
    black_c0_values: list[float] = Field(default_factory=list)
    white_detected_orientation: str | None = None
    black_detected_orientation: str | None = None


class SavedMaterialLibraryItemResponse(BaseModel):
    """Public library row for a saved Stage A material archive.
    已保存 Stage A 耗材档案的公开列表行。
    """

    material_name: str
    directory_name: str
    brand: str | None = None
    material_type: str | None = None
    material_type_source: Literal["archive", "legacy_name"] | None = None
    material_product_id: str | None = None
    material_profile_id: str | None = None
    contributor_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    material_file_url: str | None = None
    stage_a_params_url: str | None = None
    estimated_rgb: list[int] = Field(default_factory=list)
    layer_height_mm: float | None = None
    mean_delta_e: float | None = None
    verification_count: int = 1
    verification_history: list[SavedMaterialVerificationHistoryItemResponse] = Field(default_factory=list)
    # Material usage statistics (sidecar-backed, best-effort).
    # 耗材使用次数（边车文件支撑，缺失时回退为 0）。
    usage_total: int = 0
    usage_by_color_mode: dict[str, int] = Field(default_factory=dict)
    usage_last_used_at: str | None = None
    usage_last_used_color_mode: str | None = None
    sync_material_id: str | None = None
    sync_revision_id: str | None = None
    sync_channel: str | None = None
    sync_official: bool = False


class GradientCardMaterialLibraryResponse(BaseModel):
    """Saved gradient-card material archive library response."""

    status: str
    message: str
    materials: list[SavedMaterialLibraryItemResponse] = Field(default_factory=list)


class GradientCardMaterialBulkExportResponse(BaseModel):
    """Saved gradient-card material archive bulk export response."""

    status: str
    message: str
    download_url: str
    filename: str
    exported_count: int
    exported_directory_names: list[str] = Field(default_factory=list)


class GradientCardMaterialBulkImportResponse(BaseModel):
    """Saved gradient-card material archive bulk import response."""

    status: str
    message: str
    imported_count: int
    imported_materials: list[SavedMaterialSummaryResponse] = Field(default_factory=list)


class MaterialSyncRevisionResponse(BaseModel):
    revision_id: str
    installed_at: str | None = None


class MaterialSyncInstalledEntryResponse(BaseModel):
    """One material package recorded in the local sync index.
    本地同步索引记录的单个耗材包。
    """

    material_id: str
    revision_id: str
    content_hash: str
    channel: str
    source: str
    local_directory: str
    display_brand: str
    display_name: str
    installed_at: str | None = None
    updated_at: str | None = None
    local_exists: bool = False
    material_file_exists: bool = False
    available_revisions: list[str] = Field(default_factory=list)
    revision_history: list[MaterialSyncRevisionResponse] = Field(default_factory=list)


class MaterialSyncStatusResponse(BaseModel):
    """Local material sync-index status response.
    本地耗材同步索引状态响应。
    """

    status: str
    message: str
    schema_version: str
    index_state: Literal["missing", "ready", "invalid"]
    last_sync_at: str | None = None
    registries: dict[str, Any] = Field(default_factory=dict)
    installed_count: int = 0
    installed: list[MaterialSyncInstalledEntryResponse] = Field(default_factory=list)
    local_overrides_count: int = 0


class MaterialSyncInstallResponse(BaseModel):
    """Local material package install response.
    本地耗材包安装响应。
    """

    status: str
    message: str
    installed_count: int
    installed_materials: list[SavedMaterialSummaryResponse] = Field(default_factory=list)


class MaterialSyncRefreshFailureResponse(BaseModel):
    """One package-level failure during read-only material Registry refresh.
    耗材 Registry 只读刷新中的单个包级失败。
    """

    material_id: str = ""
    revision_id: str = ""
    package_url: str = ""
    error: str


class MaterialSyncRefreshResponse(BaseModel):
    """Read-only material Registry refresh response.
    耗材 Registry 只读刷新响应。
    """

    status: str
    message: str
    registry_url: str
    channels: list[str] = Field(default_factory=list)
    checked_count: int
    installed_count: int
    skipped_count: int
    failed_count: int
    installed_materials: list[SavedMaterialSummaryResponse] = Field(default_factory=list)
    failures: list[MaterialSyncRefreshFailureResponse] = Field(default_factory=list)


class MaterialSyncRollbackResponse(BaseModel):
    """Local synced material rollback response.
    本地已同步耗材回滚响应。
    """

    status: str
    message: str
    material_id: str
    revision_id: str
    content_hash: str
    channel: str
    local_directory: str


class MaterialRegistryCatalogEntryResponse(BaseModel):
    """One published material package revision in the read-only Registry catalog.
    只读 Registry catalog 中的单个已发布耗材包 revision。
    """

    material_id: str
    revision_id: str
    content_hash: str
    channel: str
    visibility: str
    local_directory: str
    display: dict[str, Any] = Field(default_factory=dict)
    compatibility: dict[str, Any] = Field(default_factory=dict)
    package_url: str
    package_sha256: str
    package_bytes: int
    card_metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Public card projection from the Registry (fit error, layer height, "
            "verification count). Registry 公开卡片元数据（拟合误差、层高、验证次数）。"
        ),
    )


class MaterialRegistryCatalogResponse(BaseModel):
    """Read-only material Registry catalog response.
    只读耗材 Registry catalog 响应。
    """

    schema_version: str
    channels: list[str] = Field(default_factory=list)
    count: int
    total_count: int | None = None
    offset: int = 0
    limit: int | None = None
    materials: list[MaterialRegistryCatalogEntryResponse] = Field(default_factory=list)


class MaterialRegistryPackageMutationResponse(BaseModel):
    """Registry package upload/approval response.
    Registry 耗材包上传/审批响应。
    """

    status: str
    message: str
    channel: str
    package_path: str
    package_url: str
    package_sha256: str
    package_bytes: int
    materials: list[MaterialRegistryCatalogEntryResponse] = Field(default_factory=list)


class MaterialSolverCacheEntryResponse(BaseModel):
    """Metadata for a single persisted material-solver cache entry.
    单个耗材求解器缓存条目的元数据。

    The ``palette_fingerprint`` identifies which saved materials were combined.
    ``total_combinations`` and ``valid_cell_count`` describe the enumeration
    coverage; ``mean_delta_e`` / ``max_delta_e`` summarise bucket-center quality.
    """

    palette_hash: str
    material_directory_names: list[str] = Field(default_factory=list)
    layer_count: int
    layer_height_mm: float
    substrate: str
    grid_resolution: int
    total_combinations: int
    valid_cell_count: int
    total_cell_count: int
    mean_delta_e: float
    max_delta_e: float
    build_time_seconds: float
    built_at: str | None = None
    cache_file_size_bytes: int = 0


class MaterialSolverCacheStatusResponse(BaseModel):
    """Status check for a specific ``(palette, N, t, substrate)`` combination.
    针对指定 ``(调色板, 层数, 层厚, 基底)`` 组合的缓存状态。

    ``cached`` is ``True`` when a compatible cache exists on disk; in that
    case ``entry`` carries the loaded metadata. Otherwise ``entry`` is ``None``
    and the caller should call the build endpoint to create it.
    """

    status: str
    message: str
    cached: bool
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    entry: MaterialSolverCacheEntryResponse | None = None


class MaterialSolverCacheBuildResponse(BaseModel):
    """Response after an explicit cache build.
    显式构建缓存后的响应。
    """

    status: str
    message: str
    entry: MaterialSolverCacheEntryResponse


class MaterialSolverCacheListResponse(BaseModel):
    """Listing response for all persisted solver caches.
    所有已持久化求解器缓存的列表响应。
    """

    status: str
    message: str
    entries: list[MaterialSolverCacheEntryResponse] = Field(default_factory=list)


class MaterialRecipeLayerResponse(BaseModel):
    """One layer in a forward-simulated material recipe.
    正向模拟配方中的一层。
    """

    layer_index: int = Field(..., description="0-based layer index, bottom to top.")
    directory_name: str = Field(..., description="Saved material directory name.")
    material_name: str = Field(..., description="Display material name.")
    estimated_rgb: list[int] = Field(
        ...,
        description="Display sRGB [R, G, B] for the material itself, not the stack.",
    )
    estimated_hex: str = Field(..., description="Display sRGB hex for the material itself.")


class MaterialRecipePreviewResponse(BaseModel):
    """Forward-model prediction of a stacked-material recipe.
    叠层耗材配方的正向预测响应。
    """

    status: str = Field("ok", description="Status indicator.")
    layer_count: int = Field(..., description="Number of layers in the recipe.")
    layer_height_mm: float = Field(..., description="Per-layer thickness in millimeters.")
    substrate: str = Field(..., description="Substrate identifier ('white' or 'black').")
    predicted_rgb: list[int] = Field(
        ...,
        description="Predicted stacked color as sRGB [R, G, B] in [0, 255].",
    )
    predicted_hex: str = Field(..., description="Predicted stacked color as #RRGGBB hex.")
    layers: list[MaterialRecipeLayerResponse] = Field(
        default_factory=list,
        description="Per-layer detail in the requested stacking order.",
    )


class MaterialColorSuggestionItem(BaseModel):
    """One achievable-color candidate returned by the suggester.
    颜色建议器返回的一个可达色候选。

    ``hex`` / ``rgb`` describe the predicted sRGB of the candidate; ``recipe``
    is the per-layer material index array (bottom-to-top), using the same
    ``material_directory_names`` order the caller submitted. ``recipe_display``
    is a short human-readable representation (e.g. ``"[0,2,1,2,0]"``) suitable
    for tooltips.
    """

    hex: str
    rgb: list[int]
    delta_e: float
    recipe: list[int]
    recipe_display: str


class MaterialColorSuggestionsResponse(BaseModel):
    """Response for the "suggest achievable colors near target" endpoint.
    "为目标色推荐可达近似色" 接口的响应。

    ``source`` is ``"cache"`` when a persisted ``MaterialSolverCache`` served
    the query, ``"runtime"`` when the persisted hybrid candidate runtime served
    it, or ``"mitm"`` when the MITM fallback ran in-process. The frontend uses
    this to decide whether to nudge the user to build reusable solver data.
    """

    status: str
    message: str
    source: str
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    target_hex: str
    target_rgb: list[int]
    suggestions: list[MaterialColorSuggestionItem] = Field(default_factory=list)


class MaterialSolverCacheDeleteResponse(BaseModel):
    """Delete response for a solver cache entry.
    求解器缓存条目的删除响应。
    """

    status: str
    message: str
    deleted: bool
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str


class MaterialSolverRuntimeEntryResponse(BaseModel):
    """Metadata for one persisted hybrid material runtime.
    单个已持久化 hybrid 耗材运行时的元数据。
    """

    palette_hash: str
    material_directory_names: list[str] = Field(default_factory=list)
    layer_count: int
    layer_height_mm: float
    substrate: str
    mode: str
    candidate_budget: int
    candidate_count: int
    candidate_pool_multiplier: int
    batch_recipe_count: int
    lab_grid_resolution: int
    seed: int
    inverse_refinement_enabled: bool
    built_at: str | None = None
    cache_file_size_bytes: int = 0


class MaterialSolverRuntimeStatusResponse(BaseModel):
    """Status for a hybrid material runtime combination.
    hybrid 耗材运行时组合状态。
    """

    status: str
    message: str
    cached: bool
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    candidate_budget: int
    entry: MaterialSolverRuntimeEntryResponse | None = None


class MaterialSolverRuntimeBuildResponse(BaseModel):
    """Response after explicit hybrid runtime build.
    显式构建 hybrid runtime 后的响应。
    """

    status: str
    message: str
    entry: MaterialSolverRuntimeEntryResponse


class MaterialSolverRuntimeDeleteResponse(BaseModel):
    """Delete response for a hybrid runtime entry.
    hybrid runtime 条目的删除响应。
    """

    status: str
    message: str
    deleted: bool
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    candidate_budget: int


class MaterialSolverRuntimeDetailsResponse(BaseModel):
    """Visualization payload for a hybrid runtime entry.
    hybrid runtime 条目的可视化载荷。
    """

    status: str
    message: str
    palette_hash: str
    material_directory_names: list[str] = Field(default_factory=list)
    layer_count: int
    layer_height_mm: float
    substrate: str
    grid_resolution: int
    valid_cell_count: int
    total_cell_count: int
    candidate_budget: int
    candidate_count: int
    coverage_stats: LutCoverageStatsResponse
    lab_points: list[LutPlotPoint] = Field(default_factory=list)
    lab_points_3d: list[LutPlotPoint3D] = Field(default_factory=list)
    lab_hull: list[LutHullPoint] = Field(default_factory=list)
    rgb_points: list[LutPlotPoint] = Field(default_factory=list)


class MaterialSolverCacheDetailsResponse(BaseModel):
    """Visualization payload for a single solver-cache entry.
    单份求解器缓存的可视化载荷。

    Mirrors the subset of :class:`LutDetailsResponse` fields the four scatter
    charts (Lab a*/b*, RGB isometric projection, Hue × Lightness, Hue ×
    Saturation) consume so the frontend can reuse the same
    ``LutScatterChart`` / ``LabPointCloud3D`` components verbatim.

    与 LUT 详情响应字段同构（取四张散点图所需子集），让前端复用 LUT 详情的
    ``LutScatterChart`` / ``LabPointCloud3D`` 组件。
    """

    status: str
    message: str
    palette_hash: str
    material_directory_names: list[str] = Field(default_factory=list)
    layer_count: int
    layer_height_mm: float
    substrate: str
    grid_resolution: int
    valid_cell_count: int
    total_cell_count: int
    coverage_stats: LutCoverageStatsResponse
    lab_points: list[LutPlotPoint] = Field(default_factory=list)
    lab_points_3d: list[LutPlotPoint3D] = Field(default_factory=list)
    lab_hull: list[LutHullPoint] = Field(default_factory=list)
    rgb_points: list[LutPlotPoint] = Field(default_factory=list)


class RecipePredictResponse(BaseModel):
    """Recipe color prediction response."""

    status: str
    message: str
    rgb: list[int] = Field(default_factory=list)
    lab: list[float] = Field(default_factory=list)
    source: str
    runtime_mode_key: str | None = None


class SimilarRecipeItem(BaseModel):
    """One suggested recipe ranked by CIEDE2000 distance.
    按 CIEDE2000 色差排序的一条推荐配方。"""

    hex: str
    rgb: list[int]
    delta_e00: float
    recipe: list[int]
    source: Literal["lut", "predictive", "image"]
    in_image: bool = False


class SimilarRecipesResponse(BaseModel):
    """Similar-recipe suggestions for one target colour.
    单个目标颜色的相似配方推荐结果。"""

    status: str = "ok"
    target_color: str
    layer_order: str = "Top2Bottom"
    predictive_available: bool = False
    items: list[SimilarRecipeItem] = Field(default_factory=list)


class RecipeOverrideApplyResponse(DynamicMaterialResultResponse):
    """Recipe override apply response."""

    status: str
    message: str
    preview_url: str
    preview_glb_url: str | None = None
    rgb: list[int] = Field(default_factory=list)
    lab: list[float] = Field(default_factory=list)
    source: str
    runtime_mode_key: str | None = None
    override_count: int = 0
    recipe_overrides: list[RecipeOverrideItem] = Field(default_factory=list)
    can_undo: bool = False
    can_redo: bool = False
    selection: SelectionDocumentResponse | None = None


class RegionRecipeEntry(BaseModel):
    """Per-region current recipe payload.
    单个区域的当前 recipe 返回体。
    """

    region_id: str
    recipe: list[int] = Field(default_factory=list)
    color_layers: int = 0
    layer_height_mm: float = 0.08
    layer_order: str = "Top2Bottom"


class RegionRecipeResponse(BaseModel):
    """Response for ``POST /api/convert/region-recipe``.

    Carries the current per-layer material indices that the pipeline has
    already matched for each requested region, so the Custom Recipe dialog
    can pre-populate its per-layer dropdowns instead of defaulting to White.

    每个请求区域当前已匹配到的逐层材料索引，供自定义配方对话框把下拉框
    预设成该区域的真实配方，而不是默认的全白。
    """

    status: str
    message: str
    recipes: list[RegionRecipeEntry] = Field(default_factory=list)


class PerformanceTimingResponse(BaseModel):
    """Endpoint performance timings in milliseconds.

    接口性能耗时统计，单位为毫秒。
    """

    total_ms: Optional[float] = None
    upload_ms: Optional[float] = None
    worker_ms: Optional[float] = None
    endpoint_to_enqueue_ms: Optional[float] = None
    queue_wait_ms: Optional[float] = None
    worker_execution_ms: Optional[float] = None
    result_delivery_ms: Optional[float] = None
    endpoint_post_worker_ms: Optional[float] = None
    pickle_load_ms: Optional[float] = None
    segmented_glb_ms: Optional[float] = None
    palette_ms: Optional[float] = None
    overhead_ms: Optional[float] = None


class PreviewResponse(DynamicMaterialResultResponse):
    """预览生成响应。"""

    session_id: str
    status: str
    message: str
    preview_url: str
    preview_glb_url: Optional[str] = None
    lut_match_mode: Optional[str] = None
    lut_match_info: Optional[dict[str, Any]] = None
    palette: list[dict]
    dimensions: dict
    contours: Optional[dict[str, list[list[list[float]]]]] = None
    warnings: list[str] = Field(default_factory=list)
    performance_timing: Optional[PerformanceTimingResponse] = None


class ColorReplaceResponse(DynamicMaterialResultResponse):
    """颜色替换响应。"""

    status: str
    message: str
    preview_url: str
    preview_3d_url: str | None = None
    replacement_count: int
    can_undo: bool = False
    can_redo: bool = False
    selection: SelectionDocumentResponse | None = None


class MergePreviewResponse(BaseModel):
    """颜色合并预览响应。"""

    status: str
    message: str
    preview_url: str
    merge_map: dict[str, str]
    quality_metric: float
    colors_before: int
    colors_after: int


class GenerateResponse(_NoPublic3mfDiskPathMixin):
    """3MF 生成响应。"""

    status: str
    message: str
    download_url: str
    preview_3d_url: Optional[str] = None
    threemf_disk_path: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    performance_timing: Optional[PerformanceTimingResponse] = None
    editor_content_revision: int | None = None
    selection_revision: int | None = None


class RecipePredictionResponse(BaseModel):
    """Predictive custom recipe color response."""

    status: str
    message: str
    rgb: list[int] = Field(default_factory=list)
    hex: str = ""
    lab: list[float] = Field(default_factory=list)
    source: str = ""
    runtime_mode_key: Optional[str] = None


class PuzzleLayoutPreviewResponse(BaseModel):
    """拼图布局预览响应。"""

    status: str
    message: str
    overlay_url: str
    piece_count: int
    grid_cols: int
    grid_rows: int
    derived_piece_width_mm: float | None = None
    derived_piece_height_mm: float | None = None
    warnings: list[str] = Field(default_factory=list)
    piece_areas_mm2: list[float] = Field(default_factory=list)


class PuzzleGenerateResponse(_NoPublic3mfDiskPathMixin):
    """拼图生成响应。"""

    status: str
    message: str
    download_url: str
    threemf_disk_path: Optional[str] = None
    piece_count: int
    grid_cols: int
    grid_rows: int
    warnings: list[str] = Field(default_factory=list)
    editor_content_revision: int | None = None
    selection_revision: int | None = None


class LargeFormatGenerateResponse(BaseModel):
    """大画幅切片生成响应。"""

    status: str
    message: str
    download_url: str
    tile_count: int
    failed_tiles: list[str] = Field(default_factory=list)
    grid_cols: int
    grid_rows: int
    warnings: list[str] = Field(default_factory=list)
    editor_content_revision: int | None = None
    selection_revision: int | None = None


class BatchItemResult(BaseModel):
    """批量转换单项结果。"""

    filename: str
    status: str
    error: Optional[str] = None
    download_url: str | None = None


class WarningEntry(BaseModel):
    """批量响应警告条目。

    Structured warning entry returned in BatchResponse.warnings.

    `code` 是稳定的机器可读标识（例如 ``"plate-overflow"``），前端 SHALL
    根据 `code` 选择对应的 i18n key 渲染本地化文案；`message` 仅是后端
    默认 locale 渲染的可读文本，作为前端 i18n key 缺失时的 fallback，
    前端不应依赖 `message` 文本判断警告类型。

    `code` is the stable machine-readable identifier; the frontend MUST
    pick its i18n key by `code`, never by parsing `message`. `message`
    is only a server-rendered human-readable fallback.
    """

    code: Literal["plate-overflow"] | str = Field(
        ..., description="Stable machine-readable warning code"
    )
    message: str = Field(..., description="Server-rendered human-readable text")


class BatchPreviewItem(BaseModel):
    """单个批量预览模型条目。

    Batch preview now reuses each per-image GLB instead of baking a new
    merged GLB. The frontend places these URLs on the same virtual plate
    using the layout coordinates.
    """

    url: str
    filename: str
    tx_mm: float
    ty_mm: float
    width_mm: float
    depth_mm: float


class BatchResponse(_NoPublic3mfDiskPathMixin):
    """批量转换响应。"""

    status: str
    message: str
    download_url: str | None = None
    threemf_disk_path: str | None = None
    preview_3d_url: str | None = None
    preview_items: list[BatchPreviewItem] = Field(default_factory=list)
    results: list[BatchItemResult]
    warnings: list[WarningEntry] = Field(default_factory=list)


class LutInfo(BaseModel):
    """单个 LUT 预设信息。"""

    name: str
    color_mode: str
    path: str = Field(..., description="公开引用（非本机文件系统路径）")


class LUTListResponse(BaseModel):
    """LUT 列表响应。"""

    luts: list[LutInfo]


class WorkerPoolStatus(BaseModel):
    """Worker Pool 状态信息。"""

    healthy: bool
    max_workers: int


class HealthResponse(BaseModel):
    """健康检查响应（含 Worker Pool 状态）。"""

    status: str
    service: str = "lumina-studio"
    desktop_instance_id: Optional[str] = None
    version: str
    uptime_seconds: float
    worker_pool: WorkerPoolStatus


class ExtractResponse(BaseModel):
    """颜色提取响应。"""

    session_id: str
    workspace_session_id: str | None = None
    status: str
    message: str
    lut_download_url: str
    warp_view_url: str
    lut_preview_url: str
    default_palette: list[PaletteEntrySchema] = Field(
        default_factory=list,
        description="默认调色板数组，每项含 color、material、hex_color、color_name",
    )
    lut_layout: Optional["LutCardLayoutResponse"] = None


class ManualFixResponse(BaseModel):
    """手动修正响应。"""

    status: str
    message: str
    lut_preview_url: str
    lut_layout: Optional["LutCardLayoutResponse"] = None


class HeightmapUploadResponse(BaseModel):
    """高度图上传响应。"""

    status: str
    message: str
    thumbnail_url: str
    original_size: tuple[int, int]
    color_height_map: dict[str, float]
    warnings: list[str]


class LutColorEntry(BaseModel):
    """单个 LUT 颜色条目。"""

    hex: str
    rgb: tuple[int, int, int]


class LutCardPageResponse(BaseModel):
    """Single LUT card/page layout descriptor."""

    page_index: int
    page_label: str
    card_index: int
    card_label: str
    start_index: int
    item_count: int
    data_rows: int
    data_cols: int
    padding: int
    physical_rows: int
    physical_cols: int


class LutCardLayoutResponse(BaseModel):
    """Resolved LUT card layout."""

    color_mode: str
    total_count: int
    pages: list[LutCardPageResponse]


class LutCardCellCoordinateResponse(BaseModel):
    """Resolved coordinate for one LUT row."""

    card_index: int
    card_label: str
    page_index: int
    page_label: str
    grid_size: int
    data_rows: int
    data_cols: int
    row: int
    col: int
    data_row: int
    data_col: int
    display_row: int
    display_col: int
    physical_row: int
    physical_col: int
    row_index: int


class LutPreviewResolvedCell(BaseModel):
    """Resolved LUT preview click target."""

    cell: LutCardCellCoordinateResponse
    rgb: tuple[int, int, int]
    hex: str
    overlay_bbox: dict[str, float]


class LutColorsCardResponse(BaseModel):
    """LUT colors grouped by backend-resolved card/page."""

    page: LutCardPageResponse
    colors: list[LutColorEntry]


class LutColorsResponse(BaseModel):
    """LUT 颜色列表响应。"""

    lut_name: str
    total: int
    colors: list[LutColorEntry]
    layout: Optional[LutCardLayoutResponse] = None
    cards: list[LutColorsCardResponse] = Field(default_factory=list)


ExtractResponse.model_rebuild()
ManualFixResponse.model_rebuild()


class CropResponse(BaseModel):
    """裁剪响应。"""

    status: str
    message: str
    cropped_url: str
    width: int
    height: int


class AutoDetectColorsResponse(BaseModel):
    """自动检测推荐量化颜色数响应。"""

    recommended: int
    max_safe: int
    unique_colors: int
    complexity_score: int


class ResetReplacementsResponse(DynamicMaterialResultResponse):
    """颜色替换重置响应。"""

    status: str
    message: str
    preview_url: str
    preview_glb_url: str | None = None
    can_undo: bool = False
    can_redo: bool = False
    selection: SelectionDocumentResponse | None = None
