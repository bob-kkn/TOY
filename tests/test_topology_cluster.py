from pathlib import Path
import unittest


class TopologyClusterSourceTests(unittest.TestCase):
    def test_topology_cluster_uses_distance_shared_ratio_and_axis_similarity(self):
        src = Path("Service/gis_modules/skeleton/topology_cluster.py").read_text(encoding="utf-8")
        self.assertIn("class EdgeFeature", src)
        self.assertIn("distance", src)
        self.assertIn("shared_ratio", src)
        self.assertIn("axis_similarity", src)
        self.assertIn("minimum_rotated_rectangle", src)

    def test_cluster_rule_protects_close_but_low_shared_low_axis_case(self):
        src = Path("Service/gis_modules/skeleton/topology_cluster.py").read_text(encoding="utf-8")
        self.assertIn("best.distance <= self._distance_th", src)
        self.assertIn("best.shared_ratio < shared_lo", src)
        self.assertIn("best.axis_similarity < axis_mid", src)
        self.assertIn("return False", src)


if __name__ == "__main__":
    unittest.main()
