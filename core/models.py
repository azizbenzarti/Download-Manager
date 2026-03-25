from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import time


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    FETCHING_METADATA = "fetching_metadata"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SegmentStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class SegmentInfo:
    segment_id: int
    start_byte: int
    end_byte: int
    temp_file_path: str

    downloaded_bytes: int = 0
    status: SegmentStatus = SegmentStatus.PENDING
    retries_used: int = 0
    error_message: Optional[str] = None

    def size(self) -> int:
        return self.end_byte - self.start_byte + 1

    def remaining_bytes(self) -> int:
        return max(0, self.size() - self.downloaded_bytes)

    def current_start_byte(self) -> int:
        """
        Byte position from which this segment should resume.
        """
        return self.start_byte + self.downloaded_bytes

    def is_complete(self) -> bool:
        return self.downloaded_bytes >= self.size()


@dataclass
class DownloadTask:
    task_id: str
    url: str
    output_file: str

    file_name: Optional[str] = None
    total_size: int = 0
    thread_count: int = 1
    supports_range: bool = False

    status: DownloadStatus = DownloadStatus.QUEUED
    segments: List[SegmentInfo] = field(default_factory=list)

    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    error_message: Optional[str] = None

    def total_downloaded_bytes(self) -> int:
        return sum(segment.downloaded_bytes for segment in self.segments)

    def progress_percentage(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return (self.total_downloaded_bytes() / self.total_size) * 100

    def is_complete(self) -> bool:
        if not self.segments:
            return False
        return all(segment.is_complete() for segment in self.segments)

    def mark_started(self) -> None:
        self.started_at = time.time()
        self.status = DownloadStatus.DOWNLOADING

    def mark_completed(self) -> None:
        self.completed_at = time.time()
        self.status = DownloadStatus.COMPLETED

    def mark_failed(self, message: str) -> None:
        self.error_message = message
        self.status = DownloadStatus.FAILED

    def mark_paused(self) -> None:
        self.status = DownloadStatus.PAUSED

    def mark_cancelled(self) -> None:
        self.status = DownloadStatus.CANCELLED