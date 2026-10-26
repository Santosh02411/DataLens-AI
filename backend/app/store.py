"""In-memory dataset store. Uploaded files are never written to disk.

Least-recently-used datasets are evicted once MAX_DATASETS_IN_MEMORY is reached.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .ingest import IngestInfo


@dataclass
class Dataset:
    id: str
    name: str
    df: pd.DataFrame
    schema: dict[str, str]
    profile: dict[str, Any]
    info: IngestInfo
    source: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    history: list[dict[str, Any]] = field(default_factory=list)
    insights: dict[str, Any] | None = None
    explanations: dict[str, str] = field(default_factory=dict)
    investigations: dict[str, Any] = field(default_factory=dict)
    formulas: list[dict[str, Any]] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "created_at": self.created_at,
            "rows": int(len(self.df)),
            "columns": [{"name": c, "type": t} for c, t in self.schema.items()],
            "file": {
                "type": self.info.file_type,
                "size_bytes": self.info.size_bytes,
                "sheet": self.info.sheet,
                "sheets": self.info.sheets,
                "delimiter": self.info.delimiter,
                "encoding": self.info.encoding,
            },
            "notes": self.info.notes,
        }


class DatasetStore:
    def __init__(self, max_items: int):
        self.max_items = max_items
        self._items: OrderedDict[str, Dataset] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, **kwargs: Any) -> Dataset:
        ds = Dataset(id=uuid.uuid4().hex[:12], **kwargs)
        with self._lock:
            self._items[ds.id] = ds
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return ds

    def get(self, dataset_id: str) -> Dataset | None:
        with self._lock:
            ds = self._items.get(dataset_id)
            if ds:
                self._items.move_to_end(dataset_id)
            return ds

    def delete(self, dataset_id: str) -> bool:
        with self._lock:
            return self._items.pop(dataset_id, None) is not None

    def record(self, ds: Dataset, entry: dict[str, Any]) -> None:
        with self._lock:
            ds.history.append(entry)
            del ds.history[:-50]
