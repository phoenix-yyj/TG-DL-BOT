"""Filesystem lifecycle helpers for downloads and post-processing."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable


def working_dir(output_dir: Path) -> Path:
    path = output_dir / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def failed_dir(output_dir: Path) -> Path:
    path = output_dir / "failed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _top_level(path: Path, root: Path) -> Path:
    """Return the direct child that owns *path*, rejecting path escapes."""
    root = root.resolve()
    path = path.resolve()
    relative = path.relative_to(root)
    if not relative.parts:
        raise ValueError("不能移动工作目录本身")
    return root / relative.parts[0]


def move_artifacts(paths: Iterable[Path], work_dir: Path, destination: Path) -> list[Path]:
    """Move tracked artifacts from ``tmp`` to a terminal directory.

    A processed result can be nested below a generated directory.  Moving the
    top-level owner keeps that directory intact and makes the operation safe
    to replay from the returned paths.
    """
    destination.mkdir(parents=True, exist_ok=True)
    roots: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        root = _top_level(path, work_dir)
        if root not in roots:
            roots.append(root)
    moved: list[Path] = []
    for root in roots:
        target = destination / root.name
        if target.exists():
            raise FileExistsError(f"目标文件已存在：{target}")
        shutil.move(str(root), str(target))
        moved.append(target)
    return moved


def remap_result_files(files: Iterable[str], work_dir: Path, destination: Path) -> list[str]:
    """Translate archive-processor relative result paths after a move."""
    result: list[str] = []
    for file_name in files:
        path = Path(file_name)
        if path.is_absolute():
            relative = path.resolve().relative_to(work_dir.resolve())
        else:
            relative = path
        result.append(str(destination / relative))
    return result
