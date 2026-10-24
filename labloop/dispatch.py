"""Dispatching pipeline steps to tools.

A dispatcher runs one wave of independent steps and returns, for each, either
the tool's result dict or the exception it raised. `ModalDispatcher` calls the
deployed `labloop-tools` app, using `.map()` for several calls of one tool and
`.spawn()` for the rest so the whole wave runs concurrently. `LocalDispatcher`
runs only the CPU data tools in this process, for development without Modal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from labloop import catalog

Call = tuple[str, dict[str, Any]]


class Dispatcher(Protocol):
    def run_wave(self, calls: list[Call]) -> list[dict[str, Any] | BaseException]: ...


class ModalDispatcher:
    def __init__(self, app_name: str = catalog.APP_NAME) -> None:
        import modal

        self._modal = modal
        self.app_name = app_name
        self._functions: dict[str, Any] = {}

    def _fn(self, tool: str):
        if tool not in self._functions:
            self._functions[tool] = self._modal.Function.from_name(self.app_name, tool)
        return self._functions[tool]

    def run_wave(self, calls: list[Call]) -> list[dict[str, Any] | BaseException]:
        by_tool: dict[str, list[int]] = {}
        for index, (tool, _) in enumerate(calls):
            by_tool.setdefault(tool, []).append(index)
        out: list[Any] = [None] * len(calls)
        spawned = []
        for tool, indices in by_tool.items():
            if len(indices) == 1:
                try:
                    spawned.append((indices[0], self._fn(tool).spawn(calls[indices[0]][1])))
                except Exception as error:
                    out[indices[0]] = error
        for tool, indices in by_tool.items():
            if len(indices) > 1:
                try:
                    results = list(self._fn(tool).map([calls[i][1] for i in indices], return_exceptions=True,
                                                         wrap_returned_exceptions=False))
                except Exception as error:
                    results = [error] * len(indices)
                for i, result in zip(indices, results):
                    out[i] = result
        for index, handle in spawned:
            try:
                out[index] = handle.get()
            except Exception as error:
                out[index] = error
        return out


class LocalDispatcher:
    """Runs the CPU data tools in-process; refuses model tools."""

    def __init__(self, artifacts_root: Path | None = None) -> None:
        self.artifacts_root = artifacts_root

    def run_wave(self, calls: list[Call]) -> list[dict[str, Any] | BaseException]:
        from labloop.toolkit.data import DATA_TOOLS

        out: list[Any] = []
        for tool, args in calls:
            try:
                if tool not in DATA_TOOLS:
                    raise RuntimeError(f"{tool} runs only on Modal")
                out.append(DATA_TOOLS[tool](args, self.artifacts_root))
            except Exception as error:
                out.append(error)
        return out
