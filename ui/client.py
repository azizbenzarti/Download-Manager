# https://proof.ovh.net/files/100Mb.dat
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import streamlit.web.cli as streamlit_cli
from streamlit.runtime.scriptrunner import get_script_run_ctx

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
from core.models import DownloadStatus
from core.persistence import PersistenceManager


PROGRESS_REFRESH_INTERVAL_SECONDS = 0.5


def relaunch_with_streamlit_if_needed() -> None:
    """
    Streamlit apps need Streamlit's script runner for session state and UI updates.
    If this file is launched with `python ui/client.py`, hand off to `streamlit run`.
    """
    if __name__ == "__main__" and get_script_run_ctx(suppress_warning=True) is None:
        sys.argv = [
            "streamlit",
            "run",
            str(Path(__file__).resolve()),
            *sys.argv[1:],
        ]
        raise SystemExit(streamlit_cli.main())


relaunch_with_streamlit_if_needed()
ensure_directories()

st.set_page_config(page_title=APP_NAME, layout="wide")
st.title(f"{APP_NAME} v{APP_VERSION}")


# -----------------------------
# Session state init
# -----------------------------
if "download_manager" not in st.session_state:
    st.session_state.download_manager = DownloadManager(
        temp_dir=str(TEMP_DIR),
        chunk_size=DEFAULT_CHUNK_SIZE,
        timeout=DEFAULT_TIMEOUT,
    )

if "current_task_id" not in st.session_state:
    st.session_state.current_task_id = None

if "download_thread" not in st.session_state:
    st.session_state.download_thread = None

if "is_downloading" not in st.session_state:
    st.session_state.is_downloading = False

if "last_output_path" not in st.session_state:
    st.session_state.last_output_path = ""

if "ui_state" not in st.session_state:
    st.session_state.ui_state = {
        "status_message": "Idle",
        "progress": 0.0,
        "speed": "0 KB/s",
        "eta": "--",
        "error": None,
        "done": False,
        "task_id": None,
        "download_status": "idle",
    }

if "ui_state_lock" not in st.session_state:
    st.session_state.ui_state_lock = threading.Lock()


# -----------------------------
# Helpers
# -----------------------------
def update_ui_state(
    ui_state: dict[str, Any],
    ui_state_lock: threading.Lock,
    **updates: Any,
) -> None:
    with ui_state_lock:
        ui_state.update(updates)


def get_ui_state_snapshot() -> dict[str, Any]:
    with st.session_state.ui_state_lock:
        return dict(st.session_state.ui_state)


def sync_download_state(ui_state: dict[str, Any]) -> None:
    thread = st.session_state.download_thread

    if thread is not None and not thread.is_alive():
        st.session_state.is_downloading = False
    if ui_state.get("task_id"):
        st.session_state.current_task_id = ui_state["task_id"]


def save_task_state(manager: DownloadManager, task_id: str | None) -> None:
    if not task_id:
        return

    task = manager.get_status(task_id)
    persistence = PersistenceManager(db_path=str(DB_PATH))
    persistence.save_download_task(task)


def resolve_output_path(output_name: str) -> str:
    output_name = output_name.strip()
    path = Path(output_name)

    if not path.is_absolute() and path.parent == Path("."):
        return str((DOWNLOADS_DIR / path.name).resolve())

    return str(path.resolve())


def run_download(
    manager: DownloadManager,
    url: str,
    output_path: str,
    thread_count: int,
    max_retries: int,
    ui_state: dict,
    ui_state_lock: threading.Lock,
) -> None:
    """
    Background thread function.
    IMPORTANT: do not use st.* or st.session_state here.
    """
    try:
        persistence = PersistenceManager(db_path=str(DB_PATH))
        task_id_holder: dict[str, str | None] = {"task_id": None}
        last_save_at = {"value": 0.0}

        def save_active_task(force: bool = False) -> None:
            task_id = task_id_holder["task_id"]
            if not task_id:
                return

            now = time.time()
            if not force and now - last_save_at["value"] < 1.0:
                return

            persistence.save_download_task(manager.get_status(task_id))
            last_save_at["value"] = now

        def task_created_callback(task) -> None:
            task_id_holder["task_id"] = task.task_id
            update_ui_state(
                ui_state,
                ui_state_lock,
                task_id=task.task_id,
                download_status=task.status.value,
                status_message="Downloading...",
            )
            persistence.save_download_task(task)

        update_ui_state(
            ui_state,
            ui_state_lock,
            status_message="Downloading...",
            progress=0.0,
            speed="0 KB/s",
            eta="--",
            error=None,
            done=False,
            download_status=DownloadStatus.DOWNLOADING.value,
        )

        def progress_callback(progress_value: float, speed_text: str, eta_text: str) -> None:
            update_ui_state(
                ui_state,
                ui_state_lock,
                progress=progress_value,
                speed=speed_text,
                eta=eta_text,
            )
            save_active_task()

        task_id = manager.start_download(
            url=url,
            output_path=output_path,
            thread_count=thread_count,
            max_retries=max_retries,
            progress_callback=progress_callback,
            task_created_callback=task_created_callback,
        )
        task_id_holder["task_id"] = task_id
        task = manager.get_status(task_id)

        update_ui_state(
            ui_state,
            ui_state_lock,
            status_message=f"Download {task.status.value}: {task_id}",
            progress=task.progress_percentage() / 100,
            speed="0 KB/s" if task.status == DownloadStatus.COMPLETED else "0 KB/s",
            eta="00:00:00" if task.status == DownloadStatus.COMPLETED else "--",
            task_id=task_id,
            download_status=task.status.value,
        )

        save_active_task(force=True)

    except Exception as e:
        update_ui_state(
            ui_state,
            ui_state_lock,
            status_message="Download failed.",
            error=str(e),
            download_status=DownloadStatus.FAILED.value,
        )

    finally:
        update_ui_state(ui_state, ui_state_lock, done=True)


