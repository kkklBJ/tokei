import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "Tokei/Sources/Tokei"


class QuotaDetailTests(unittest.TestCase):
    def test_visible_panel_refreshes_detail_after_successful_usage_refresh(self):
        source = (SOURCES / "main.swift").read_text()
        refresh = source.split("private func performRefresh() {", 1)[1].split(
            "private func finishRefresh()", 1
        )[0]
        success = refresh.split("self.applyDisplayMode(updateStatusTitle: false)", 1)[1]
        self.assertRegex(
            success,
            r"if self\.popoverVisible\s*\{\s*QuotaDetailRepository\.shared\.load\(\)\s*\}",
        )

    def test_detail_refresh_projection_cache_and_inflight_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "quota-detail-check"
            subprocess.run(
                [
                    "swiftc", "-parse-as-library",
                    "-module-cache-path", str(Path(tmp) / "module-cache"),
                    str(SOURCES / "QuotaDetail.swift"),
                    str(ROOT / "tests/swift/QuotaDetailCheck.swift"),
                    "-o", str(binary),
                ],
                check=True, cwd=ROOT,
            )
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True, timeout=10
            )
            self.assertIn("quota detail checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
