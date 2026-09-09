import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("TOKEI_UI_TESTS") == "1", "opt-in macOS WindowServer test")
class ContentFittingScrollViewTests(unittest.TestCase):
    def test_content_fitting_and_live_popover_resize(self):
        self.run_check([])

    def test_fullscreen_popover_resize_on_each_screen(self):
        self.run_check(["--fullscreen"])

    def run_check(self, args):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "content-fitting-check"
            sources = ROOT / "Tokei/Sources/Tokei"
            subprocess.run([
                "swiftc", "-parse-as-library", "-module-cache-path", "/tmp/tokei-ui-test-module-cache",
                str(sources / "ContentFittingScrollView.swift"),
                str(sources / "PanelPlacement.swift"),
                str(ROOT / "tests/swift/ContentFittingScrollViewCheck.swift"),
                "-o", str(binary),
            ], check=True, timeout=120)
            result = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("live popover resize checks passed", result.stdout, result.stderr)
            print(result.stdout.strip())
