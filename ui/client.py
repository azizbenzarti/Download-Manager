import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from pathlib import Path

from core.downloader import DownloadManager
from core.persistence import PersistenceManager

st.set_page_config(page_title="Smart Download Manager", layout="wide")
st.title("Smart Download Manager")

# ---------- Session state ----------
if "download_manager" not in st.session_state:
    st.session_state.download_manager = DownloadManager()

if "current_task_id" not in st.session_state:
    st.session_state.current_task_id = None

if "status_message" not in st.session_state:
    st.session_state.status_message = ""

if "progress" not in st.session_state:
    st.session_state.progress = 0.0

if "speed" not in st.session_state:
    st.session_state.speed = "0 KB/s"

if "eta" not in st.session_state:
    st.session_state.eta = "--"

# ---------- Sidebar config ----------
st.sidebar.header("Settings")
thread_count = st.sidebar.number_input("Threads", min_value=1, max_value=16, value=4)
max_retries = st.sidebar.number_input("Max retries", min_value=0, max_value=10, value=3)

# ---------- Inputs ----------
url = st.text_input("File URL", placeholder="https://example.com/file.zip")
output_name = st.text_input("Output filename", placeholder="file.zip")

col1, col2, col3 = st.columns(3)

def progress_callback(progress_value: float, speed_text: str, eta_text: str):
    st.session_state.progress = progress_value
    st.session_state.speed = speed_text
    st.session_state.eta = eta_text

with col1:
    if st.button("Start Download"):
        if not url.strip():
            st.error("Please enter a valid URL.")
        elif not output_name.strip():
            st.error("Please enter an output filename.")
        else:
            try:
                task_id = st.session_state.download_manager.start_download(
                    url=url.strip(),
                    output_path=str(Path(output_name.strip()).resolve()),
                    thread_count=thread_count,
                    max_retries=max_retries,
                    progress_callback=progress_callback,
                )
                st.session_state.current_task_id = task_id
                st.session_state.status_message = f"Download started: {task_id}"
            except Exception as e:
                st.session_state.status_message = f"Error: {e}"

with col2:
    if st.button("Pause Download"):
        task_id = st.session_state.current_task_id
        if task_id:
            st.session_state.download_manager.pause_download(task_id)
            st.session_state.status_message = "Download paused."

with col3:
    if st.button("Resume Download"):
        task_id = st.session_state.current_task_id
        if task_id:
            st.session_state.download_manager.resume_download(
                task_id,
                progress_callback=progress_callback
            )
            st.session_state.status_message = "Download resumed."

# ---------- Progress display ----------
st.subheader("Progress")
st.progress(int(st.session_state.progress * 100))
st.write(f"**Status:** {st.session_state.status_message}")
st.write(f"**Progress:** {st.session_state.progress * 100:.1f}%")
st.write(f"**Speed:** {st.session_state.speed}")
st.write(f"**ETA:** {st.session_state.eta}")

# ---------- History ----------
st.subheader("Download History")

try:
    persistence = PersistenceManager()
    history = persistence.list_downloads()

    if history:
        st.dataframe(history, use_container_width=True)
    else:
        st.info("No downloads yet.")
except Exception as e:
    st.warning(f"Could not load history: {e}")