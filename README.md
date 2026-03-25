# 📦 Smart Download Manager (SDM)

A **multi-threaded segmented download manager** built in Python as part of a Distributed Systems course project.

SDM accelerates file downloads by splitting files into segments and downloading them concurrently using multiple threads, while supporting retry logic, pause/resume, and progress tracking.

---

## 🚀 Features

- **Segmented Downloads (Multi-threaded)**
  - Splits files into multiple byte ranges
  - Downloads segments in parallel

- **Pause & Resume**
  - Resume downloads from where they stopped
  - Persistent state using SQLite

- **Real-time Progress Tracking**
  - Download percentage
  - Speed (KB/s, MB/s)
  - Estimated Time Remaining (ETA)

- **Retry Mechanism**
  - Automatic retry on failed segments
  - Configurable retry attempts and backoff

- **File Assembly**
  - Merges downloaded segments into final file

- **Download History**
  - Stores completed and ongoing downloads

- **CLI Interface**
  - Simple command-line interaction (GUI optional extension)

---

## 🏗️ Architecture

This project follows a **layered architecture with concurrent worker threads**:

- **Presentation Layer**
  - CLI interface (`ui/cli.py`)

- **Application Layer**
  - Download Manager (`core/downloader.py`)

- **Worker Layer**
  - Segment workers (`core/segment_worker.py`)

- **Data Layer**
  - Persistence (`core/persistence.py`)
  - Temporary storage (`temp/`)

- **Network Layer**
  - HTTP client (`core/http_client.py`)

---

## 📁 Project Structure

```text
sdm/
├── core/
│   ├── downloader.py
│   ├── segment_worker.py
│   ├── assembler.py
│   ├── progress.py
│   ├── retry.py
│   ├── persistence.py
│   ├── http_client.py
│   └── models.py
├── ui/
│   └── cli.py
├── temp/
├── tests/
│   ├── test_downloader.py
│   ├── test_assembler.py
│   └── test_retry.py
├── config.py
├── main.py
└── README.md
```

## ⚙️ How It Works

### 1. Metadata Fetch
- Send an HTTP `HEAD` request  
- Retrieve file size using `Content-Length`  
- Check whether the server supports `Accept-Ranges`  

### 2. Segmentation
- Divide the file into multiple segments based on file size and thread count  

### 3. Parallel Download
- Each segment is downloaded by a separate thread using HTTP Range requests  

### 4. Temporary Storage
- Segments are saved in the `temp/` folder as `.part` files  

### 5. Retry Handling
- Failed segments are retried automatically  

### 6. Assembly
- Segments are merged into the final file  

### 7. Cleanup
- Temporary files are deleted after successful merge  

---

## 🧪 Testing

Basic unit tests are included to verify core functionality:

- `test_downloader.py` → segmentation and orchestration logic  
- `test_assembler.py` → correct merging of segments  
- `test_retry.py` → retry mechanism behavior  

Run tests with:

```bash
pytest tests/
```

## Installation 
- git clone https://github.com/azizbenzarti/sdm.git
- cd sdm
- python -m venv venv
- source venv/bin/activate
- pip install -r requirements.txt