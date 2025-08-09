from pathlib import Path
import tempfile
from image_finder import scan_images, IMAGE_EXTENSIONS


def test_scan_images_basic(tmp_path: Path) -> None:
    # image files
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.JPG").write_bytes(b"x")
    # no- image files
    (tmp_path / "c.txt").write_text("nope")
    # subcart directory with an image
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.webp").write_bytes(b"x")

    res = scan_images(str(tmp_path))
    assert res == sorted(
        [
            str((tmp_path / "a.png").resolve()),
            str((tmp_path / "b.JPG").resolve()),
            str((sub / "d.webp").resolve()),
        ]
    )


def test_scan_images_empty_dir(tmp_path: Path) -> None:
    assert scan_images(str(tmp_path)) == []


def test_scan_images_custom_exts(tmp_path: Path) -> None:
    (tmp_path / "x.tif").write_bytes(b"x")
    (tmp_path / "y.raw").write_bytes(b"x")
    res = scan_images(str(tmp_path), exts=(".tif",))
    assert len(res) == 1 and res[0].endswith("x.tif")
    assert ".tif" in IMAGE_EXTENSIONS
