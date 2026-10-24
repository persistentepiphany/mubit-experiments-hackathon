"""Domain graders. Each one decides for itself whether a task is its business."""

from __future__ import annotations

from labloop.graders.ppi import PPIAssureGrader


def default_graders() -> list:
    return [PPIAssureGrader()]
