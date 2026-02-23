from pathlib import Path
import unittest


class SkeletonSelectorWiringTests(unittest.TestCase):
    @staticmethod
    def _source(rel_path: str) -> str:
        return Path(rel_path).read_text(encoding="utf-8")

    def test_selector_uses_inside_curvature_and_length_scores(self):
        src = self._source("Service/gis_modules/skeleton/selector.py")
        self.assertIn("inside_ratio = self._inside_ratio(line, boundary_geom, policy)", src)
        self.assertIn("curvature_penalty = self._curvature_penalty(line)", src)
        self.assertIn("length_score = self._length_score(line, policy)", src)

    def test_selector_supports_threshold_plus_top_ratio(self):
        src = self._source("Service/gis_modules/skeleton/selector.py")
        self.assertIn("item[0] >= policy.selector_min_quality_score", src)
        self.assertIn("policy.selector_keep_top_ratio", src)


if __name__ == "__main__":
    unittest.main()
