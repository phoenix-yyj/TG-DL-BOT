from core.download_lifecycle import failed_dir, move_artifacts, remap_result_files, working_dir


def test_move_artifacts_keeps_processed_directory_structure(tmp_path):
    output = tmp_path / "downloads"
    tmp = working_dir(output)
    source = tmp / "package.zip"
    result = tmp / "package_processed" / "secret.txt"
    source.write_bytes(b"archive")
    result.parent.mkdir()
    result.write_text("secret", encoding="utf-8")

    move_artifacts([source, result], tmp, output)

    assert (output / "package.zip").read_bytes() == b"archive"
    assert (output / "package_processed" / "secret.txt").read_text(encoding="utf-8") == "secret"
    assert remap_result_files(["package_processed/secret.txt"], tmp, output) == [
        str(output / "package_processed" / "secret.txt")
    ]


def test_failed_directory_is_created_separately(tmp_path):
    output = tmp_path / "downloads"
    tmp = working_dir(output)
    source = tmp / "broken.zip"
    source.write_bytes(b"broken")

    move_artifacts([source], tmp, failed_dir(output))

    assert (output / "failed" / "broken.zip").read_bytes() == b"broken"
    assert not source.exists()
