from pathlib import Path
from types import SimpleNamespace

import pytest

from core import archive_processor as processor


def _fake_extract(monkeypatch, contents):
    calls = []

    def run(*args):
        calls.append(args)
        if args[0] == "x":
            destination = Path(next(arg[2:] for arg in args if arg.startswith("-o")))
            archive = Path(args[-1])
            destination.mkdir(parents=True, exist_ok=True)
            for name, content in contents(archive).items():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        elif args[0] == "t":
            return
        else:
            raise AssertionError(args)

    monkeypatch.setattr(processor, "_run_7z", run)
    monkeypatch.setattr(processor, "_archive_tool", lambda: "7z")
    return calls


def test_matching_rules_uses_exact_source_title():
    config = {"rules": [{"chat_title": "Movies"}, {"chat_title": "Movies 2"}]}

    assert processor.matching_rules(config, "Movies") == [config["rules"][0]]
    assert processor.matching_rules(config, "movies") == []
    assert processor.matching_rules(config, None) == []


def test_matching_rules_prefers_stable_peer_over_changing_title():
    rule = {"chat": "example_public_group", "chat_title": "旧标题"}
    config = {"rules": [rule]}

    assert processor.matching_rules(config, "新标题", "@example_public_group") == [rule]
    assert processor.matching_rules(config, "旧标题", "other_group") == []


def test_link_archive_without_matching_title_stays_unchanged(tmp_path):
    source = tmp_path / "item.zip"
    source.write_bytes(b"archive")

    result = processor._process_download(
        str(source), "Different group", "public",
        {"passwords": ["unused"], "rules": [{"chat_title": "Group", "steps": [{"action": "extract"}]}]},
    )

    assert result == {"status": "no_rule", "matched_rule": None, "files": [], "error": None}
    assert source.read_bytes() == b"archive"


def test_link_rules_fall_back_in_order_until_complete(tmp_path, monkeypatch):
    source = tmp_path / "0001_item.zip"
    source.write_bytes(b"archive")
    _fake_extract(monkeypatch, lambda _archive: {"result.txt": "ok"})
    config = {"passwords": [], "rules": [
        {"name": "broken", "chat_title": "Group", "steps": [{"action": "unknown"}]},
        {"name": "working", "chat_title": "Group", "steps": [{"action": "extract"}]},
    ]}

    result = processor._process_download(str(source), "Group", "public", config)

    assert result["status"] == "success"
    assert result["matched_rule"] == "working"
    assert (tmp_path / result["files"][0]).read_text() == "ok"
    assert source.read_bytes() == b"archive"


def test_result_dir_keeps_source_outside_published_output(tmp_path, monkeypatch):
    source = tmp_path / ".sources" / "group" / "package.zip"
    result_dir = tmp_path / "published"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"archive")
    _fake_extract(monkeypatch, lambda _archive: {"result.txt": "ok"})

    result = processor._process_download(
        str(source), "Group", "public",
        {"passwords": [], "rules": [{"chat_title": "Group", "steps": [{"action": "extract"}]}]},
        result_dir=result_dir,
    )

    assert source.exists()
    assert (result_dir / result["files"][0]).read_text(encoding="utf-8") == "ok"
    assert not (tmp_path / ".sources" / "group" / "result.txt").exists()


def test_direct_archive_tries_passwords_and_recompresses_without_password(tmp_path, monkeypatch):
    source = tmp_path / "package.zip"
    source.write_bytes(b"encrypted")
    calls = []

    def run(*args):
        calls.append(args)
        if args[0] == "x":
            password = next((arg[2:] for arg in args if arg.startswith("-p")), None)
            if password != "right":
                raise processor.ArchiveProcessingError("wrong password")
            destination = Path(next(arg[2:] for arg in args if arg.startswith("-o")))
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "secret.txt").write_text("secret")
        elif args[0] != "t":
            raise AssertionError(args)

    monkeypatch.setattr(processor, "_run_7z", run)
    monkeypatch.setattr(processor, "_archive_tool", lambda: "7z")

    def fake_subprocess(args, **kwargs):
        Path(args[3]).write_bytes(b"unencrypted")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(processor.subprocess, "run", fake_subprocess)
    result = processor._process_download(str(source), None, "direct", {"passwords": ["wrong", "right"], "rules": []})

    assert result["status"] == "success"
    assert result["matched_rule"] == "password_table"
    assert [next((arg[2:] for arg in call if arg.startswith("-p")), None)
            for call in calls if call[0] == "x"] == ["wrong", "right"]
    assert (tmp_path / result["files"][0]).read_bytes() == b"unencrypted"
    assert source.exists()


def test_explicit_nested_extract_handles_extension_change(tmp_path, monkeypatch):
    source = tmp_path / "outer.zip"
    source.write_bytes(b"outer")

    def contents(archive):
        if archive.suffix == ".zip":
            return {"inner.dat": "fake inner archive"}
        assert archive.suffix == ".7z"
        return {"final.txt": "done"}

    _fake_extract(monkeypatch, contents)
    config = {"passwords": [], "rules": [{
        "name": "nested", "chat_title": "Group", "steps": [
            {"action": "extract"},
            {"action": "rename_extension", "from": ".dat", "to": ".7z"},
            {"action": "extract"},
        ],
    }]}

    result = processor._process_download(str(source), "Group", "public", config)

    assert result["status"] == "success"
    assert (tmp_path / result["files"][0]).read_text() == "done"


def test_config_missing_defaults_empty(tmp_path):
    assert processor.load_archive_config(tmp_path / "missing.json") == {"passwords": [], "rules": []}


def test_archive_config_description_explains_order_and_hides_passwords():
    descriptions = processor.describe_archive_config({
        "passwords": ["do-not-log"],
        "rules": [{"name": "群组规则", "chat_title": "小白菜分拣中心", "steps": [
            {"action": "extract"},
            {"action": "recompress", "format": "zip", "output": "整理.zip"},
        ]}],
    })

    log_text = "\n".join(descriptions)
    assert "小白菜分拣中心" in log_text
    assert "完全一致" in log_text
    assert "重新压缩为 zip" in log_text
    assert "do-not-log" not in log_text
