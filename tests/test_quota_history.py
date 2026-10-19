import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QuotaHistoryTests(unittest.TestCase):
    def test_tool_preference_and_sample_count_use_selected_tool(self):
        source = (ROOT / "Tokei/Sources/Tokei/QuotaHistoryView.swift").read_text()
        self.assertIn('@AppStorage("quotaHistoryTool") private var tool', source)
        self.assertIn('Text("\\(projection.hoverSamples.count)")', source)

    def test_minute_aggregation_activity_and_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "quota-history-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    "-framework", "Combine",
                    str(ROOT / "Tokei/Sources/Tokei/QuotaHistoryStore.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/QuotaHistoryProjection.swift"),
                    str(ROOT / "tests/swift/QuotaHistoryStoreCheck.swift"),
                    "-o", str(binary),
                ],
                check=True,
                cwd=ROOT,
            )
            result = subprocess.run(
                [str(binary)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("quota history store checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
