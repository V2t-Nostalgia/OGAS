from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


SCHEMA = "iag.stellaris.perf_window.v1"

_HEADER = re.compile(
    r"^(?P<comm>.*?)\s+(?P<pid>\d+)(?:/(?P<tid>\d+))?\s+"
    r"(?:\[(?P<cpu>\d+)\]\s+)?(?P<time>\d+(?:\.\d+)?):\s+(?P<rest>.+)$"
)
_LOCATION = re.compile(
    r"^(?:(?P<ip>(?:0x)?[0-9a-fA-F]+)\s+)?"
    r"(?P<symbol>.*?)\s+\((?P<module>.*)\)\s*$"
)
_FRAME = re.compile(
    r"^\s+(?:(?:0x)?[0-9a-fA-F]+)\s+"
    r"(?P<symbol>.*?)\s+\((?P<module>.*)\)\s*$"
)


@dataclass(frozen=True)
class Frame:
    symbol: str
    module: str


@dataclass(frozen=True)
class PerfSample:
    comm: str
    pid: int
    tid: int
    timestamp: float
    event: str
    frames: tuple[Frame, ...]  # root -> leaf


def _clean_frame(symbol: str, module: str) -> Frame:
    symbol = symbol.strip() or "[unknown]"
    module = module.strip() or "[unknown]"
    return Frame(symbol=symbol, module=module)


def parse_perf_script(text: str) -> list[PerfSample]:
    """Parse ``perf script`` output with callchains into sampled stacks.

    A sample is evidence of on-CPU presence, not an actual function call.  The
    parser deliberately retains unknown frames rather than inventing symbols.
    """
    samples: list[PerfSample] = []
    current: dict[str, Any] | None = None

    def finish() -> None:
        nonlocal current
        if current is None:
            return
        leaf_first: list[Frame] = current["frames"]
        compact: list[Frame] = []
        for frame in leaf_first:
            if not compact or compact[-1] != frame:
                compact.append(frame)
        if compact:
            samples.append(
                PerfSample(
                    comm=current["comm"],
                    pid=current["pid"],
                    tid=current["tid"],
                    timestamp=current["timestamp"],
                    event=current["event"],
                    frames=tuple(reversed(compact)),
                )
            )
        current = None

    for raw_line in text.splitlines():
        if not raw_line.strip():
            finish()
            continue
        header = _HEADER.match(raw_line)
        if header and not raw_line[:1].isspace():
            finish()
            rest = header.group("rest")
            event, separator, location = rest.rpartition(": ")
            if not separator:
                event, location = "unknown", rest
            matched_location = _LOCATION.match(location)
            frames: list[Frame] = []
            if matched_location:
                frames.append(
                    _clean_frame(
                        matched_location.group("symbol"),
                        matched_location.group("module"),
                    )
                )
            pid = int(header.group("pid"))
            current = {
                "comm": header.group("comm").strip(),
                "pid": pid,
                "tid": int(header.group("tid") or pid),
                "timestamp": float(header.group("time")),
                "event": event.strip(),
                "frames": frames,
            }
            continue
        frame = _FRAME.match(raw_line)
        if frame and current is not None:
            current["frames"].append(
                _clean_frame(frame.group("symbol"), frame.group("module"))
            )
    finish()
    return samples


def _frame_id(frame: Frame) -> str:
    return hashlib.sha1(
        f"{frame.module}\0{frame.symbol}".encode("utf-8")
    ).hexdigest()[:16]


def _view(samples: Iterable[PerfSample], frame_table: dict[str, dict[str, str]],
          frequency_hz: int) -> dict[str, Any]:
    folded: Counter[tuple[str, ...]] = Counter()
    self_counts: Counter[str] = Counter()
    inclusive_counts: Counter[str] = Counter()
    sample_count = 0
    for sample in samples:
        ids: list[str] = []
        for frame in sample.frames:
            identifier = _frame_id(frame)
            frame_table.setdefault(
                identifier, {"symbol": frame.symbol, "module": frame.module}
            )
            ids.append(identifier)
        if not ids:
            continue
        sample_count += 1
        folded[tuple(ids)] += 1
        self_counts[ids[-1]] += 1
        inclusive_counts.update(set(ids))
    hotspots: list[dict[str, Any]] = []
    for identifier in set(self_counts) | set(inclusive_counts):
        frame = frame_table[identifier]
        self_samples = self_counts[identifier]
        inclusive_samples = inclusive_counts[identifier]
        hotspots.append(
            {
                "frame_id": identifier,
                "symbol": frame["symbol"],
                "module": frame["module"],
                "self_samples": self_samples,
                "inclusive_samples": inclusive_samples,
                "self_percent": (100.0 * self_samples / sample_count)
                if sample_count
                else 0.0,
                "inclusive_percent": (100.0 * inclusive_samples / sample_count)
                if sample_count
                else 0.0,
                "self_cpu_seconds_estimate": self_samples / frequency_hz,
                "inclusive_cpu_seconds_estimate": inclusive_samples / frequency_hz,
                "actual_call_count": None,
                "metric_kind": "sampled_on_cpu",
            }
        )
    hotspots.sort(
        key=lambda item: (
            -item["self_samples"],
            -item["inclusive_samples"],
            item["symbol"],
        )
    )
    return {
        "sample_count": sample_count,
        "estimated_on_cpu_seconds": sample_count / frequency_hz,
        "folded": [
            {"frames": list(stack), "samples": count}
            for stack, count in sorted(folded.items())
        ],
        "hotspots": hotspots,
    }


