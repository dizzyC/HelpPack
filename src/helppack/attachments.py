from __future__ import annotations

from pathlib import Path

from .models import Attachment

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_ATTACHMENTS = 5


class AttachmentError(ValueError):
    """Raised when an attachment cannot be accepted."""


def add_attachments(existing: list[Attachment], paths: list[str | Path]) -> list[Attachment]:
    if len(existing) + len(paths) > MAX_ATTACHMENTS:
        raise AttachmentError("最多只能添加 5 张截图，请先移除不需要的截图。")

    known = {item.path.resolve() for item in existing}
    result = list(existing)
    used_names = {item.export_name.lower() for item in existing}
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise AttachmentError("仅支持 PNG、JPG 或 JPEG 格式的截图。")
        if not path.is_file():
            raise AttachmentError(f"找不到截图文件：{path.name}")
        resolved = path.resolve()
        if resolved in known:
            continue
        export_name = _unique_name(path.name, used_names)
        result.append(Attachment(path=resolved, export_name=export_name))
        known.add(resolved)
        used_names.add(export_name.lower())
    return result


def _unique_name(name: str, used_names: set[str]) -> str:
    candidate = Path(name).name
    stem, suffix = Path(candidate).stem, Path(candidate).suffix.lower()
    index = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    return candidate
