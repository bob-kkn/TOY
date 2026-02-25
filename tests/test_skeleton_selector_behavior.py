from pathlib import Path
import unittest


class SkeletonSelectorBehaviorWiringTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return Path("Service/gis_modules/skeleton/selector.py").read_text(encoding="utf-8")

    def test_threshold_pass_lines_are_all_kept(self):
        src = self._source()
        self.assertIn("if quality_filtered:", src)
        self.assertIn("selected = [line for _, line in quality_filtered]", src)

    def test_top_ratio_fallback_still_exists(self):
        src = self._source()
        self.assertIn("keep_count = max(1, int(math.ceil(len(scored) * policy.selector_keep_top_ratio)))", src)
        self.assertIn("selected = [line for _, line in scored[:keep_count]]", src)


if __name__ == "__main__":
    unittest.main()
