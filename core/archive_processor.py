"""Post-download archive rule processing backed by the 7-Zip command line tool."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import re
from pathlib import Path
from typing import Any

ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}
VOLUME_PATTERN = re.compile(r"(?i)\.(zip|7z)\.\d{3}$|\.part\d+\.rar$|\.r\d{2}$")
VOLUME_GROUP_PATTERN = re.compile(r"(?i)^(.*?)(?:\.part\d+\.rar|\.(?:zip|7z)\.\d{3}|\.r\d{2})$")
MAX_EXTRACTED_BYTES = 20 * 1024 * 1024 * 1024
MAX_EXTRACTED_FILES = 100_000


class ArchiveProcessingError(RuntimeError):
    pass


def is_archive_path(path: Path) -> bool:
    """Return whether a path is a supported archive or a volume entry."""
    return path.suffix.lower() in ARCHIVE_EXTENSIONS or bool(VOLUME_PATTERN.search(path.name))


def archive_format(path: Path) -> str:
    match = re.search(r"(?i)\.(zip|7z)\.\d{3}$", path.name)
    if match:
        return match.group(1).lower()
    if re.search(r"(?i)\.part\d+\.rar$|\.r\d{2}$", path.name):
        return "rar"
    return path.suffix.lower().lstrip(".")


def volume_group_name(path: Path) -> str | None:
    match = VOLUME_GROUP_PATTERN.match(path.name)
    return match.group(1).lower() if match else None


def load_archive_config(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate the optional JSON configuration."""
    config_path = Path(path)
    if not config_path.exists():
        return {"passwords": [], "rules": []}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveProcessingError(f"无法读取压缩包配置：{exc}") from exc
    if not isinstance(data, dict):
        raise ArchiveProcessingError("压缩包配置必须是 JSON 对象")
    passwords = data.get("passwords", [])
    rules = data.get("rules", [])
    if not isinstance(passwords, list) or not all(isinstance(item, str) for item in passwords):
        raise ArchiveProcessingError("passwords 必须是字符串数组")
    if not isinstance(rules, list) or not all(isinstance(item, dict) for item in rules):
        raise ArchiveProcessingError("rules 必须是对象数组")
    return {"passwords": passwords, "rules": rules}


def _normalize_peer(value: Any) -> str:
    return str(value).strip().lstrip("@")


def matching_rules(config: dict[str, Any], chat_title: str | None,
                   chat_peer: str | int | None = None) -> list[dict[str, Any]]:
    """Match stable peer identifiers first, with title matching as fallback."""
    peer = _normalize_peer(chat_peer) if chat_peer is not None else None
    matched = []
    for rule in config.get("rules", []):
        rule_peer = rule.get("chat") or rule.get("chat_peer") or rule.get("username")
        if rule_peer is not None:
            if peer is not None and _normalize_peer(rule_peer) == peer:
                matched.append(rule)
            continue
        if chat_title and rule.get("chat_title") == chat_title:
            matched.append(rule)
    return matched


def describe_archive_config(config: dict[str, Any]) -> list[str]:
    """Explain configured archive behavior without exposing configured passwords."""
    descriptions: list[str] = []
    passwords = config.get("passwords", [])
    rules = config.get("rules", [])
    descriptions.append(
        f"通用密码表：{len(passwords)} 个候选密码；解压步骤未单独指定密码时会使用，也会用于单项直发压缩包；不记录密码内容。"
        if passwords else "通用密码表：未配置；解压步骤默认不尝试密码。"
    )
    if not rules:
        descriptions.append("群组规则：未配置；带链接的压缩包不会自动解压，单项直发压缩包仍会尝试通用密码表。")
    for index, rule in enumerate(rules, 1):
        name = str(rule.get("name") or f"规则 {index}")
        title = rule.get("chat_title")
        if not isinstance(title, str) or not title:
            descriptions.append(f"{name}：未设置有效 chat_title，因此不会匹配任何群组。")
            continue
        steps = rule.get("steps", [])
        step_descriptions = []
        if not isinstance(steps, list) or not steps:
            step_descriptions.append("无有效步骤（执行时会失败）")
        else:
            for step_index, step in enumerate(steps, 1):
                if not isinstance(step, dict):
                    step_descriptions.append(f"第 {step_index} 步格式无效")
                    continue
                action = step.get("action")
                if action == "extract":
                    candidate_passwords = step.get("passwords", passwords)
                    count = len(candidate_passwords) if isinstance(candidate_passwords, list) else 0
                    suffix = f"，按配置尝试 {count} 个密码" if count else "，不尝试密码"
                    step_descriptions.append(f"解压支持的压缩包{suffix}")
                elif action == "rename_extension":
                    step_descriptions.append(f"将扩展名 {step.get('from', '?')} 改为 {step.get('to', '?')}（不转换文件内容）")
                elif action == "recompress":
                    fmt = step.get("format", "?")
                    output = step.get("output") or f"源文件名_processed.{fmt}"
                    step_descriptions.append(f"重新压缩为 {fmt}，输出名 {output}")
                else:
                    step_descriptions.append(f"未知操作 {action!r}（执行时会失败）")
        descriptions.append(
            f"{name}：仅当来源群名与 {title!r} 完全一致时匹配；依序执行："
            + "；然后 ".join(step_descriptions)
            + "。同一群名有多条规则时按配置顺序尝试，前一条失败才继续下一条。"
        )
    descriptions.append("命中规则后原始下载文件会保留，处理产物写入其旁边的 *_processed 目录。")
    descriptions.append("压缩包只识别 ZIP、7z、RAR；规则优先按稳定的 chat/username 匹配，也兼容按 chat_title 匹配，不按文件名匹配。")
    return descriptions


