import ast
from pathlib import Path
import unittest


class SkeletonQualityRegressionWiringTests(unittest.TestCase):
    def setUp(self):
        self.src = Path("tools/eval_skeleton.py").read_text(encoding="utf-8")
        self.module = ast.parse(self.src)

    def test_quality_metrics_are_defined(self):
        required_keys = [
            '"component_count"',
            '"leaf_count"',
            '"branch_count"',
            '"total_length"',
            '"length_change_rate"',
            '"outside_ratio"',
            '"parallel_pair_found"',
        ]
        for key in required_keys:
            self.assertIn(key, self.src)

    def test_gate_checks_are_defined(self):
        required_checks = [
            '"max_components"',
            '"min_leaf_count"',
            '"max_branch_count"',
            '"max_length_change_rate"',
            '"max_outside_ratio"',
            '"parallel_pair_required"',
            '"passed": all(checks.values())',
        ]
        for key in required_checks:
            self.assertIn(key, self.src)


if __name__ == "__main__":
    unittest.main()
