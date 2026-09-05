"""Shared status vocabulary for dependency checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DependencyState = Literal["up", "down", "disabled"]


@dataclass(frozen=True)
class DependencyStatus:
    """Result of a dependency health probe."""

    status: DependencyState
    detail: str | None = None

    @property
    def is_failure(self) -> bool:
        """A disabled dependency is a configuration choice, not a failure."""
        return self.status == "down"
