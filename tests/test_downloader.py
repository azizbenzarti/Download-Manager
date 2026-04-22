import time

from core.downloader import DownloadManager
from core.models import DownloadStatus


class FakeHttpClient:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def get_file_metadata(self, url: str) -> dict[str, object]:
        return {
            "content_length": len(self.data),
            "accept_ranges": True,
            "content_type": "application/octet-stream",
            "filename": None,
        }

    def stream_range(
        self,
        url: str,
        start_byte: int,
        end_byte: int,
        chunk_size: int = 8192,
        extra_headers: dict[str, str] | None = None,
    ):
        del url, chunk_size, extra_headers

        for index in range(start_byte, end_byte + 1, 2):
            time.sleep(0.001)
            yield self.data[index : min(index + 2, end_byte + 1)]


def test_pause_exits_workers_and_resume_completes_from_partial_file(tmp_path):
    manager = DownloadManager(temp_dir=str(tmp_path / "temp"), chunk_size=2)
    manager.http_client = FakeHttpClient(b"abcdef")

    task_id_holder = {"task_id": None}
    paused_once = {"value": False}

    def on_task_created(task):
        task_id_holder["task_id"] = task.task_id

    def on_progress(progress, speed, eta):
        del progress, speed, eta
        if not paused_once["value"]:
            paused_once["value"] = True
            manager.pause_download(task_id_holder["task_id"])

    output_file = tmp_path / "download.bin"
    task_id = manager.start_download(
        url="https://example.test/file.bin",
        output_path=str(output_file),
        thread_count=1,
        max_retries=0,
        progress_callback=on_progress,
        task_created_callback=on_task_created,
    )

    paused_task = manager.get_status(task_id)
    assert paused_task.status == DownloadStatus.PAUSED
    assert 0 < paused_task.total_downloaded_bytes() < paused_task.total_size
    assert not output_file.exists()

    manager.resume_download(task_id, max_retries=0)

    completed_task = manager.get_status(task_id)
    assert completed_task.status == DownloadStatus.COMPLETED
    assert output_file.read_bytes() == b"abcdef"


def test_cancel_stops_download_without_assembly(tmp_path):
    manager = DownloadManager(temp_dir=str(tmp_path / "temp"), chunk_size=2)
    manager.http_client = FakeHttpClient(b"abcdef")

    task_id_holder = {"task_id": None}
    cancelled_once = {"value": False}

    def on_task_created(task):
        task_id_holder["task_id"] = task.task_id

    def on_progress(progress, speed, eta):
        del progress, speed, eta
        if not cancelled_once["value"]:
            cancelled_once["value"] = True
            manager.cancel_download(task_id_holder["task_id"])

    output_file = tmp_path / "cancelled.bin"
    task_id = manager.start_download(
        url="https://example.test/file.bin",
        output_path=str(output_file),
        thread_count=1,
        max_retries=0,
        progress_callback=on_progress,
        task_created_callback=on_task_created,
    )

    task = manager.get_status(task_id)
    assert task.status == DownloadStatus.CANCELLED
    assert task.total_downloaded_bytes() < task.total_size
    assert not output_file.exists()
