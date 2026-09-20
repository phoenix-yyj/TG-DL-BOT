def test_retry_classification_and_media_size_helpers():
    from core.bot import get_media_file_size, is_retryable_error, parse_link

    media = type("Message", (), {"document": None, "video": type("Video", (), {"file_size": 42})()})()
    assert get_media_file_size(media) == 42
    assert is_retryable_error(TimeoutError())
    assert not is_retryable_error(ValueError("invalid media type"))
    assert parse_link("https://t.me/example_channel/42") == ("example_channel", 42, "public")