def _archive_tool() -> str:
    tool = shutil.which("7zz") or shutil.which("7z")
    if not tool:
        raise ArchiveProcessingError("未安装 7-Zip（需要 7zz 或 7z）")
    return tool


def _run_7z(*args: str) -> None:
    result = subprocess.run(
        [_archive_tool(), *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=600, check=False,
    )
    if result.returncode != 0:
        # Tool output may contain archive names or password-related details; keep
        # only a short diagnostic and never log the command-line arguments.
        detail = (result.stdout or "").strip().splitlines()
        raise ArchiveProcessingError((detail[-1] if detail else "7-Zip 操作失败")[:240])


def _extract(archive: Path, destination: Path, passwords: list[str]) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    attempts: list[str | None] = list(passwords) if passwords else [None]
    errors: list[str] = []
    for password in attempts:
        args = ["x", "-y", "-bd", f"-o{destination}"]
        if password is not None:
            args.append(f"-p{password}")
        try:
            _run_7z(*args, str(archive))
            files = []
            total_bytes = 0
            root = destination.resolve()
            for path in destination.rglob("*"):
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ArchiveProcessingError("压缩包包含不安全的符号链接/路径")
                if path.is_file():
                    files.append(path)
                    total_bytes += path.stat().st_size
                    if len(files) > MAX_EXTRACTED_FILES or total_bytes > MAX_EXTRACTED_BYTES:
                        raise ArchiveProcessingError("解压产物超过安全限制")
            if not files:
                raise ArchiveProcessingError("压缩包没有可用文件")
            return files
        except ArchiveProcessingError as exc:
            errors.append(str(exc))
            shutil.rmtree(destination, ignore_errors=True)
            destination.mkdir(parents=True, exist_ok=True)
    raise ArchiveProcessingError(errors[-1] if errors else "压缩包解压失败")


def _safe_name(value: str) -> str:
    name = Path(value).name
    if not name or name in {".", ".."}:
        raise ArchiveProcessingError("无效的输出文件名")
    return name


def _run_rule(source: Path, rule: dict[str, Any], passwords: list[str], output_dir: Path) -> list[str]:
    steps = rule.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ArchiveProcessingError("规则必须包含非空 steps 步骤链")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".archive-work-", dir=output_dir) as work:
        workdir = Path(work)
        # Never let a rename step or archive tool mutate the preserved download.
        # Preserve compound suffixes such as ``.7z.001`` so volume entries
        # remain recognizable to the archive dispatcher.
        working_source = workdir / source.name
        shutil.copy2(source, working_source)
        source_group = volume_group_name(source)
        if source_group:
            # 7-Zip resolves volume siblings by filename.  Keep the original
            # names in the temporary workspace while preserving the original
            # download directory untouched.
            for sibling in source.parent.iterdir():
                if sibling.is_file() and volume_group_name(sibling) == source_group and sibling != source:
                    shutil.copy2(sibling, workdir / sibling.name)
        artifacts = [working_source]
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ArchiveProcessingError("步骤必须是对象")
            action = step.get("action")
            if action == "extract":
                next_artifacts: list[Path] = []
                archives_found = 0
                for artifact_index, artifact in enumerate(artifacts):
                    if not is_archive_path(artifact):
                        next_artifacts.append(artifact)
                        continue
                    archives_found += 1
                    dest = workdir / f"step-{index}-{artifact_index}"
                    step_passwords = step.get("passwords", passwords)
                    if not isinstance(step_passwords, list) or not all(isinstance(p, str) for p in step_passwords):
                        raise ArchiveProcessingError("extract.passwords 必须是字符串数组")
                    next_artifacts.extend(_extract(artifact, dest, step_passwords))
                if not archives_found:
                    raise ArchiveProcessingError(f"步骤 {index + 1} 未找到支持的压缩包")
                artifacts = next_artifacts
            elif action == "rename_extension":
                old_ext = step.get("from")
                new_ext = step.get("to")
                if not isinstance(old_ext, str) or not isinstance(new_ext, str) or not new_ext.startswith("."):
                    raise ArchiveProcessingError("rename_extension 需要 from 和带点的 to")
                renamed = []
                for artifact in artifacts:
                    if artifact.suffix.lower() == old_ext.lower():
                        target = artifact.with_suffix(new_ext)
                        artifact.rename(target)
                        renamed.append(target)
                    else:
                        renamed.append(artifact)
                artifacts = renamed
            elif action == "recompress":
                fmt = str(step.get("format", "")).lower().lstrip(".")
                if fmt not in {"zip", "7z"}:
                    raise ArchiveProcessingError("recompress.format 仅支持 zip、7z（RAR 可解压但不能创建）")
                archive_name = _safe_name(str(step.get("output", f"{source.stem}_processed.{fmt}")))
                archive_path = workdir / archive_name
                common_root = Path(os.path.commonpath([str(p.parent) for p in artifacts]))
                args = ["a", f"-t{fmt}", str(archive_path), *(str(p.relative_to(common_root)) for p in artifacts)]
                # Run from the artifact root so stored paths remain relative.
                result = subprocess.run(
                    [_archive_tool(), *args], cwd=common_root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, timeout=600, check=False,
                )
                if result.returncode != 0 or not archive_path.exists():
                    raise ArchiveProcessingError("重新压缩失败")
                artifacts = [archive_path]
            else:
                raise ArchiveProcessingError(f"不支持的步骤类型：{action}")
        if not artifacts:
            raise ArchiveProcessingError("步骤链没有产生最终产物")
        # Validate final archive artifacts with 7-Zip's integrity test.
        for artifact in artifacts:
            if is_archive_path(artifact):
                _run_7z("t", str(artifact))
        final_dir = output_dir / f"{source.stem}_processed"
        if final_dir.exists():
            raise ArchiveProcessingError(f"最终目录已存在：{final_dir.name}")
        staging_dir = Path(tempfile.mkdtemp(prefix=".archive-result-", dir=output_dir))
        results = []
        try:
            for artifact in artifacts:
                target = staging_dir / artifact.name
                shutil.copy2(artifact, target)
                results.append(str((final_dir / artifact.name).relative_to(output_dir)))
            staging_dir.rename(final_dir)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
        return results


