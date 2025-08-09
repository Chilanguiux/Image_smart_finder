from __future__ import annotations

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # Maya/Nuke compatibility
    from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore

import os
import threading
from pathlib import Path
from typing import List, Optional, Tuple
from typing import Iterable

APP_ORG: str = "Erik Elizalde"
APP_NAME: str = "SmartImageExplorer"

IMAGE_EXTENSIONS: Tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tiff",
    ".tif",
    ".webp",
    ".heic",
    ".heif",
    ".svg",
    ".ppm",
    ".pgm",
)


def scan_images(root: str, exts: Iterable[str] = IMAGE_EXTENSIONS) -> List[str]:
    """
    Returns absolute paths of images under 'root', sorted. Does not depend on Qt (pure, easy to test).
    """
    out: List[str] = []
    base = Path(root)
    if not base.is_dir():
        return out
    exts_lower: Tuple[str, ...] = tuple(e.lower() for e in exts)
    for p in base.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts_lower:
            out.append(str(p.resolve()))
    out.sort()
    return out


class ImageListModel(QtCore.QAbstractListModel):
    """
    Read-only model that exposes image paths, their display names, and an icon/thumbnail for use in a QListView.
    """

    displayRole = QtCore.Qt.ItemDataRole.DisplayRole
    decorationRole = QtCore.Qt.ItemDataRole.DecorationRole
    FILEPATH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

    def __init__(self, paths: Optional[List[str]] = None, thumb_size: int = 64) -> None:
        super().__init__()
        self._paths: List[str] = paths or []
        self._thumbs: dict[str, QtGui.QIcon] = {}
        self._thumb_size: int = thumb_size

    # ---- Qt Model API ----
    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # type: ignore[override]
        return len(self._paths)

    def data(self, index: QtCore.QModelIndex, role: int) -> Optional[object]:  # type: ignore[override]
        if not index.isValid():
            return None
        path = self._paths[index.row()]
        if role == self.displayRole:
            return os.path.basename(path)
        if role == self.FILEPATH_ROLE:
            return path
        if role == self.decorationRole:
            icon = self._thumbs.get(path)
            if icon is None:
                icon = self._make_icon(path)
                self._thumbs[path] = icon
            return icon
        return None

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return {self.FILEPATH_ROLE: b"filepath"}

    def replace(self, paths: List[str]) -> None:
        """Replace all paths in the model with a new list."""
        self.beginResetModel()
        self._paths = list(paths)
        self._thumbs.clear()
        self.endResetModel()

    def remove_path(self, path: str) -> None:
        """Delete a specific path from the model."""
        try:
            row = self._paths.index(path)
        except ValueError:
            return
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        self._paths.pop(row)
        self._thumbs.pop(path, None)
        self.endRemoveRows()

    def _make_icon(self, path: str) -> QtGui.QIcon:
        """Make an icon from the image at 'path', scaled to thumb size."""
        size = QtCore.QSize(self._thumb_size, self._thumb_size)
        try:
            reader = QtGui.QImageReader(path)
            reader.setAutoTransform(True)
            img = reader.read()
            if not img.isNull():
                pm = QtGui.QPixmap.fromImage(img).scaled(
                    size,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                if not pm.isNull():
                    return QtGui.QIcon(pm)
        except Exception:
            pass
        provider = QtWidgets.QFileIconProvider()
        return provider.icon(QtCore.QFileInfo(path))


class WorkerSignals(QtCore.QObject):
    """Container for worker signals."""

    result = QtCore.Signal(list)  # list[str]
    error = QtCore.Signal(str)
    finished = QtCore.Signal()


class ScanWorker(QtCore.QRunnable):
    """
    Worker that scans a directory for images.
    """

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path: str = path
        self.signals: WorkerSignals = WorkerSignals()
        self._cancel_event: threading.Event = threading.Event()

    def cancel(self) -> None:
        """Asks the worker to stop processing."""
        self._cancel_event.set()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            matches = scan_images(self.path)
            if (
                not getattr(self, "_cancel_event", None)
                or not self._cancel_event.is_set()
            ):
                self.signals.result.emit(matches)
        except Exception as exc:
            if (
                not getattr(self, "_cancel_event", None)
                or not self._cancel_event.is_set()
            ):
                self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class ViewModel(QtCore.QObject):
    """
    Logic layer that manages the image list model and handles scanning.
    It provides a clean interface for the view to interact with the data.
    """

    busyChanged = QtCore.Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.model: ImageListModel = ImageListModel([])
        self.proxy: QtCore.QSortFilterProxyModel = QtCore.QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterRole(ImageListModel.displayRole)

        self._busy: bool = False
        self._pool: QtCore.QThreadPool = QtCore.QThreadPool.globalInstance()
        self._current_worker: Optional[ScanWorker] = None

    @QtCore.Property(bool, notify=busyChanged)  # type: ignore
    def busy(self) -> bool:
        """Inicates if a scan is in progress."""
        return self._busy

    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit(value)

    def set_filter(self, text: str) -> None:
        """Applies a filter to the model based on the given text."""
        self.proxy.setFilterFixedString(text)

    def scan(self, path: str) -> None:
        """Launches a scan for images in the specified path."""
        if not path or not os.path.isdir(path):
            self.model.replace([])
            return

        if self._current_worker is not None:
            try:
                self._current_worker.cancel()
            except Exception:
                pass
            self._current_worker = None

        self._set_busy(True)
        worker = ScanWorker(path)
        self._current_worker = worker

        def on_finished() -> None:
            if self._current_worker is worker:
                self._current_worker = None
            self._set_busy(False)

        worker.signals.result.connect(self.model.replace)
        worker.signals.error.connect(lambda msg: print("Scan error:", msg))
        worker.signals.finished.connect(on_finished)
        self._pool.start(worker)


class MainWindow(QtWidgets.QWidget):
    """
    Window that provides a user interface for scanning and viewing images.
    It allows users to choose a folder, scan for images, filter results, and view them
    """

    def __init__(self) -> None:
        super().__init__()
        self.view_model: ViewModel = ViewModel()
        self._icon_mode: bool = False
        self._build_ui()
        self._wire_signals()
        self._restore_settings()
        self._update_counts_and_empty()

    def _build_ui(self) -> None:
        """Creates the UI components and layout."""
        self.setWindowTitle("Smart Image Browser - SIB")

        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("Folder to scan…")
        self.browse_button = QtWidgets.QPushButton("Choose a folder…")
        self.scan_button = QtWidgets.QPushButton("Scan")
        self.open_button = QtWidgets.QPushButton("Open selection")
        self.open_button.setEnabled(False)

        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name…")

        self.toggle_view_button = QtWidgets.QPushButton("View: Icons")

        self.count_label = QtWidgets.QLabel("")
        self.count_label.setStyleSheet("color: #aaa; padding-top: 4px;")

        self.loader = QtWidgets.QProgressBar()
        self.loader.setTextVisible(True)
        self.loader.setFormat("Loading thumnails…")
        self.loader.setRange(0, 0)
        self.loader.hide()

        self.empty_label = QtWidgets.QLabel("")
        self.empty_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: #bbb; font-style: italic; padding: 16px;"
        )

        self.view = QtWidgets.QListView()
        self.view.setModel(self.view_model.proxy)
        self.view.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.view.setUniformItemSizes(True)
        self.view.setIconSize(QtCore.QSize(64, 64))
        self.view.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.addWidget(self.path_edit, 1)
        top_bar.addWidget(self.browse_button)
        top_bar.addWidget(self.scan_button)

        actions_bar = QtWidgets.QHBoxLayout()
        actions_bar.addWidget(self.filter_edit, 1)
        actions_bar.addWidget(self.toggle_view_button)
        actions_bar.addWidget(self.open_button)

        self.stack = QtWidgets.QStackedLayout()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.empty_label)

        root = QtWidgets.QVBoxLayout(self)
        root.addLayout(top_bar)
        root.addLayout(actions_bar)
        root.addWidget(self.count_label)
        root.addWidget(self.loader)
        root.addLayout(self.stack, 1)

        self.scan_button.setEnabled(False)

    def _wire_signals(self) -> None:
        """Connects signals to their respective slots."""
        self.path_edit.textChanged.connect(
            lambda t: self.scan_button.setEnabled(bool(t.strip()))
        )
        self.browse_button.clicked.connect(self._choose_folder)
        self.scan_button.clicked.connect(
            lambda: self._start_scan(self.path_edit.text())
        )

        self._debounce_timer = QtCore.QTimer(self, interval=250, singleShot=True)
        self.filter_edit.textChanged.connect(lambda _t: self._debounce_timer.start())

        def apply_filter_and_update():
            self.view_model.set_filter(self.filter_edit.text())
            self._update_counts_and_empty()

        self._debounce_timer.timeout.connect(apply_filter_and_update)

        self.toggle_view_button.clicked.connect(self._toggle_view_mode)

        self.view_model.busyChanged.connect(self._on_busy_changed)
        self.view_model.busyChanged.connect(lambda _b: self._update_counts_and_empty())

        self.open_button.clicked.connect(self._open_selected_files)
        self.view.doubleClicked.connect(lambda _idx: self._open_selected_files())

        selection_model = self.view.selectionModel()
        selection_model.selectionChanged.connect(lambda *_: self._update_open_enabled())

        self.view.customContextMenuRequested.connect(self._on_context_menu)

        self.view_model.model.modelReset.connect(self._update_counts_and_empty)
        self.view_model.model.rowsInserted.connect(
            lambda *_: self._update_counts_and_empty()
        )
        self.view_model.model.rowsRemoved.connect(
            lambda *_: self._update_counts_and_empty()
        )
        self.view_model.proxy.modelReset.connect(self._update_counts_and_empty)
        self.view_model.proxy.rowsInserted.connect(
            lambda *_: self._update_counts_and_empty()
        )
        self.view_model.proxy.rowsRemoved.connect(
            lambda *_: self._update_counts_and_empty()
        )
        self.view_model.proxy.layoutChanged.connect(self._update_counts_and_empty)

    def _counts(self) -> Tuple[int, int]:
        """Retrieves the number of shown and total items in the model."""
        total = self.view_model.model.rowCount(QtCore.QModelIndex())
        shown = self.view_model.proxy.rowCount(QtCore.QModelIndex())
        return shown, total

    def _update_counts_and_empty(self) -> None:
        """Updates the count label and visibility of the empty state."""
        shown, total = self._counts()
        filter_text = self.filter_edit.text().strip()
        base = f"{shown} of {total} results"
        self.count_label.setText(
            base + (f" for '{filter_text}'" if filter_text else "")
        )

        if self.view_model.busy:
            self.stack.setCurrentIndex(0)
            return

        if shown == 0 and filter_text:
            self.empty_label.setText(f"{base} for '{filter_text}'")
            self.stack.setCurrentIndex(1)
        else:
            self.empty_label.setText("")
            self.stack.setCurrentIndex(0)

    def _selected_filepaths(self) -> List[str]:
        """Devuelve rutas completas de TODA la selección (map proxy->source)."""
        sel_indexes = self.view.selectionModel().selectedIndexes()
        paths: List[str] = []
        for proxy_index in sel_indexes:
            if not proxy_index.isValid():
                continue
            src_index = self.view_model.proxy.mapToSource(proxy_index)
            path = self.view_model.model.data(src_index, ImageListModel.FILEPATH_ROLE)
            if path:
                paths.append(str(path))
        return list(dict.fromkeys(paths))

    def _on_busy_changed(self, busy: bool) -> None:
        """Feedback visual de estado ocupado."""
        self.loader.setVisible(busy)
        self.scan_button.setEnabled(not busy and bool(self.path_edit.text().strip()))
        self.setCursor(
            QtCore.Qt.CursorShape.BusyCursor
            if busy
            else QtCore.Qt.CursorShape.ArrowCursor
        )
        self.scan_button.setText("Escaneando…" if busy else "Escanear")

    def _toggle_view_mode(self) -> None:
        """Alterna entre vista de lista e iconos."""
        self._icon_mode = not self._icon_mode
        if self._icon_mode:
            self.view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            self.view.setGridSize(QtCore.QSize(100, 100))
            self.view.setSpacing(8)
            self.toggle_view_button.setText("Vista: Lista")
        else:
            self.view.setViewMode(QtWidgets.QListView.ViewMode.ListMode)
            self.view.setGridSize(QtCore.QSize())  # reset
            self.view.setSpacing(2)
            self.toggle_view_button.setText("Vista: Iconos")

    def _choose_folder(self) -> None:
        """Abre diálogo para elegir carpeta de escaneo."""
        start_dir = self.path_edit.text().strip() or QtCore.QDir.homePath()
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select folder to scan",
            start_dir,
            QtWidgets.QFileDialog.Option.ShowDirsOnly,
        )
        if path:
            self.path_edit.setText(path)
            self._update_counts_and_empty()

    def _start_scan(self, path: str) -> None:
        """Initiate scan."""
        self.view_model.scan(path)

    def _update_open_enabled(self) -> None:
        """sets the Open button enabled/disabled based on selection."""
        self.open_button.setEnabled(len(self._selected_filepaths()) > 0)

    def _open_selected_files(self) -> None:
        """opens the selected files with the default viewer."""
        paths = self._selected_filepaths()
        if not paths:
            return
        for p in paths:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(p))

    def _copy_selected_paths_to_clipboard(self) -> None:
        """Copies selected file paths to the clipboard."""
        paths = self._selected_filepaths()
        if not paths:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(paths))
        QtWidgets.QToolTip.showText(
            QtGui.QCursor.pos(), f"{len(paths)} path(s) copied to clipboard."
        )

    def _delete_selected_files(self) -> None:
        """Deletes the selected files after confirmation."""
        paths = self._selected_filepaths()
        if not paths:
            return

        if len(paths) == 1:
            base = os.path.basename(paths[0])
            msg = f"¿Do you really want to delete this file(s)?\n\n{base}"
        else:
            sample = "\n".join(os.path.basename(p) for p in paths[:5])
            more = f"\n…y {len(paths)-5} más" if len(paths) > 5 else ""
            msg = f"¿Delete {len(paths)} file(s)?\n\n{sample}{more}"

        resp = QtWidgets.QMessageBox.question(
            self,
            "Delete file(s)",
            msg,
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if resp != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        errors: List[str] = []
        for p in paths:
            try:
                os.remove(p)
                self.view_model.model.remove_path(p)
            except Exception as exc:
                errors.append(f"{os.path.basename(p)}: {exc}")

        if errors:
            QtWidgets.QMessageBox.critical(
                self, "Errors while deleting", "\n".join(errors)
            )

        self._update_counts_and_empty()

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        """Shows a context menu with actions for the selected item."""
        index_at_pos = self.view.indexAt(pos)
        if index_at_pos.isValid():
            selection_model = self.view.selectionModel()
            if not selection_model.isSelected(index_at_pos):
                selection_model.select(
                    index_at_pos,
                    QtCore.QItemSelectionModel.SelectionFlag.Select
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
            self.view.setCurrentIndex(index_at_pos)

        menu = QtWidgets.QMenu(self)
        act_open = menu.addAction("Open with default viewer")
        act_copy = menu.addAction("Copy paths to clipboard")
        act_delete = menu.addAction("Delete selected file(s)…")

        chosen = menu.exec(self.view.viewport().mapToGlobal(pos))
        if chosen == act_open:
            self._open_selected_files()
        elif chosen == act_copy:
            self._copy_selected_paths_to_clipboard()
        elif chosen == act_delete:
            self._delete_selected_files()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        key = event.key()
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self._open_selected_files()
            return
        if event.matches(QtGui.QKeySequence.StandardKey.Copy):
            self._copy_selected_paths_to_clipboard()
            return
        if key in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace):
            self._delete_selected_files()
            return
        super().keyPressEvent(event)

    def _restore_settings(self) -> None:
        s = QtCore.QSettings(APP_ORG, APP_NAME)
        size = s.value("win/size", QtCore.QSize(820, 580))
        pos = s.value("win/pos", QtCore.QPoint(100, 100))
        if not isinstance(size, QtCore.QSize):
            size = QtCore.QSize(820, 580)
        if not isinstance(pos, QtCore.QPoint):
            pos = QtCore.QPoint(100, 100)
        self.resize(size)
        self.move(pos)
        self.path_edit.setText(str(s.value("last/path", "")))
        self.filter_edit.setText(str(s.value("last/filter", "")))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        s = QtCore.QSettings(APP_ORG, APP_NAME)
        s.setValue("win/size", self.size())
        s.setValue("win/pos", self.pos())
        s.setValue("last/path", self.path_edit.text())
        s.setValue("last/filter", self.filter_edit.text())
        super().closeEvent(event)


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication.instance()
    created_here = False
    if not app:
        app = QtWidgets.QApplication(sys.argv)
        created_here = True

    window = MainWindow()
    window.show()

    if created_here:
        sys.exit(app.exec())
