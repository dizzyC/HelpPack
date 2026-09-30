import pytest

from helppack.diagnostics.models import DiagnosticStatus
from helppack.diagnostics.tls import INTERNET_KEY, POLICY_KEY, InternetTlsCheck


def run(monkeypatch, *, mask=None, supported=True, policy=None, disabled=False):
    monkeypatch.setattr("helppack.diagnostics.tls.platform.system", lambda: "Windows")

    def reader(hive, path, name):
        if path == INTERNET_KEY:
            return mask
        if path == POLICY_KEY:
            return policy
        if disabled and path.endswith(r"TLS 1.2\Client") and name == "Enabled":
            return 0
        return None

    return InternetTlsCheck(reader, lambda: supported).run(None)[0]


def test_missing_value_is_default_not_disabled(monkeypatch):
    result = run(monkeypatch)
    assert result.status == DiagnosticStatus.NORMAL
    assert "不能判定为关闭" in result.evidence[0].value
    assert not result.repair_suggestions


@pytest.mark.parametrize("mask", [0, 0x800, 0x2000])
def test_unchecked_supported_protocol_noticed(monkeypatch, mask):
    assert run(monkeypatch, mask=mask).status == DiagnosticStatus.NOTICE


def test_windows10_never_requires_tls13(monkeypatch):
    result = run(monkeypatch, mask=0x800, supported=False)
    assert result.status == DiagnosticStatus.NORMAL
    assert "不支持" in result.evidence[2].value


def test_schannel_disabled_and_policy_reported_no_mutations(monkeypatch):
    result = run(monkeypatch, mask=0x2800, policy=0x800, disabled=True)
    assert result.status == DiagnosticStatus.NOTICE
    assert "显式禁用" in result.evidence[1].value
    assert "联系管理员" in result.recommendations[0]
    assert not result.repair_suggestions


def test_read_failure_not_misdiagnosed(monkeypatch):
    monkeypatch.setattr("helppack.diagnostics.tls.platform.system", lambda: "Windows")

    def denied(*args):
        raise PermissionError()

    result = InternetTlsCheck(denied, lambda: True).run(None)[0]
    assert result.status == DiagnosticStatus.UNKNOWN
