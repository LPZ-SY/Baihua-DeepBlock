"""Isolated DeepBlock optimization components for the competition UI."""

from .builder import BoundaryCandidate, DeepBlock, build_overlapping_blocks
from .solver import DeepBlockConfig, DeepBlockResult, run_deepblock

__all__ = [
    "BoundaryCandidate",
    "DeepBlock",
    "DeepBlockConfig",
    "DeepBlockResult",
    "build_overlapping_blocks",
    "run_deepblock",
]
