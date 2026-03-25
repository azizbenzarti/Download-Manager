# Progress speed

from __future__ import annotations

import time
from typing import Optional

from core.models import DownloadTask


class ProgressTracker:
    """
    Tracks overall download progress, speed, and ETA.
    """

    def __init__(self, task: DownloadTask) -> None:
        self.task = task
        self.started_at = time.time()
        self._last_update_time = self.started_at
        self._last_downloaded = task.total_downloaded_bytes()
        self._current_speed_bps = 0.0

    def update(self) -> None:
        now = time.time()
        downloaded_now = self.task.total_downloaded_bytes()

        elapsed = now - self._last_update_time
        delta_bytes = downloaded_now - self._last_downloaded

        if elapsed > 0:
            self._current_speed_bps = max(0.0, delta_bytes / elapsed)

        self._last_update_time = now
        self._last_downloaded = downloaded_now

    def get_progress_fraction(self) -> float:
        if self.task.total_size <= 0:
            return 0.0
        return min(1.0, self.task.total_downloaded_bytes() / self.task.total_size)

    def get_progress_percentage(self) -> float:
        return self.get_progress_fraction() * 100

    def get_speed_bps(self) -> float:
        return self._current_speed_bps

    def get_speed_text(self) -> str:
        return self.format_speed(self._current_speed_bps)

    def get_eta_seconds(self) -> Optional[float]:
        if self.task.total_size <= 0:
            return None
        if self._current_speed_bps <= 0:
            return None

        remaining = max(0, self.task.total_size - self.task.total_downloaded_bytes())
        return remaining / self._current_speed_bps

    def get_eta_text(self) -> str:
        eta = self.get_eta_seconds()
        if eta is None:
            return "--"
        return self.format_eta(eta)

    @staticmethod
    def format_speed(speed_bps: float) -> str:
        if speed_bps < 1024:
            return f"{speed_bps:.1f} B/s"
        if speed_bps < 1024 ** 2:
            return f"{speed_bps / 1024:.1f} KB/s"
        if speed_bps < 1024 ** 3:
            return f"{speed_bps / (1024 ** 2):.2f} MB/s"
        return f"{speed_bps / (1024 ** 3):.2f} GB/s"

    @staticmethod
    def format_eta(seconds: float) -> str:
        seconds = int(max(0, seconds))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"