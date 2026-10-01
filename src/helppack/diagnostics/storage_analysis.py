from __future__ import annotations

import json
import os
import stat
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .investigation import Finding, Investigation


def linked(path: Path) -> bool:
    value = path.lstat()
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & 0x400)


def assert_local_path(root: Path, path: Path) -> None:
    if not root.is_absolute() or not path.is_absolute() or ".." in path.parts or ".." in root.parts or not path.is_relative_to(root):
        raise ValueError("路径不在用户选择的目录范围内")
    for candidate in [root, *root.parents, *path.relative_to(root).parents]:
        checked = candidate if candidate.is_absolute() else root / candidate
        if linked(checked):
            raise ValueError("不能操作目录链接或重解析点")
    if linked(path):
        raise ValueError("不能操作文件链接或重解析点")


def classify(path: Path) -> str:
    if path.suffix.casefold() in {".exe", ".dll", ".sys", ".msi", ".pak"}:
        return "应用文件"
    if any(part.casefold() in {"cache", "caches", "缓存", "temp", "tmp", "code cache", "gpucache"} for part in path.parts):
        return "缓存（按目录名称推测）"
    return "用户文件/未知"


@dataclass(frozen=True)
class FileEntry:
    path: Path
    size: int
    mtime_ns: int
    inode: int
    category: str


@dataclass
class SpaceScan:
    root: Path
    files: list[FileEntry] = field(default_factory=list)
    ranking: list[tuple[str, int]] = field(default_factory=list)
    skipped: int = 0
    cancelled: bool = False
    limited: bool = False

    def markdown(self) -> str:
        result = Investigation("磁盘空间分析", "用户主动选择的目录")
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                result.findings.append(Finding("分区 " + part.device, "已读取", f"总量 {usage.total / 2**30:.1f} GiB，剩余 {usage.free / 2**30:.1f} GiB"))
            except OSError:
                continue
        result.findings.append(Finding("目录排行", "不完整" if self.cancelled or self.limited or self.skipped else "完成", "\n".join(f"{name}：{size / 2**20:.1f} MiB" for name, size in self.ranking[:30])))
        result.recommendations = [f"跳过链接/不可访问项目 {self.skipped} 个；取消={self.cancelled}；达到扫描上限={self.limited}。",
                                  "缓存分类是名称线索，不证明可以安全删除；应用文件和用户文件不自动清理。移出后可恢复，但同盘隔离区不会释放该分区空间。"]
        return result.markdown()


def scan_directory(raw_root: str, cancel, progress, max_entries: int = 200000, max_seconds: int = 120) -> SpaceScan:
    if not raw_root.strip():
        raise ValueError("请先选择扫描目录")
    root = Path(os.path.abspath(raw_root))
    if str(root).startswith("\\\\"):
        raise ValueError("仅支持本机普通目录，不扫描网络共享或设备命名空间")
    if not root.is_dir() or linked(root):
        raise ValueError("请选择真实目录，不支持目录链接")
    # Also reject a root reached through any reparse-point ancestor.
    for parent in root.parents:
        if linked(parent):
            raise ValueError("所选目录的上级是链接，不能扫描")
    result = SpaceScan(root)
    stack = [root]
    seen_files = set()
    ranking = {}
    deadline = time.monotonic() + max_seconds
    entries = 0
    while stack:
        if cancel.is_set():
            result.cancelled = True
            break
        if entries >= max_entries or time.monotonic() > deadline:
            result.limited = True
            break
        folder = stack.pop()
        try:
            assert_local_path(root, folder)
            with os.scandir(folder) as iterator:
                for item in iterator:
                    if cancel.is_set():
                        break
                    if entries >= max_entries or time.monotonic() > deadline:
                        result.limited = True
                        break
                    entries += 1
                    path = Path(item.path)
                    try:
                        info = item.stat(follow_symlinks=False)
                        if item.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or item.name == ".helppack-quarantine":
                            result.skipped += 1
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            stack.append(path)
                        elif stat.S_ISREG(info.st_mode):
                            # Windows DirEntry.stat may report inode=0; stat the file
                            # directly so hard-link dedup and change checks agree.
                            if not info.st_ino:
                                info = path.stat(follow_symlinks=False)
                            identity = (info.st_dev, info.st_ino)
                            if info.st_ino and identity in seen_files:
                                continue
                            seen_files.add(identity)
                            result.files.append(FileEntry(path, info.st_size, info.st_mtime_ns, info.st_ino, classify(Path(root.name) / path.relative_to(root))))
                            bucket = str(path.relative_to(root).parts[0])
                            ranking[bucket] = ranking.get(bucket, 0) + info.st_size
                    except OSError:
                        result.skipped += 1
                    if entries % 200 == 0:
                        progress(0, f"已检查 {entries} 项，扫描可取消")
        except (OSError, ValueError):
            result.skipped += 1
        if result.limited:
            break
    result.ranking = sorted(ranking.items(), key=lambda row: row[1], reverse=True)
    result.cancelled |= cancel.is_set()
    progress(100, f"目录扫描结束，共 {len(result.files)} 个文件")
    return result


