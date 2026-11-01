"""Bounded parallelism policy for CPU-heavy work inside one conversion task."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import threading
from typing import Iterator, Literal

from api.structured_logging import get_logger
from core.system_capacity import get_effective_cpu_capacity
from core.task_parallelism_runtime import (
    current_demand_snapshot_path,
    read_outer_demand,
)

_log = get_logger(__name__)

WorkloadKind = Literal["raster", "vector", "material"]

_ENV_BY_WORKLOAD: dict[WorkloadKind, str] = {
    "raster": "LUMINA_RASTER_PARALLELISM",
    "vector": "LUMINA_VECTOR_PARALLELISM",
    "material": "LUMINA_MATERIAL_PARALLELISM",
}
_WARNED_INVALID_VALUES: set[tuple[str, str]] = set()
_WARNING_LOCK = threading.Lock()
_WORKER_STATE = threading.local()


@dataclass(frozen=True)
class AdaptiveParallelismPlan:
    """Describe every ceiling used to select an inner worker count.

    描述选择任务内 worker 数时使用的全部上限。

    Args:
        workers: Final selected worker count. 最终 worker 数。
        requested_ceiling: Operator-requested or automatic ceiling.
            用户请求或自动请求上限。
        effective_cpu_capacity: CPU capacity visible to this process.
            当前进程可见的有效 CPU 容量。
        outer_demand: Concurrent outer tasks used for fair sharing.
            用于公平分配的外层并发任务数。
        cpu_fair_share_ceiling: CPU capacity divided by outer demand.
            CPU 容量按外层负载平分后的上限。
        work_item_ceiling: Independent item-count ceiling.
            独立工作项数量上限。
        work_unit_ceiling: Fine-grained useful-work ceiling.
            细粒度有效工作量上限。
        stage_ceiling: Stage-specific stability ceiling.
            阶段稳定性硬上限。
        limiting_reason: Stable label for the selected ceiling.
            最终限制来源的稳定标签。
        demand_snapshot_fallback: Whether configured outer capacity was used.
            是否回退使用外层配置容量。
        cpu_topology: Reliably detected CPU topology, or ``"unknown"``.
            可靠探测到的 CPU 拓扑；无法确认时为 ``"unknown"``。
        cpu_scheduling_policy: Platform policy used to derive CPU capacity.
            用于计算 CPU 容量的平台调度策略。
        performance_cpu_capacity: Fastest reported core-class capacity when
            available. 可用时记录最高性能核心等级的容量。
    """

    workers: int
    requested_ceiling: int
    effective_cpu_capacity: int
    outer_demand: int
    cpu_fair_share_ceiling: int
    work_item_ceiling: int
    work_unit_ceiling: int
    stage_ceiling: int
    limiting_reason: str
    demand_snapshot_fallback: bool
    cpu_topology: str = "unknown"
    cpu_scheduling_policy: str = "injected_or_unknown"
    performance_cpu_capacity: int | None = None


@contextmanager
def task_parallelism_worker_scope() -> Iterator[None]:
    """Mark code running inside a Lumina-managed inner worker.

    标记当前代码正在 Lumina 管理的内部 worker 中执行。嵌套调用并行度
    解析器时会强制串行，避免线程池内再次创建线程池。

    Yields:
        None while the current thread is marked as an inner worker.
        当前线程被标记为内部 worker 期间返回 ``None``。
    """

    previous_depth = int(getattr(_WORKER_STATE, "depth", 0))
    _WORKER_STATE.depth = previous_depth + 1
    try:
        yield
    finally:
        if previous_depth:
            _WORKER_STATE.depth = previous_depth
        else:
            try:
                del _WORKER_STATE.depth
            except AttributeError:
                pass


def _positive_int_or_default(raw_value: str | None, default: int) -> int:
    """Return a positive environment integer or a safe default."""

    if raw_value is None:
        return default
    try:
        parsed = int(raw_value.strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_int(value: int | None, *, default: int = 1) -> int:
    try:
        parsed = int(value) if value is not None else int(default)
    except (TypeError, ValueError, OverflowError):
        return max(1, int(default))
    return parsed if parsed > 0 else max(1, int(default))


def _warn_invalid_once(env_var: str, raw_value: str) -> None:
    """Emit one structured warning for each distinct invalid setting."""

    warning_key = (env_var, raw_value)
    with _WARNING_LOCK:
        if warning_key in _WARNED_INVALID_VALUES:
            return
        _WARNED_INVALID_VALUES.add(warning_key)

    _log.warning(
        "Invalid task parallelism setting; falling back to automatic policy",
        extra={
            "event": "task_parallelism_invalid",
            "env_var": env_var,
            "raw_value": raw_value,
            "fallback": "auto",
        },
    )


def _resolve_requested_ceiling(
    workload: WorkloadKind,
    *,
    automatic_ceiling: int,
) -> tuple[int, bool]:
    env_var = _ENV_BY_WORKLOAD[workload]
    raw_requested = os.getenv(env_var)
    normalized = (
        raw_requested.strip().lower()
        if raw_requested is not None
        else ""
    )
    if raw_requested is None or normalized == "auto":
        return automatic_ceiling, False
    if normalized == "":
        _warn_invalid_once(env_var, raw_requested)
        return automatic_ceiling, False
    try:
        requested = int(normalized)
    except ValueError:
        requested = 0
    if requested <= 0:
        _warn_invalid_once(env_var, raw_requested or "")
        return automatic_ceiling, False
    return requested, True


def resolve_task_parallelism_plan(
    workload: WorkloadKind,
    *,
    work_items: int,
    min_parallel_items: int = 2,
    hard_max_workers: int | None = 8,
    work_units: int | None = None,
    min_parallel_work_units: int = 0,
    work_units_per_worker: int | None = None,
    effective_cpu_capacity: int | None = None,
    outer_demand: int | None = None,
) -> AdaptiveParallelismPlan:
    """Resolve a safe, inspectable inner-worker plan for one task.

    根据有效 CPU、外层负载、工作量和阶段上限，生成可检查的并行计划。
    显式配置仍只是上限；任何 CPU 遥测缺失都会降低并发而不改变模型输出。

    Args:
        workload: Workload family selecting its environment override.
            工作负载类型，用于选择对应的环境变量。
        work_items: Number of independent work items available.
            可独立执行的工作项数量。
        min_parallel_items: Minimum item count required before parallel work.
            启用并行所需的最少工作项数量。
        hard_max_workers: Evidence-backed stage ceiling, defaulting to the
            legacy eight-worker limit. ``None`` adds no ceiling below
            effective CPU capacity. 阶段证据上限，默认保留旧版八 worker
            上限；``None`` 不低于有效 CPU 另设上限。
        work_units: Optional total amount of fine-grained work.
            可选的细粒度总工作量。
        min_parallel_work_units: Useful work represented by one worker tier.
            每个 worker 档位需要的有效细粒度工作量。
        work_units_per_worker: Optional useful-work density for continuous
            worker scaling. 可选的连续 worker 有效工作量密度。
        effective_cpu_capacity: Optional deterministic process CPU capacity.
            可选的确定性进程 CPU 容量。
        outer_demand: Optional deterministic active outer-task count.
            可选的确定性外层活跃任务数。

    Returns:
        An immutable plan bounded by every safety limit.
        受全部安全边界约束的不可变计划。
    """

    if workload not in _ENV_BY_WORKLOAD:
        raise ValueError(f"Unsupported workload kind: {workload!r}")

    item_count = max(0, int(work_items))
    parallel_threshold = max(2, int(min_parallel_items))

    if effective_cpu_capacity is None:
        discovered_capacity = get_effective_cpu_capacity()
        effective_cpu = max(
            1,
            int(discovered_capacity.effective_cpu_count),
        )
        cpu_topology = str(discovered_capacity.cpu_topology)
        cpu_scheduling_policy = str(
            discovered_capacity.scheduling_policy,
        )
        performance_cpu_capacity = (
            discovered_capacity.apple_performance_cpu_count
            or discovered_capacity.windows_performance_cpu_count
        )
    else:
        effective_cpu = _positive_int(effective_cpu_capacity)
        cpu_topology = "unknown"
        cpu_scheduling_policy = "injected_or_unknown"
        performance_cpu_capacity = None
    stage_ceiling = (
        effective_cpu
        if hard_max_workers is None
        else _positive_int(hard_max_workers)
    )

    default_outer_workers = min(effective_cpu, 4)
    configured_outer_workers = _positive_int_or_default(
        os.getenv("LUMINA_MAX_WORKERS"),
        default_outer_workers,
    )
    if outer_demand is None:
        demand_state = read_outer_demand(
            current_demand_snapshot_path(),
            fallback_outer_workers=configured_outer_workers,
        )
        demand = demand_state.outer_demand
        demand_snapshot_fallback = demand_state.snapshot_fallback
    else:
        demand = _positive_int(outer_demand)
        demand_snapshot_fallback = False
    cpu_fair_share = max(1, effective_cpu // demand)

    requested, request_is_explicit = _resolve_requested_ceiling(
        workload,
        automatic_ceiling=effective_cpu,
    )

    unit_count = max(0, int(work_units or 0))
    unit_threshold = max(0, int(min_parallel_work_units))
    units_per_worker = max(0, int(work_units_per_worker or 0))
    if (
        work_units is not None
        and unit_threshold > 0
        and unit_count < unit_threshold
    ):
        work_unit_ceiling = 1
    elif work_units is not None and units_per_worker > 0:
        work_unit_ceiling = max(
            1,
            (unit_count + units_per_worker - 1) // units_per_worker,
        )
    else:
        work_unit_ceiling = stage_ceiling

    work_item_ceiling = max(1, item_count)
    candidates: list[tuple[str, int]] = []
    if request_is_explicit:
        candidates.append(("requested", requested))
    candidates.extend(
        [
            ("cpu_fair_share", cpu_fair_share),
            ("effective_cpu", effective_cpu),
            ("work_items", work_item_ceiling),
            ("work_units", work_unit_ceiling),
            ("stage", stage_ceiling),
        ]
    )
    selected_workers = max(
        1,
        min(
            requested,
            cpu_fair_share,
            effective_cpu,
            work_item_ceiling,
            work_unit_ceiling,
            stage_ceiling,
        ),
    )

    if int(getattr(_WORKER_STATE, "depth", 0)) > 0:
        selected_workers = 1
        limiting_reason = "nested_worker"
    elif item_count < parallel_threshold:
        selected_workers = 1
        limiting_reason = "insufficient_items"
    elif (
        work_units is not None
        and unit_threshold > 0
        and unit_count < unit_threshold
    ):
        selected_workers = 1
        limiting_reason = "insufficient_work_units"
    else:
        limiting_reason = next(
            reason
            for reason, ceiling in candidates
            if ceiling == selected_workers
        )

    return AdaptiveParallelismPlan(
        workers=selected_workers,
        requested_ceiling=requested,
        effective_cpu_capacity=effective_cpu,
        outer_demand=demand,
        cpu_fair_share_ceiling=cpu_fair_share,
        work_item_ceiling=work_item_ceiling,
        work_unit_ceiling=work_unit_ceiling,
        stage_ceiling=stage_ceiling,
        limiting_reason=limiting_reason,
        demand_snapshot_fallback=demand_snapshot_fallback,
        cpu_topology=cpu_topology,
        cpu_scheduling_policy=cpu_scheduling_policy,
        performance_cpu_capacity=performance_cpu_capacity,
    )


def resolve_task_parallelism(
    workload: WorkloadKind,
    *,
    work_items: int,
    min_parallel_items: int = 2,
    hard_max_workers: int | None = 8,
    work_units: int | None = None,
    min_parallel_work_units: int = 0,
    work_units_per_worker: int | None = None,
    effective_cpu_capacity: int | None = None,
    outer_demand: int | None = None,
) -> int:
    """Resolve worker count while preserving the original integer API.

    保留原有整数返回接口，并由自适应计划提供最终 worker 数。

    Args:
        workload: Raster or vector workload family. 位图或矢量工作负载。
        work_items: Independent item count. 独立工作项数量。
        min_parallel_items: Minimum items required for parallel work.
            启用并行所需的最少工作项。
        hard_max_workers: Stage worker ceiling, defaulting to eight; ``None``
            removes the stage-specific cap. 阶段 worker 上限，默认八；
            ``None`` 表示不另设阶段上限。
        work_units: Optional fine-grained work amount. 可选细粒度工作量。
        min_parallel_work_units: Minimum useful work threshold.
            最小有效工作量阈值。
        work_units_per_worker: Optional useful-work density per worker.
            可选的单 worker 有效工作量密度。
        effective_cpu_capacity: Deterministic effective CPU when supplied.
            可选的确定性有效 CPU 容量。
        outer_demand: Deterministic outer demand when supplied.
            可选的确定性外层负载。

    Returns:
        A worker count of at least one. 至少为一的 worker 数。
    """

    return resolve_task_parallelism_plan(
        workload,
        work_items=work_items,
        min_parallel_items=min_parallel_items,
        hard_max_workers=hard_max_workers,
        work_units=work_units,
        min_parallel_work_units=min_parallel_work_units,
        work_units_per_worker=work_units_per_worker,
        effective_cpu_capacity=effective_cpu_capacity,
        outer_demand=outer_demand,
    ).workers
