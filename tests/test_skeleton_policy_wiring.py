import ast
from pathlib import Path
import unittest


class SkeletonPolicyWiringTests(unittest.TestCase):
    def _module(self, rel_path: str):
        src = Path(rel_path).read_text(encoding="utf-8")
        return src, ast.parse(src)

    def test_policy_declares_new_threshold_fields(self):
        src, _ = self._module("Service/gis_modules/skeleton/policy.py")
        required = [
            "voronoi_density_interval_m",
            "merge_shared_ratio_th",
            "parallel_close_dist_factor",
            "parallel_angle_deg",
            "parallel_offset_factor",
            "reconnect_boundary_buffer_m",
            "prune_ratio_limit",
        ]
        for name in required:
            self.assertIn(name, src)

    def test_generator_uses_policy_for_merge_and_pair_break(self):
        src, _ = self._module("Service/gis_modules/skeleton/generator.py")
        self.assertIn("policy.merge_distance_min_m", src)
        self.assertIn("policy.merge_distance_lane_width_ratio", src)
        self.assertIn("policy.merge_shared_ratio_th", src)
        self.assertIn("policy.pair_segment_break_bin_ratio", src)
        self.assertIn("policy.boundary_sample_min_step_m", src)

    def test_graph_builder_uses_policy_for_smoothing_shift_and_resample_floor(self):
        src, _ = self._module("Service/gis_modules/skeleton/graph_builder.py")
        self.assertIn("policy.parallel_close_dist_factor", src)
        self.assertIn("policy.parallel_angle_deg", src)
        self.assertIn("policy.parallel_offset_factor", src)
        self.assertIn("policy.reconnect_boundary_buffer_m", src)
        self.assertIn("policy.graph_smooth_target_shift_m", src)
        self.assertIn("policy.resample_min_step_m", src)


if __name__ == "__main__":
    unittest.main()
