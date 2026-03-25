# Thread worker per segment 

from __future__ import annotations

import os
import threading
from typing import Callable, Optional

from core.http_client import HttpClient
from core.models import SegmentInfo, SegmentStatus


ProgressCallback = Callable[[int, int], None]
# receives: segment_id, newly_downloaded_bytes


class SegmentWorker(threading.Thread):
    """
    Downloads a single segment into a temp file.

    Responsibilities:
    - download exactly one byte range
    - write to segment temp file
    - support resume from partially downloaded temp file
    - update SegmentInfo state
    - notify caller of progress
    """

    def __init__(
        self,
        url: str,
        segment: SegmentInfo,
        http_client: HttpClient,
        chunk_size: int = 8192,
        max_retries: int = 3,
        progress_callback: Optional[ProgressCallback] = None,
        pause_event: Optional[threading.Event] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        super().__init__()
        self.url = url
        self.segment = segment
        self.http_client = http_client
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.progress_callback = progress_callback
        self.pause_event = pause_event
        self.stop_event = stop_event

    def run(self) -> None:
        attempts = 0

        while attempts <= self.max_retries:
            try:
                if self.stop_event and self.stop_event.is_set():
                    self.segment.status = SegmentStatus.PAUSED
                    return

                self._download_segment()
                self.segment.status = SegmentStatus.COMPLETED
                self.segment.error_message = None
                return

            except Exception as exc:
                attempts += 1
                self.segment.retries_used = attempts
                self.segment.error_message = str(exc)

                if self.stop_event and self.stop_event.is_set():
                    self.segment.status = SegmentStatus.PAUSED
                    return

                if attempts > self.max_retries:
                    self.segment.status = SegmentStatus.FAILED
                    return

                self.segment.status = SegmentStatus.PENDING

    def _download_segment(self) -> None:
        os.makedirs(os.path.dirname(self.segment.temp_file_path), exist_ok=True)

        existing_size = self._get_existing_temp_file_size()
        expected_size = self.segment.size()

        # If temp file already fully exists, mark complete immediately.
        if existing_size >= expected_size:
            self.segment.downloaded_bytes = expected_size
            self.segment.status = SegmentStatus.COMPLETED
            return

        # Resume support
        self.segment.downloaded_bytes = existing_size
        resume_start = self.segment.current_start_byte()

        if resume_start > self.segment.end_byte:
            self.segment.downloaded_bytes = expected_size
            self.segment.status = SegmentStatus.COMPLETED
            return

        self.segment.status = SegmentStatus.DOWNLOADING

        with open(self.segment.temp_file_path, "ab") as temp_file:
            for chunk in self.http_client.stream_range(
                url=self.url,
                start_byte=resume_start,
                end_byte=self.segment.end_byte,
                chunk_size=self.chunk_size,
            ):
                if self.stop_event and self.stop_event.is_set():
                    self.segment.status = SegmentStatus.PAUSED
                    return

                while self.pause_event and self.pause_event.is_set():
                    self.segment.status = SegmentStatus.PAUSED
                    if self.stop_event and self.stop_event.is_set():
                        return

                temp_file.write(chunk)
                temp_file.flush()

                bytes_written = len(chunk)
                self.segment.downloaded_bytes += bytes_written

                if self.progress_callback:
                    self.progress_callback(self.segment.segment_id, bytes_written)

        if self.segment.is_complete():
            self.segment.status = SegmentStatus.COMPLETED
        else:
            raise IOError(
                f"Segment {self.segment.segment_id} incomplete after download. "
                f"Downloaded {self.segment.downloaded_bytes}/{self.segment.size()} bytes."
            )

    def _get_existing_temp_file_size(self) -> int:
        if os.path.exists(self.segment.temp_file_path):
            return os.path.getsize(self.segment.temp_file_path)
        return 0