from pathlib import Path
import unittest


class SkeletonGraphBuilderRegressionTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return Path("Service/gis_modules/skeleton/graph_builder.py").read_text(encoding="utf-8")

    def test_parallel_split_tracks_both_original_and_shifted_keys(self):
        src = self._source()
        self.assertIn("key2 = self._canonical_edge_key(u2, v2)", src)
        self.assertIn("moved_edges.add(self._canonical_edge_key(start, end))", src)

    def test_reconnect_uses_buffer_as_fallback_not_double_gate(self):
        src = self._source()
        self.assertIn("is_within_buffer = geom.within(boundary.buffer(policy.reconnect_boundary_buffer_m))", src)
        self.assertIn("if inside_ratio < policy.reconnect_min_inside_ratio and not is_within_buffer:", src)

    def test_morph_orientation_uses_distance_based_matching(self):
        src = self._source()
        self.assertIn("direct_cost = self._point_distance(start, old_u) + self._point_distance(end, old_v)", src)
        self.assertIn("reverse_cost = self._point_distance(start, old_v) + self._point_distance(end, old_u)", src)


if __name__ == "__main__":
    unittest.main()