def run_resume(
    manager: DownloadManager,
    task_id: str,
    max_retries: int,
    ui_state: dict,
    ui_state_lock: threading.Lock,
) -> None:
    """
    Background resume function.
    IMPORTANT: do not use st.* or st.session_state here.
    """
    persistence = PersistenceManager(db_path=str(DB_PATH))
    last_save_at = {"value": 0.0}

    def save_active_task(force: bool = False) -> None:
        now = time.time()
        if not force and now - last_save_at["value"] < 1.0:
            return

        persistence.save_download_task(manager.get_status(task_id))
        last_save_at["value"] = now

    try:
        update_ui_state(
            ui_state,
            ui_state_lock,
            status_message="Resuming download...",
            error=None,
            done=False,
            download_status=DownloadStatus.DOWNLOADING.value,
        )

        def progress_callback(progress_value: float, speed_text: str, eta_text: str) -> None:
            update_ui_state(
                ui_state,
                ui_state_lock,
                progress=progress_value,
                speed=speed_text,
                eta=eta_text,
            )
            save_active_task()

        manager.resume_download(
            task_id=task_id,
            progress_callback=progress_callback,
            max_retries=max_retries,
        )

        task = manager.get_status(task_id)
        update_ui_state(
            ui_state,
            ui_state_lock,
            status_message=f"Download {task.status.value}: {task_id}",
            progress=task.progress_percentage() / 100,
            speed="0 KB/s",
            eta="00:00:00" if task.status == DownloadStatus.COMPLETED else "--",
            download_status=task.status.value,
        )
        save_active_task(force=True)

    except Exception as e:
        update_ui_state(
            ui_state,
            ui_state_lock,
            status_message="Resume failed.",
            error=str(e),
            download_status=DownloadStatus.FAILED.value,
        )

    finally:
        update_ui_state(ui_state, ui_state_lock, done=True)


# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.header("Settings")

thread_count = st.sidebar.number_input(
    "Threads",
    min_value=1,
    max_value=16,
    value=DEFAULT_THREAD_COUNT,
)

max_retries = st.sidebar.number_input(
    "Max retries",
    min_value=0,
    max_value=10,
    value=DEFAULT_MAX_RETRIES,
)


# -----------------------------
# Inputs
# -----------------------------
url = st.text_input("File URL", placeholder="https://proof.ovh.net/files/100Mb.dat")
output_name = st.text_input("Output filename", placeholder="example.bin")

col1, col2 = st.columns(2)

with col1:
    if st.button("Start Download", width="stretch"):
        thread = st.session_state.download_thread

        if thread is not None and thread.is_alive():
            st.warning("A download is already running.")
        elif not url.strip():
            st.error("Please enter a valid URL.")
        elif not output_name.strip():
            st.error("Please enter an output filename.")
        else:
            output_path = resolve_output_path(output_name)

            st.session_state.last_output_path = output_path
            st.session_state.is_downloading = True
            st.session_state.current_task_id = None

            st.session_state.ui_state = {
                "status_message": "Preparing download...",
                "progress": 0.0,
                "speed": "0 KB/s",
                "eta": "--",
                "error": None,
                "done": False,
                "task_id": None,
                "download_status": "preparing",
            }

            thread = threading.Thread(
                target=run_download,
                args=(
                    st.session_state.download_manager,
                    url.strip(),
                    output_path,
                    int(thread_count),
                    int(max_retries),
                    st.session_state.ui_state,
                    st.session_state.ui_state_lock,
                ),
                daemon=True,
            )

            st.session_state.download_thread = thread
            thread.start()
            st.rerun()

