"""Where run reports are kept.

A store takes the files `labloop.reporting.build_report` returns and writes
them under one run id. The Volume store always runs; the Supabase store is
added when its URL and service-role key are present in the environment. A
store that cannot write raises `ReportStoreError` rather than returning a
partial result, and no store ever puts its key in a message or a repr.
"""

from __future__ import annotations

import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json", ".png": "image/png",
                 ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


class ReportStoreError(RuntimeError):
    pass


class ReportStore(Protocol):
    def put(self, run_id: str, files: dict[str, bytes]) -> dict: ...


def content_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return CONTENT_TYPES.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def _check(run_id: str, files: dict[str, bytes]) -> None:
    if not SAFE_RUN_ID.match(run_id or ""):
        raise ReportStoreError(f"invalid run id {run_id!r}")
    for name in files:
        parts = name.split("/")
        if not name or name.startswith("/") or "\\" in name or any(p in ("", ".", "..") for p in parts):
            raise ReportStoreError(f"invalid report file name {name!r}")


@dataclass
class VolumeReportStore:
    """Writes files under `root/<run_id>/` and returns their paths relative to `root`."""

    root: Path

    def put(self, run_id: str, files: dict[str, bytes]) -> dict:
        _check(run_id, files)
        base = Path(self.root) / run_id
        urls = {}
        for name, data in files.items():
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
            urls[name] = f"{run_id}/{name}"
        return {"location": str(base), "urls": urls}


@dataclass
class SupabaseReportStore:
    """Uploads files to a Supabase Storage bucket and returns their public URLs."""

    url: str
    key: str = field(repr=False)
    bucket: str = "labloop-reports"
    timeout: float = 60.0

    def __post_init__(self) -> None:
        self.url = self.url.rstrip("/")
        if not self.url.startswith(("https://", "http://")):
            raise ReportStoreError("SUPABASE_URL must start with https:// or http://")
        if not self.key:
            raise ReportStoreError("the Supabase service-role key is empty")

    def _path(self, run_id: str, name: str) -> str:
        return "/".join(urllib.parse.quote(p, safe="") for p in [self.bucket, run_id, *name.split("/")])

    def put(self, run_id: str, files: dict[str, bytes]) -> dict:
        _check(run_id, files)
        urls = {}
        for name, data in files.items():
            path = self._path(run_id, name)
            request = urllib.request.Request(
                f"{self.url}/storage/v1/object/{path}", data=data, method="POST",
                headers={"Authorization": f"Bearer {self.key}", "apikey": self.key, "x-upsert": "true",
                         "Content-Type": content_type(name), "Cache-Control": "no-cache"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    status = getattr(response, "status", 200)
                    if status >= 300:
                        raise ReportStoreError(f"Supabase upload of {name} returned HTTP {status}")
            except urllib.error.HTTPError as error:
                body = error.read(300).decode("utf-8", "replace") if error.fp else ""
                raise ReportStoreError(f"Supabase upload of {name} to bucket {self.bucket} failed with "
                                       f"HTTP {error.code}: {body.replace(self.key, '***')}") from None
            except urllib.error.URLError as error:
                raise ReportStoreError(f"Supabase upload of {name} could not reach {self.url}: "
                                       f"{error.reason}") from None
            urls[name] = f"{self.url}/storage/v1/object/public/{path}"
        return {"location": f"supabase://{self.bucket}/{run_id}", "urls": urls}


def from_env(root: Path) -> list[ReportStore]:
    """The Volume store under `root`, plus Supabase when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set."""
    stores: list[ReportStore] = [VolumeReportStore(Path(root))]
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        stores.append(SupabaseReportStore(url, key, os.environ.get("SUPABASE_REPORTS_BUCKET") or "labloop-reports"))
    return stores
