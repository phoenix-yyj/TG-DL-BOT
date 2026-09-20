"""Regression checks for command-handler module loading."""

import inspect


def test_stats_handler_imports_without_removed_file_manager():
    from core.handlers import stats

    assert inspect.iscoroutinefunction(stats.stats_command)


def test_cleanup_handler_uses_native_file_operations():
    from core.handlers import cleanup

    assert inspect.iscoroutinefunction(cleanup.cleanup_command)
    assert hasattr(cleanup, "os")
    assert hasattr(cleanup, "shutil")
