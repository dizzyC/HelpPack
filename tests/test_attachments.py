from pathlib import Path

import pytest

from helppack.attachments import AttachmentError, add_attachments


def test_rejects_unsupported_screenshot(tmp_path: Path) -> None:
    file = tmp_path / "screen.gif"
    file.write_bytes(b"gif")
    with pytest.raises(AttachmentError, match="仅支持 PNG"):
        add_attachments([], [file])


def test_rejects_more_than_five_screenshots(tmp_path: Path) -> None:
    files = []
    for index in range(6):
        file = tmp_path / f"{index}.png"
        file.write_bytes(b"png")
        files.append(file)
    with pytest.raises(AttachmentError, match="最多只能添加 5 张"):
        add_attachments([], files)


def test_duplicate_names_get_safe_unique_export_names(tmp_path: Path) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "screen.JPG"
    second = second_dir / "screen.JPG"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    result = add_attachments([], [first, second])
    assert [item.export_name for item in result] == ["screen.JPG", "screen_2.jpg"]
