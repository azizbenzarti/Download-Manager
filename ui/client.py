import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

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
    }


# -----------------------------
# Helpers
# -----------------------------
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
) -> None:
    """
    Background thread function.
    IMPORTANT: do not use st.* or st.session_state here.
    """
    try:
        ui_state["status_message"] = "Downloading..."
        ui_state["progress"] = 0.0
        ui_state["speed"] = "0 KB/s"
        ui_state["eta"] = "--"
        ui_state["error"] = None

        def progress_callback(progress_value: float, speed_text: str, eta_text: str) -> None:
            ui_state["progress"] = progress_value
            ui_state["speed"] = speed_text
            ui_state["eta"] = eta_text

        task_id = manager.start_download(
            url=url,
            output_path=output_path,
            thread_count=thread_count,
            max_retries=max_retries,
            progress_callback=progress_callback,
        )

        ui_state["status_message"] = f"Download completed: {task_id}"
        ui_state["progress"] = 1.0
        ui_state["speed"] = "0 KB/s"
        ui_state["eta"] = "00:00:00"
        ui_state["task_id"] = task_id

        task = manager.get_status(task_id)
        persistence = PersistenceManager(db_path=str(DB_PATH))
        persistence.save_download_task(task)

    except Exception as e:
        ui_state["status_message"] = "Download failed."
        ui_state["error"] = str(e)

    finally:
        ui_state["done"] = True


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

col1, col2, col3 = st.columns(3)

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
                ),
                daemon=True,
            )

            st.session_state.download_thread = thread
            thread.start()
            st.rerun()

with col2:
    if st.button("Refresh Status", width="stretch"):
        st.rerun()

with col3:
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
        }
        st.rerun()


# -----------------------------
# Sync state from worker result
# -----------------------------
thread = st.session_state.download_thread
ui_state = st.session_state.ui_state

if thread is not None and not thread.is_alive():
    st.session_state.is_downloading = False
    if ui_state.get("task_id"):
        st.session_state.current_task_id = ui_state["task_id"]


# -----------------------------
# Progress display
# -----------------------------
st.subheader("Progress")

st.progress(float(ui_state.get("progress", 0.0)))

st.write(f"**Status:** {ui_state.get('status_message', 'Idle')}")
st.write(f"**Progress:** {ui_state.get('progress', 0.0) * 100:.1f}%")
st.write(f"**Speed:** {ui_state.get('speed', '0 KB/s')}")
st.write(f"**ETA:** {ui_state.get('eta', '--')}")
st.write(f"**Temp folder:** `{TEMP_DIR}`")
st.write(f"**Downloads folder:** `{DOWNLOADS_DIR}`")

if st.session_state.last_output_path:
    st.write(f"**Target output:** `{st.session_state.last_output_path}`")

if ui_state.get("error"):
    st.error(ui_state["error"])


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