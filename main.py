# Entry point

from __future__ import annotations

import argparse
import time
from pathlib import Path

from config import (
    APP_NAME,
    APP_VERSION,
    DB_PATH,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_THREAD_COUNT,
    DEFAULT_TIMEOUT,
    DOWNLOADS_DIR,
    TEMP_DIR,
    ensure_directories,
)
from core.downloader import DownloadManager
from core.persistence import PersistenceManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdm",
        description=f"{APP_NAME} v{APP_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # download command
    download_parser = subparsers.add_parser("download", help="Download a file")
    download_parser.add_argument("url", help="File URL")
    download_parser.add_argument(
        "-o",
        "--output",
        help="Output file path or file name",
        required=False,
    )
    download_parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=DEFAULT_THREAD_COUNT,
        help=f"Number of threads (default: {DEFAULT_THREAD_COUNT})",
    )
    download_parser.add_argument(
        "-r",
        "--retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Max retries per segment (default: {DEFAULT_MAX_RETRIES})",
    )

    # history command
    subparsers.add_parser("history", help="Show download history")

    # status command
    status_parser = subparsers.add_parser("status", help="Show details for one task")
    status_parser.add_argument("task_id", help="Task ID")

    return parser


def resolve_output_path(output_value: str | None, url: str) -> str:
    if output_value:
        path = Path(output_value)

        # If user gives only a filename, place it in downloads/
        if not path.is_absolute() and path.parent == Path("."):
            return str((DOWNLOADS_DIR / path.name).resolve())

        return str(path.resolve())

    fallback_name = url.rstrip("/").split("/")[-1] or "downloaded_file"
    return str((DOWNLOADS_DIR / fallback_name).resolve())


def print_progress(progress_fraction: float, speed_text: str, eta_text: str) -> None:
    percent = progress_fraction * 100
    print(
        f"\rProgress: {percent:6.2f}% | Speed: {speed_text:>10} | ETA: {eta_text:>8}",
        end="",
        flush=True,
    )


def command_download(args: argparse.Namespace) -> None:
    ensure_directories()

    manager = DownloadManager(
        temp_dir=str(TEMP_DIR),
        chunk_size=DEFAULT_CHUNK_SIZE,
        timeout=DEFAULT_TIMEOUT,
    )

    output_path = resolve_output_path(args.output, args.url)

    print(f"Starting download...")
    print(f"URL: {args.url}")
    print(f"Output: {output_path}")
    print(f"Threads: {args.threads}")
    print(f"Retries: {args.retries}")
    print()

    try:
        task_id = manager.start_download(
            url=args.url,
            output_path=output_path,
            thread_count=args.threads,
            max_retries=args.retries,
            progress_callback=print_progress,
        )

        print()
        task = manager.get_status(task_id)

        print(f"\nTask ID: {task.task_id}")
        print(f"Status: {task.status.value}")
        print(f"Saved to: {task.output_file}")

        # Persist final state
        persistence = PersistenceManager(db_path=str(DB_PATH))
        persistence.save_download_task(task)

    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user.")
    except Exception as exc:
        print(f"\nError: {exc}")


def command_history() -> None:
    ensure_directories()
    persistence = PersistenceManager(db_path=str(DB_PATH))
    history = persistence.list_downloads()

    if not history:
        print("No downloads found.")
        return

    print(f"{'Task ID':36}  {'Status':12}  {'File Name':25}  {'Size (bytes)':12}")
    print("-" * 95)

    for item in history:
        task_id = item.get("task_id", "")
        status = item.get("status", "")
        file_name = item.get("file_name") or Path(item.get("output_file", "")).name
        total_size = item.get("total_size", 0)

        print(f"{task_id:36}  {status:12}  {file_name[:25]:25}  {str(total_size):12}")


def command_status(task_id: str) -> None:
    ensure_directories()
    persistence = PersistenceManager(db_path=str(DB_PATH))
    task = persistence.load_download_task(task_id)

    if not task:
        print(f"No task found with ID: {task_id}")
        return

    print(f"Task ID:        {task.task_id}")
    print(f"URL:            {task.url}")
    print(f"Output file:    {task.output_file}")
    print(f"File name:      {task.file_name}")
    print(f"Total size:     {task.total_size}")
    print(f"Thread count:   {task.thread_count}")
    print(f"Range support:  {task.supports_range}")
    print(f"Status:         {task.status.value}")
    print(f"Created at:     {task.created_at}")
    print(f"Started at:     {task.started_at}")
    print(f"Completed at:   {task.completed_at}")
    print(f"Error:          {task.error_message}")
    print()
    print("Segments:")

    for segment in task.segments:
        print(
            f"  - Segment {segment.segment_id}: "
            f"{segment.start_byte}-{segment.end_byte} | "
            f"Downloaded={segment.downloaded_bytes} | "
            f"Status={segment.status.value} | "
            f"Retries={segment.retries_used}"
        )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "download":
        command_download(args)
    elif args.command == "history":
        command_history()
    elif args.command == "status":
        command_status(args.task_id)


if __name__ == "__main__":
    main()