def aggregate_samples(
    samples: Iterable[PerfSample], *, frequency_hz: int, duration_seconds: float
) -> dict[str, Any]:
    if frequency_hz <= 0 or duration_seconds <= 0:
        raise ValueError("frequency_hz and duration_seconds must be positive")
    values = list(samples)
    frame_table: dict[str, dict[str, str]] = {}
    by_thread: dict[int, list[PerfSample]] = defaultdict(list)
    comm_by_thread: dict[int, str] = {}
    for sample in values:
        by_thread[sample.tid].append(sample)
        comm_by_thread[sample.tid] = sample.comm
    views: dict[str, Any] = {
        "all": _view(values, frame_table, frequency_hz),
    }
    main_samples = [sample for sample in values if sample.tid == sample.pid]
    worker_samples = [sample for sample in values if sample.tid != sample.pid]
    if main_samples:
        views["main"] = _view(main_samples, frame_table, frequency_hz)
    if worker_samples:
        views["workers"] = _view(worker_samples, frame_table, frequency_hz)
    threads: list[dict[str, Any]] = []
    for tid in sorted(by_thread):
        key = f"tid:{tid}"
        views[key] = _view(by_thread[tid], frame_table, frequency_hz)
        threads.append(
            {
                "key": key,
                "tid": tid,
                "comm": comm_by_thread[tid],
                "sample_count": views[key]["sample_count"],
                "role": "main"
                if any(sample.tid == sample.pid for sample in by_thread[tid])
                else "worker_or_auxiliary",
                "role_confidence": "exact_tid"
                if any(sample.tid == sample.pid for sample in by_thread[tid])
                else "not_classified_as_ai_without_stack_evidence",
            }
        )
    return {
        "schema": SCHEMA,
        "frequency_hz": frequency_hz,
        "duration_seconds": duration_seconds,
        "sample_count": views["all"]["sample_count"],
        "metric_kind": "sampled_on_cpu",
        "call_counts_available": False,
        "frames": frame_table,
        "threads": threads,
        "views": views,
    }


def build_flame_tree(aggregate: dict[str, Any], thread: str = "all") -> dict[str, Any]:
    views = aggregate.get("views", {})
    if thread not in views:
        raise KeyError(f"Unknown sampled thread: {thread}")
    frames = aggregate.get("frames", {})
    root: dict[str, Any] = {
        "name": "all samples" if thread == "all" else thread,
        "module": "",
        "samples": 0,
        "self_samples": 0,
        "children": {},
    }
    for folded in views[thread].get("folded", []):
        count = int(folded.get("samples", 0))
        root["samples"] += count
        node = root
        for identifier in folded.get("frames", []):
            frame = frames.get(identifier, {})
            children = node["children"]
            child = children.setdefault(
                identifier,
                {
                    "frame_id": identifier,
                    "name": frame.get("symbol", "[unknown]"),
                    "module": frame.get("module", "[unknown]"),
                    "samples": 0,
                    "self_samples": 0,
                    "children": {},
                },
            )
            child["samples"] += count
            node = child
        node["self_samples"] += count

    def serialise(node: dict[str, Any]) -> dict[str, Any]:
        result = dict(node)
        children = list(result.pop("children").values())
        result["children"] = [
            serialise(child)
            for child in sorted(children, key=lambda child: -child["samples"])
        ]
        return result

    return serialise(root)


def build_diff_flame_tree(
    baseline: dict[str, Any], comparison: dict[str, Any], thread: str = "all"
) -> dict[str, Any]:
    def folded_map(value: dict[str, Any]) -> dict[tuple[str, ...], int]:
        view = value.get("views", {}).get(thread, {})
        return {
            tuple(item.get("frames", [])): int(item.get("samples", 0))
            for item in view.get("folded", [])
        }

    baseline_folded = folded_map(baseline)
    comparison_folded = folded_map(comparison)
    frames = dict(baseline.get("frames", {}))
    frames.update(comparison.get("frames", {}))
    root: dict[str, Any] = {
        "name": "window comparison",
        "module": "",
        "baseline_samples": sum(baseline_folded.values()),
        "comparison_samples": sum(comparison_folded.values()),
        "children": {},
    }
    for stack in set(baseline_folded) | set(comparison_folded):
        before = baseline_folded.get(stack, 0)
        after = comparison_folded.get(stack, 0)
        node = root
        for identifier in stack:
            frame = frames.get(identifier, {})
            child = node["children"].setdefault(
                identifier,
                {
                    "frame_id": identifier,
                    "name": frame.get("symbol", "[unknown]"),
                    "module": frame.get("module", "[unknown]"),
                    "baseline_samples": 0,
                    "comparison_samples": 0,
                    "children": {},
                },
            )
            child["baseline_samples"] += before
            child["comparison_samples"] += after
            node = child

    def serialise(node: dict[str, Any]) -> dict[str, Any]:
        result = dict(node)
        result["delta_samples"] = (
            result["comparison_samples"] - result["baseline_samples"]
        )
        children = list(result.pop("children").values())
        result["children"] = [
            serialise(child)
            for child in sorted(
                children,
                key=lambda child: -max(
                    child["baseline_samples"], child["comparison_samples"]
                ),
            )
        ]
        return result

    return serialise(root)
