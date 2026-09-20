from types import SimpleNamespace

from core.i18n import get_locale, tr


def test_chinese_is_default_locale_and_command_names_are_preserved(monkeypatch):
    monkeypatch.delenv("BOT_LOCALE", raising=False)
    message = SimpleNamespace(from_user=SimpleNamespace(language_code="zh-CN"))

    assert get_locale(message) == "zh_CN"
    help_text = tr(message, "help")
    assert "本地合集" in help_text
    assert "/collect <合集名称>" in help_text
    assert "/resume" in help_text


def test_translation_uses_default_locale_when_telegram_language_is_missing():
    assert "欢迎使用" in tr(SimpleNamespace(from_user=SimpleNamespace()), "start")