with col2:
    if st.button("Reset UI", width="stretch"):
        st.session_state.is_downloading = False
        st.session_state.download_thread = None
        st.session_state.current_task_id = None
        st.session_state.ui_state = {
            "status_message": "Idle",
            "progress": 0.0,
            "speed": "0 KB/s",
            "eta": "--",
            "error": None,
            "done": False,
            "task_id": None,
            "download_status": "idle",
        }
        st.rerun()


# -----------------------------
# Progress display
# -----------------------------
@st.fragment(run_every=PROGRESS_REFRESH_INTERVAL_SECONDS)
def render_progress_panel() -> None:
    ui_state = get_ui_state_snapshot()
    sync_download_state(ui_state)

    st.subheader("Progress")

    progress = max(0.0, min(1.0, float(ui_state.get("progress", 0.0))))
    st.progress(progress)

    st.write(f"**Status:** {ui_state.get('status_message', 'Idle')}")
    st.write(f"**Progress:** {progress * 100:.1f}%")
    st.write(f"**Speed:** {ui_state.get('speed', '0 KB/s')}")
    st.write(f"**ETA:** {ui_state.get('eta', '--')}")
    st.write(f"**Temp folder:** `{TEMP_DIR}`")
    st.write(f"**Downloads folder:** `{DOWNLOADS_DIR}`")

    if st.session_state.last_output_path:
        st.write(f"**Target output:** `{st.session_state.last_output_path}`")

    if ui_state.get("error"):
        st.error(ui_state["error"])

    task_id = ui_state.get("task_id")
    status = ui_state.get("download_status", "idle")
    thread = st.session_state.download_thread
    thread_is_alive = thread is not None and thread.is_alive()
    can_pause = bool(task_id) and status == DownloadStatus.DOWNLOADING.value
    can_resume = (
        bool(task_id)
        and status in (DownloadStatus.PAUSED.value, DownloadStatus.FAILED.value)
        and not thread_is_alive
    )
    terminal_statuses = {
        DownloadStatus.COMPLETED.value,
        DownloadStatus.CANCELLED.value,
        "idle",
    }
    can_cancel = bool(task_id) and status not in terminal_statuses

    action_col1, action_col2, action_col3, action_col4 = st.columns(4)

    with action_col1:
        if st.button("Pause", width="stretch", disabled=not can_pause):
            try:
                st.session_state.download_manager.pause_download(task_id)
                save_task_state(st.session_state.download_manager, task_id)
                update_ui_state(
                    st.session_state.ui_state,
                    st.session_state.ui_state_lock,
                    status_message="Download paused.",
                    download_status=DownloadStatus.PAUSED.value,
                )
            except Exception as e:
                st.error(f"Pause failed: {e}")
            st.rerun()

    with action_col2:
        if st.button("Resume", width="stretch", disabled=not can_resume):
            thread = threading.Thread(
                target=run_resume,
                args=(
                    st.session_state.download_manager,
                    task_id,
                    int(max_retries),
                    st.session_state.ui_state,
                    st.session_state.ui_state_lock,
                ),
                daemon=True,
            )
            st.session_state.download_thread = thread
            st.session_state.is_downloading = True
            thread.start()
            st.rerun()

    with action_col3:
        if st.button("Cancel", width="stretch", disabled=not can_cancel):
            try:
                st.session_state.download_manager.cancel_download(task_id)
                save_task_state(st.session_state.download_manager, task_id)
                update_ui_state(
                    st.session_state.ui_state,
                    st.session_state.ui_state_lock,
                    status_message="Download cancelled.",
                    download_status=DownloadStatus.CANCELLED.value,
                    speed="0 KB/s",
                    eta="--",
                    done=True,
                )
            except Exception as e:
                st.error(f"Cancel failed: {e}")
            st.rerun()

    with action_col4:
        if st.button("Refresh Status", width="stretch"):
            st.rerun()


render_progress_panel()


# -----------------------------
# Temp files
# -----------------------------
st.subheader("Current Temp Files")

temp_files = sorted(TEMP_DIR.glob("*"))
if temp_files:
    for temp_file in temp_files:
        try:
            size = temp_file.stat().st_size
        except OSError:
            size = 0
        st.write(f"- `{temp_file.name}` — {size} bytes")
else:
    st.info("No temp files currently found.")


# -----------------------------
# Download history
# -----------------------------
st.subheader("Download History")

try:
    persistence = PersistenceManager(db_path=str(DB_PATH))
    history = persistence.list_downloads()

    if history:
        st.dataframe(history, width="stretch")
    else:
        st.info("No downloads yet.")
except Exception as e:
    st.warning(f"Could not load history: {e}")
