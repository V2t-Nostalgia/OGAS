"""Read-only observability tools for long-running Stellaris research sessions."""

from .perf_parser import aggregate_samples, build_flame_tree, parse_perf_script

__all__ = ["aggregate_samples", "build_flame_tree", "parse_perf_script"]
