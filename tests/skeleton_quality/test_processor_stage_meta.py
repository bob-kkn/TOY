import ast
from pathlib import Path
import unittest


class SkeletonProcessorStageMetaWiringTests(unittest.TestCase):
    def setUp(self):
        self.src = Path("Service/gis_modules/skeleton/processor.py").read_text(encoding="utf-8")
        self.module = ast.parse(self.src)

    def test_execute_supports_return_and_save_options(self):
        self.assertIn("return_stage_meta: bool = False", self.src)
        self.assertIn("stage_meta_output_path: Optional[str] = None", self.src)
        self.assertIn("self._finalize_result", self.src)

    def test_processor_tracks_and_exposes_stage_meta(self):
        self.assertIn("self._last_stage_meta", self.src)
        self.assertIn("def get_last_stage_meta", self.src)
        self.assertIn("stage_record = {\"stage\": stage, \"meta\": dict(meta)}", self.src)
        self.assertIn("def _save_stage_meta", self.src)


if __name__ == "__main__":
    unittest.main()
