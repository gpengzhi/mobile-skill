import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mobile_skill import observations


class ObservationTests(unittest.TestCase):
    def test_capture_reports_only_original_image_dimensions_for_coordinates(self):
        session = {"id": "abcd", "state": "active", "device_id": "device-a"}
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "obs.png"
            model_path = Path(directory) / "obs.jpg"
            with (
                patch("mobile_skill.observations.state.get_session", return_value=session),
                patch("mobile_skill.observations.android.require_device", return_value="device-a"),
                patch(
                    "mobile_skill.observations.state.screenshots_dir",
                    return_value=Path(directory),
                ),
                patch(
                    "mobile_skill.observations.android.capture",
                    return_value=(raw_path, (321, 654)),
                ),
                patch(
                    "mobile_skill.observations.android.compress_for_model",
                    return_value=(model_path, (1, 1)),
                ),
                patch("mobile_skill.observations.state.update_session") as update_session,
            ):
                result = observations.capture("abcd")

        self.assertEqual(result["width"], 321)
        self.assertEqual(result["height"], 654)
        self.assertEqual(result["coordinate_scale"], 999)
        self.assertEqual(result["coordinate_space"], "normalized_0_999")
        self.assertNotIn("model_width", result)
        self.assertNotIn("model_height", result)
        self.assertNotIn("scale", result)
        update_session.assert_called_once()


if __name__ == "__main__":
    unittest.main()
