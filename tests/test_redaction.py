from helppack.redaction import redact_text


def test_redacts_personal_data_and_secrets() -> None:
    source = (
        r"用户 Alice 位于 C:\Users\Alice\Desktop\shot.png，"
        "IPv4=192.168.1.42 IPv6=2001:db8::8 MAC=AA-BB-CC-DD-EE-FF "
        "邮箱 alice@example.com api_key=sk-abcdefghijklmnopqrstuvwxyz "
        "Authorization: Bearer abc.def.ghi password=hunter2"
    )
    result = redact_text(source, username="Alice", home_path=r"C:\Users\Alice")

    assert "<USERNAME>" in result
    assert "<USER_PATH>" in result
    assert result.count("<IP_ADDRESS>") == 2
    assert "<MAC_ADDRESS>" in result
    assert "<EMAIL>" in result
    assert result.count("<REDACTED_SECRET>") >= 3
    for secret in ("192.168.1.42", "2001:db8::8", "AA-BB-CC-DD-EE-FF", "hunter2", "alice@example.com"):
        assert secret not in result


def test_invalid_ipv4_is_not_changed() -> None:
    assert "999.1.1.1" in redact_text("版本 999.1.1.1", username="", home_path="")


def test_extra_attachment_path_is_removed() -> None:
    source = r"截图：D:\private\name\shot.png"
    assert redact_text(source, username="", home_path="", extra_paths=[r"D:\private\name\shot.png"]) == "截图：<USER_PATH>"


def test_username_embedded_in_windows_task_name_is_removed() -> None:
    result = redact_text("VendorUpdate_Alice_LogonTask", username="Alice", home_path="")

    assert result == "VendorUpdate_<USERNAME>_LogonTask"


def test_quoted_secret_keeps_surrounding_structure_valid() -> None:
    result = redact_text('prefix password="fake value" suffix', username="", home_path="")
    assert result == "prefix password=<REDACTED_SECRET> suffix"


def test_mixed_case_nested_bearer_github_and_api_keys() -> None:
    source = (
        "Nested{PaSsWoRd:'Fake Pass'} Authorization: Bearer fake.header.signature "
        "github=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 API_KEY=FAKE-API-KEY-123 token=FAKE-TOKEN-123"
    )
    result = redact_text(source, username="", home_path="")
    for secret in (
        "Fake Pass",
        "fake.header.signature",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "FAKE-API-KEY-123",
        "FAKE-TOKEN-123",
    ):
        assert secret not in result
    assert result.count("<REDACTED_SECRET>") >= 5
