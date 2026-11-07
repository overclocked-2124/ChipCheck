import tempfile
import unittest
from pathlib import Path

from activequal.service.bundle import verify_bundle
from activequal.service.exporter import make_exporter
from activequal.tools.stack import SimulatedStack


class ExporterTests(unittest.TestCase):
    def test_export_after_a_campaign_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SimulatedStack("B1w", planner="tpe", seed=3, discovery=20, verification=8) as stack:
                stack.run()
                result = make_exporter(Path(tmp) / "exports")(stack.backend, stack.campaign_id)
                self.assertEqual(verify_bundle(result["bundlePath"]), [])
                self.assertIn("markdown", result)


if __name__ == "__main__":
    unittest.main()
