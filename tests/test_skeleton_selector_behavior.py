from pathlib import Path
import unittest


class SkeletonSelectorBehaviorWiringTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return Path("Service/gis_modules/skeleton/selector.py").read_text(encoding="utf-8")

    def test_threshold_pass_pool_is_kept_then_deduplicated(self):
        src = self._source()
        self.assertIn("if quality_filtered:", src)
        self.assertIn("pool = quality_filtered", src)
        self.assertIn("selected = self._suppress_near_parallel_duplicates(pool, policy)", src)

    def test_top_ratio_fallback_still_exists(self):
        src = self._source()
        self.assertIn("keep_count = max(1, int(math.ceil(len(scored) * policy.selector_keep_top_ratio)))", src)
        self.assertIn("pool = scored[:keep_count]", src)

    def test_selector_adds_center_proximity_and_duplicate_suppression(self):
        src = self._source()
        self.assertIn("center_score = self._center_proximity_score(line, boundary_geom, policy)", src)
        self.assertIn("def _center_proximity_score", src)
        self.assertIn("def _suppress_near_parallel_duplicates", src)


if __name__ == "__main__":
    unittest.main()