def _unlock_single(source: Path, passwords: list[str], output_dir: Path) -> list[str]:
    if not is_archive_path(source):
        return []
    # 7-Zip can extract RAR but cannot create RAR archives.
    source_format = archive_format(source)
    fmt = "zip" if source_format == "rar" else source_format
    output = output_dir / f"{source.name}_unlocked.{fmt}"
    rule = {"steps": [
        {"action": "extract", "passwords": passwords},
        {"action": "recompress", "format": fmt, "output": output.name},
    ]}
    return _run_rule(source, rule, [], output_dir)


def _process_download(source_path: str, chat_title: str | None, link_type: str,
                      config: dict[str, Any], chat_peer: str | int | None = None,
                      result_dir: str | Path | None = None) -> dict[str, Any]:
    source = Path(source_path).resolve()
    if not is_archive_path(source):
        return {"status": "not_archive", "matched_rule": None, "files": [], "error": None}
    destination = Path(result_dir).resolve() if result_dir is not None else source.parent
    rules = matching_rules(config, chat_title, chat_peer) if link_type != "direct" else []
    if rules:
        errors = []
        for index, rule in enumerate(rules, 1):
            try:
                files = _run_rule(source, rule, config.get("passwords", []), destination)
                return {"status": "success", "matched_rule": str(rule.get("name") or index), "files": files, "error": None}
            except (ArchiveProcessingError, OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))
        return {"status": "failed", "matched_rule": None, "files": [], "error": "; ".join(errors)[-240:]}
    if link_type == "direct":
        try:
            files = _unlock_single(source, config.get("passwords", []), destination)
            return {"status": "success", "matched_rule": "password_table", "files": files, "error": None}
        except (ArchiveProcessingError, OSError, subprocess.SubprocessError) as exc:
            return {"status": "failed", "matched_rule": None, "files": [], "error": str(exc)[:240]}
    return {"status": "no_rule", "matched_rule": None, "files": [], "error": None}


async def process_download(source_path: str, chat_title: str | None, link_type: str,
                           config: dict[str, Any], chat_peer: str | int | None = None,
                           result_dir: str | Path | None = None) -> dict[str, Any]:
    """Run CPU/disk-bound archive operations off the asyncio event loop."""
    return await asyncio.to_thread(
        _process_download, source_path, chat_title, link_type, config, chat_peer, result_dir
    )