@dataclass
class MoveReceipt:
    root: Path
    source: Path
    destination: Path
    inode: int


def quarantine_one(scan: SpaceScan, entry: FileEntry, *, confirmed: bool) -> MoveReceipt:
    if not confirmed:
        raise PermissionError("清理需要逐项确认")
    if entry not in scan.files or not entry.category.startswith("缓存"):
        raise ValueError("只支持预览中的缓存候选；不会移出应用或用户文件")
    assert_local_path(scan.root, entry.path)
    info = entry.path.stat()
    if (info.st_size, info.st_mtime_ns, info.st_ino) != (entry.size, entry.mtime_ns, entry.inode):
        raise ValueError("文件在扫描后发生变化，请重新扫描")
    for variable in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)"):
        protected = os.environ.get(variable)
        if protected and entry.path.is_relative_to(Path(protected)):
            raise ValueError("不清理 Windows 或应用安装目录")
    base = scan.root / ".helppack-quarantine"
    if base.exists() and linked(base):
        raise ValueError("隔离目录不能是链接")
    folder = base / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    destination = folder / "payload"
    # A local recovery receipt survives app restart; it is not included in reports.
    (folder / "receipt.json").write_text(json.dumps({"source": str(entry.path.relative_to(scan.root)), "inode": info.st_ino, "file": destination.name}), encoding="utf-8")
    entry.path.rename(destination)
    return MoveReceipt(scan.root, entry.path, destination, info.st_ino)


def recovery_receipts(root: Path) -> list[MoveReceipt]:
    receipts = []
    base = root / ".helppack-quarantine"
    if not base.exists():
        return receipts
    assert_local_path(root, base)
    for folder in list(base.iterdir())[:500]:
        try:
            if linked(folder) or not folder.is_dir():
                continue
            manifest = folder / "receipt.json"
            assert_local_path(root, manifest)
            value = json.loads(manifest.read_text(encoding="utf-8"))
            source, destination = root / value["source"], manifest.parent / value["file"]
            if Path(value["source"]).is_absolute() or Path(value["file"]).name != value["file"]:
                continue
            assert_local_path(root, destination)
            if ".." in source.parts or not source.is_relative_to(root) or not destination.is_file():
                continue
            receipts.append(MoveReceipt(root, source, destination, int(value["inode"])))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return sorted(receipts, key=lambda r: (r.destination.parent / "receipt.json").stat().st_mtime_ns)


def restore_one(receipt: MoveReceipt, *, confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("恢复需要确认")
    assert_local_path(receipt.root, receipt.destination)
    if receipt.destination.stat().st_ino != receipt.inode or receipt.source.exists():
        raise ValueError("文件已变化或原位置已有同名文件，不能覆盖")
    if not receipt.source.parent.is_dir():
        raise ValueError("原目录已不存在，不能自动恢复")
    assert_local_path(receipt.root, receipt.source.parent)
    receipt.destination.rename(receipt.source)
