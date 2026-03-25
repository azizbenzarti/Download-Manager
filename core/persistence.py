# History (db)

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from core.models import DownloadStatus, DownloadTask, SegmentInfo, SegmentStatus


class PersistenceManager:
    """
    Handles SQLite persistence for:
    - download history
    - resumable segment metadata
    """

    def __init__(self, db_path: str = "sdm.db") -> None:
        self.db_path = db_path
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_database(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    task_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    output_file TEXT NOT NULL,
                    file_name TEXT,
                    total_size INTEGER NOT NULL DEFAULT 0,
                    thread_count INTEGER NOT NULL DEFAULT 1,
                    supports_range INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at REAL,
                    started_at REAL,
                    completed_at REAL,
                    error_message TEXT
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS segments (
                    task_id TEXT NOT NULL,
                    segment_id INTEGER NOT NULL,
                    start_byte INTEGER NOT NULL,
                    end_byte INTEGER NOT NULL,
                    temp_file_path TEXT NOT NULL,
                    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    retries_used INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    PRIMARY KEY (task_id, segment_id),
                    FOREIGN KEY (task_id) REFERENCES downloads(task_id)
                )
                """
            )

            conn.commit()

    def save_download_task(self, task: DownloadTask) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO downloads (
                    task_id, url, output_file, file_name, total_size,
                    thread_count, supports_range, status,
                    created_at, started_at, completed_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.url,
                    task.output_file,
                    task.file_name,
                    task.total_size,
                    task.thread_count,
                    1 if task.supports_range else 0,
                    task.status.value,
                    task.created_at,
                    task.started_at,
                    task.completed_at,
                    task.error_message,
                ),
            )

            conn.execute("DELETE FROM segments WHERE task_id = ?", (task.task_id,))

            for segment in task.segments:
                conn.execute(
                    """
                    INSERT INTO segments (
                        task_id, segment_id, start_byte, end_byte, temp_file_path,
                        downloaded_bytes, status, retries_used, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        segment.segment_id,
                        segment.start_byte,
                        segment.end_byte,
                        segment.temp_file_path,
                        segment.downloaded_bytes,
                        segment.status.value,
                        segment.retries_used,
                        segment.error_message,
                    ),
                )

            conn.commit()

    def load_download_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._get_connection() as conn:
            download_row = conn.execute(
                "SELECT * FROM downloads WHERE task_id = ?",
                (task_id,),
            ).fetchone()

            if not download_row:
                return None

            segment_rows = conn.execute(
                """
                SELECT * FROM segments
                WHERE task_id = ?
                ORDER BY segment_id ASC
                """,
                (task_id,),
            ).fetchall()

        task = DownloadTask(
            task_id=download_row["task_id"],
            url=download_row["url"],
            output_file=download_row["output_file"],
            file_name=download_row["file_name"],
            total_size=download_row["total_size"],
            thread_count=download_row["thread_count"],
            supports_range=bool(download_row["supports_range"]),
            status=DownloadStatus(download_row["status"]),
            created_at=download_row["created_at"],
            started_at=download_row["started_at"],
            completed_at=download_row["completed_at"],
            error_message=download_row["error_message"],
        )

        for row in segment_rows:
            task.segments.append(
                SegmentInfo(
                    segment_id=row["segment_id"],
                    start_byte=row["start_byte"],
                    end_byte=row["end_byte"],
                    temp_file_path=row["temp_file_path"],
                    downloaded_bytes=row["downloaded_bytes"],
                    status=SegmentStatus(row["status"]),
                    retries_used=row["retries_used"],
                    error_message=row["error_message"],
                )
            )

        return task

    def list_downloads(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    task_id,
                    file_name,
                    url,
                    output_file,
                    total_size,
                    thread_count,
                    supports_range,
                    status,
                    created_at,
                    started_at,
                    completed_at,
                    error_message
                FROM downloads
                ORDER BY created_at DESC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def delete_download_task(self, task_id: str, delete_temp_files: bool = False) -> None:
        task = self.load_download_task(task_id)

        with self._get_connection() as conn:
            conn.execute("DELETE FROM segments WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM downloads WHERE task_id = ?", (task_id,))
            conn.commit()

        if delete_temp_files and task:
            for segment in task.segments:
                try:
                    if os.path.exists(segment.temp_file_path):
                        os.remove(segment.temp_file_path)
                except OSError:
                    pass

    def update_task_status(
        self,
        task_id: str,
        status: DownloadStatus,
        error_message: Optional[str] = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE downloads
                SET status = ?, error_message = ?
                WHERE task_id = ?
                """,
                (status.value, error_message, task_id),
            )
            conn.commit()