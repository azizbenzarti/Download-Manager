# Main Downlaod Manager orchestration

from __future__ import annotations

import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.assembler import FileAssembler
from core.http_client import HttpClient
from core.models import DownloadStatus, DownloadTask, SegmentInfo
from core.segment_worker import SegmentWorker


DownloadProgressCallback = Callable[[float, str, str], None]
# receives: progress_fraction (0..1), speed_text, eta_text


class DownloadManager:
    """
    Main orchestration class for downloads.

    Responsibilities:
    - fetch file metadata
    - create download task + segments
    - spawn segment workers
    - track overall progress
    - support pause/resume
    - assemble final file
    """

    def __init__(
        self,
        temp_dir: str = "temp",
        chunk_size: int = 8192,
        timeout: int = 15,
    ) -> None:
        self.temp_dir = temp_dir
        self.chunk_size = chunk_size
        self.http_client = HttpClient(timeout=timeout)
        self.assembler = FileAssembler()

        self.tasks: Dict[str, DownloadTask] = {}
        self.pause_events: Dict[str, threading.Event] = {}
        self.stop_events: Dict[str, threading.Event] = {}
        self.progress_locks: Dict[str, threading.Lock] = {}
        self.workers: Dict[str, List[SegmentWorker]] = {}
        self.last_progress_callbacks: Dict[str, Optional[DownloadProgressCallback]] = {}

    def start_download(
        self,
        url: str,
        output_path: str,
        thread_count: int = 4,
        max_retries: int = 3,
        progress_callback: Optional[DownloadProgressCallback] = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        metadata = self.http_client.get_file_metadata(url)

        total_size = int(metadata["content_length"])
        supports_range = bool(metadata["accept_ranges"])
        file_name = metadata.get("filename") or Path(output_path).name

        task = DownloadTask(
            task_id=task_id,
            url=url,
            output_file=str(Path(output_path).resolve()),
            file_name=file_name,
            total_size=total_size,
            thread_count=thread_count,
            supports_range=supports_range,
            status=DownloadStatus.QUEUED,
        )

        if supports_range and total_size > 0 and thread_count > 1:
            task.segments = self._build_segments(
                task_id=task_id,
                file_name=file_name,
                total_size=total_size,
                thread_count=thread_count,
            )
        else:
            task.segments = self._build_segments(
                task_id=task_id,
                file_name=file_name,
                total_size=total_size if total_size > 0 else 1,
                thread_count=1,
            )
            task.thread_count = 1
            task.supports_range = False

        task.mark_started()

        self.tasks[task_id] = task
        self.pause_events[task_id] = threading.Event()
        self.stop_events[task_id] = threading.Event()
        self.progress_locks[task_id] = threading.Lock()
        self.last_progress_callbacks[task_id] = progress_callback

        self._run_download(task, max_retries, progress_callback)
        return task_id

    def pause_download(self, task_id: str) -> None:
        task = self._get_task(task_id)
        self.pause_events[task_id].set()
        task.mark_paused()

    def resume_download(
        self,
        task_id: str,
        progress_callback: Optional[DownloadProgressCallback] = None,
        max_retries: int = 3,
    ) -> None:
        task = self._get_task(task_id)

        if task.status not in (DownloadStatus.PAUSED, DownloadStatus.FAILED):
            return

        self.pause_events[task_id].clear()
        self.stop_events[task_id].clear()
        task.status = DownloadStatus.DOWNLOADING
        self.last_progress_callbacks[task_id] = progress_callback

        self._run_download(task, max_retries, progress_callback)

    def get_status(self, task_id: str) -> DownloadTask:
        return self._get_task(task_id)

    def _run_download(
        self,
        task: DownloadTask,
        max_retries: int,
        progress_callback: Optional[DownloadProgressCallback],
    ) -> None:
        start_time = time.time()
        bytes_downloaded_at_start = task.total_downloaded_bytes()

        def on_segment_progress(segment_id: int, new_bytes: int) -> None:
            del segment_id, new_bytes  # not needed directly here

            if not progress_callback:
                return

            with self.progress_locks[task.task_id]:
                downloaded = task.total_downloaded_bytes()
                progress_fraction = (
                    downloaded / task.total_size if task.total_size > 0 else 0.0
                )

                elapsed = max(time.time() - start_time, 0.001)
                current_session_downloaded = max(
                    0, downloaded - bytes_downloaded_at_start
                )
                speed_bps = current_session_downloaded / elapsed

                speed_text = self._format_speed(speed_bps)

                if speed_bps > 0 and task.total_size > 0:
                    remaining = max(0, task.total_size - downloaded)
                    eta_seconds = remaining / speed_bps
                    eta_text = self._format_eta(eta_seconds)
                else:
                    eta_text = "--"

                progress_callback(progress_fraction, speed_text, eta_text)

        workers: List[SegmentWorker] = []

        for segment in task.segments:
            if segment.is_complete():
                continue

            worker = SegmentWorker(
                url=task.url,
                segment=segment,
                http_client=self.http_client,
                chunk_size=self.chunk_size,
                max_retries=max_retries,
                progress_callback=on_segment_progress,
                pause_event=self.pause_events[task.task_id],
                stop_event=self.stop_events[task.task_id],
            )
            workers.append(worker)

        self.workers[task.task_id] = workers

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join()

        if self.pause_events[task.task_id].is_set():
            task.mark_paused()
            return

        failed_segments = [s for s in task.segments if not s.is_complete()]
        if failed_segments:
            task.mark_failed("One or more segments failed to download.")
            return

        self.assembler.assemble(task.segments, task.output_file)
        self.assembler.cleanup_segments(task.segments)
        task.mark_completed()

        if progress_callback:
            progress_callback(1.0, self._format_speed(0), "00:00:00")

    def _build_segments(
        self,
        task_id: str,
        file_name: str,
        total_size: int,
        thread_count: int,
    ) -> List[SegmentInfo]:
        os.makedirs(self.temp_dir, exist_ok=True)

        thread_count = max(1, thread_count)
        segment_size = math.ceil(total_size / thread_count)

        segments: List[SegmentInfo] = []

        for i in range(thread_count):
            start_byte = i * segment_size
            end_byte = min(start_byte + segment_size - 1, total_size - 1)

            if start_byte > end_byte:
                break

            temp_file_path = os.path.join(
                self.temp_dir,
                f"{task_id}_{file_name}.part{i}",
            )

            segments.append(
                SegmentInfo(
                    segment_id=i,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    temp_file_path=temp_file_path,
                )
            )

        return segments

    def _get_task(self, task_id: str) -> DownloadTask:
        if task_id not in self.tasks:
            raise ValueError(f"Unknown task_id: {task_id}")
        return self.tasks[task_id]

    @staticmethod
    def _format_speed(speed_bps: float) -> str:
        if speed_bps < 1024:
            return f"{speed_bps:.1f} B/s"
        if speed_bps < 1024 ** 2:
            return f"{speed_bps / 1024:.1f} KB/s"
        if speed_bps < 1024 ** 3:
            return f"{speed_bps / (1024 ** 2):.2f} MB/s"
        return f"{speed_bps / (1024 ** 3):.2f} GB/s"

    @staticmethod
    def _format_eta(seconds: float) -> str:
        seconds = int(max(0, seconds))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"