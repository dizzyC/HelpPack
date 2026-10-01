import psutil

from helppack.diagnostics.checks import BatteryDiskHealthCheck
from helppack.diagnostics.engine import ScanContext
from helppack.diagnostics.models import DiagnosticStatus
from helppack.diagnostics.platform_support import detect_windows_support
from helppack.diagnostics.runner import CommandResult


def test_windows_10_and_11_compatibility_paths() -> None:
    windows10 = detect_windows_support("Windows", "10")
    windows11 = detect_windows_support("Windows", "11")
    assert windows10.supported and windows10.label == "Windows 10"
    assert windows11.supported and windows11.label == "Windows 11"
    assert detect_windows_support("Windows", "8.1").supported is False
    assert detect_windows_support("Linux", "6").supported is False


class UnsupportedRunner:
    def powershell_json(self, _script, *, timeout):
        return CommandResult(("powershell",), -1, "", "missing", unsupported=True)


def test_absent_battery_and_unsupported_disk_api_are_reported(monkeypatch) -> None:
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    context = ScanContext(UnsupportedRunner(), __import__("threading").Event())
    result = BatteryDiskHealthCheck().run(context)[0]
    assert result.status == DiagnosticStatus.UNSUPPORTED
    assert result.evidence[0].value == 'No battery detected'
    assert 'unsupported' in result.evidence[-1].value
