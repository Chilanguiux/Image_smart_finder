from PySide6 import QtCore
from image_finder import ViewModel, ImageListModel


def test_viewmodel_filter() -> None:
    vm = ViewModel()
    vm.model.replace(["a.png", "b.jpg", "notes.txt"])
    vm.set_filter("a.")
    shown = vm.proxy.rowCount(QtCore.QModelIndex())
    assert shown == 1
