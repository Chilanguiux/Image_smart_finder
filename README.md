# Image Smart Browser (PySide6)

A lightweight image explorer built with Python + PySide6.  
Browse a folder recursively, filter, open, copy paths, and delete images.  
Supports multi-selection (Ctrl/Shift), thumbnails, progress loader, list/icon views, and persistent settings.

## Features

- Folder picker and recursive scan (non-blocking, background worker)
- Real-time filter with result count (shown/total)
- Empty-state message when the filter yields no results
- List or icon view with thumbnails (on the fly)
- Multi-selection with Ctrl/Shift
- Context menu: Open / Copy paths / Delete (with confirmation)
- Keyboard shortcuts: **Enter** (open), **Ctrl+C** (copy paths), **Delete** (remove)
- Remembers window size/position, last folder and last filter (QSettings)
- Runs standalone with PySide6 (Windows, macOS, Linux)

## Requirements

- Python 3.8+ (tested on 3.12, Windows)
- PySide6 (installed via `requirements.txt`)

> If you need to embed in Maya/Nuke (PySide2), this repo targets PySide6.

## Setup (Windows, PowerShell)

```powershell
# 1) Clone
git clone https://github.com/chilanguiux/Image_smart_finder.git
cd Image_smart_finder

# 2) Create & activate venv (Windows-native Python: creates bin/)
py -3 -m venv .venv
.\.venv\bin\Activate.ps1

# If ExecutionPolicy blocks scripts only for this session:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

# 3) Install dependencies
pip install -r requirements.txt

# 4) Run
python finder.py
```

## Usage

- Click Choose folder to pick a directory with images.
- Click Scan.
- Type in the filter box to narrow results.
- Toggle List/Icon view as needed.
- Select one or more images and press Enter to open in the system viewer
- Ctrl+C to copy full paths
- Delete to remove files (asks for confirmation)
  or right-click for the context menu.

### Troubleshooting

- ModuleNotFoundError: PySide6
  Ensure the venv is active (.venv\bin\Activate.ps1) and then pip install -r requirements.txt.

- Execution policy error
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned and try again.

- You see GCC in sys.version and install fails
  You're using a MinGW/MSYS2 Python. Recreate the venv with Python for Windows (py -3 -m venv .venv) so PyPI wheels for PySide6 are available.

### Project Structure

```
.
├── image_finder.py
├── requirements.txt
├── mypy.ini
├── README.md
├── tests/
│   ├── __init__.py
│   ├── test_scan.py
│   └── test_viewmodel.py
└── .github/
    └── workflows/
        └── ci.yml
```

### License

```
MIT
```

`Powered by Erik Elizalde 😃`
