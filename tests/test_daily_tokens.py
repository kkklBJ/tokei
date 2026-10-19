import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "Tokei/Sources/Tokei"


class DailyTokensTests(unittest.TestCase):
    def test_calendar_ranges_and_tool_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "daily-token-check"
            subprocess.run([
                "swiftc", "-parse-as-library", "-module-cache-path", str(Path(tmp) / "modules"),
                str(SOURCES / "DailyTokenSeries.swift"),
                str(SOURCES / "QuotaHistoryProjection.swift"),
                str(SOURCES / "QuotaHistoryStore.swift"),
                str(ROOT / "tests/swift/DailyTokenSeriesCheck.swift"), "-o", str(binary),
            ], check=True, cwd=ROOT)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("daily token series checks passed", result.stdout)

    def test_daily_view_is_first_and_reuses_dashboard_daily_data(self):
        panel = (SOURCES / "PanelView.swift").read_text()
        section = panel.split("if mode == .quotaHistory {", 1)[1].split("} else", 1)[0]
        self.assertLess(section.index("DailyTokenHistoryView"), section.index("QuotaHistoryView"))
        view = (SOURCES / "DailyTokenHistoryView.swift").read_text()
        self.assertIn("DashboardRepository.shared", view)
        self.assertIn("store.syncEnabled && store.showAllDevices", view)
        self.assertIn("totals[day.date, default: 0] += day.tokens", view)
        self.assertIn(".onReceive(store.$usage.dropFirst())", view)
        quota = (SOURCES / "QuotaHistoryView.swift").read_text()
        self.assertNotIn("QuotaDailyChart", quota)
        self.assertNotIn("showsDailyTokens", quota)
