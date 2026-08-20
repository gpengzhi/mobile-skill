import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from mobile_skill import android
from PIL import Image


class AndroidTests(unittest.TestCase):
    def test_parse_devices(self):
        output = (
            "List of devices attached\n"
            "device-a\tdevice usb:1-1 product:generic model:generic device:generic\n"
            "device-b\toffline usb:2-1\n"
        )
        with patch("mobile_skill.android.run_adb", return_value=output):
            devices = android.list_devices()
        self.assertEqual(devices[0]["serial"], "device-a")
        self.assertEqual(devices[0]["model"], "generic")
        self.assertEqual(devices[1]["state"], "offline")

    def test_require_device_reports_authorization_state(self):
        with patch(
            "mobile_skill.android.list_devices",
            return_value=[{"serial": "device-a", "state": "unauthorized"}],
        ):
            with self.assertRaises(android.AndroidError) as caught:
                android.require_device()

        self.assertEqual(caught.exception.code, "device_unauthorized")

    def test_validate_point(self):
        android.validate_point(0, 0, 100, 200)
        android.validate_point(99, 199, 100, 200)
        with self.assertRaises(android.AndroidError):
            android.validate_point(100, 0, 100, 200)

    def test_png_size(self):
        width, height = 37, 53
        image = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + width.to_bytes(
            4, "big"
        ) + height.to_bytes(4, "big")
        self.assertEqual(android.png_size(image), (width, height))

    def test_compress_for_model_preserves_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory, "source.png")
            output_path = Path(directory, "model.jpg")
            source_size = (17, 29)
            target_width = 7
            Image.new("RGBA", source_size, "white").save(source_path)

            _, size = android.compress_for_model(source_path, output_path, target_width=target_width)

            self.assertEqual(size, (target_width, round(source_size[1] * target_width / source_size[0])))
            with Image.open(output_path) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.size, size)

    def test_wait(self):
        with patch("mobile_skill.android.time.sleep") as sleep:
            android.wait(500)
        sleep.assert_called_once_with(0.5)

        with self.assertRaises(android.AndroidError):
            android.wait(0)

    def test_double_tap(self):
        with (
            patch("mobile_skill.android.ensure_unlocked"),
            patch("mobile_skill.android.run_adb") as run_adb,
            patch("mobile_skill.android.time.sleep") as sleep,
        ):
            android.double_tap("device-a", 100, 200, 120, (320, 480))

        self.assertEqual(run_adb.call_count, 2)
        self.assertEqual(run_adb.call_args_list[0], run_adb.call_args_list[1])
        sleep.assert_called_once_with(0.12)

        with patch("mobile_skill.android.ensure_unlocked"):
            with self.assertRaises(android.AndroidError):
                android.double_tap("device-a", 100, 200, 0, (320, 480))

    def test_input_capabilities(self):
        with patch(
            "mobile_skill.android.run_adb",
            side_effect=[
                "com.example/.Ime\n",
                "com.example/.Ime\n",
                "com.example/.Ime\ncom.github.uiautomator/.AdbKeyboard\n",
            ],
        ):
            capabilities = android.input_capabilities("device-a")

        self.assertEqual(capabilities["ascii"]["status"], "ready")
        self.assertEqual(capabilities["unicode"]["status"], "ready")
        self.assertEqual(capabilities["default_ime"], "com.example/.Ime")

    def test_unicode_input_temporarily_switches_ime(self):
        with (
            patch("mobile_skill.android.ensure_unlocked"),
            patch("mobile_skill.android.time.sleep"),
            patch(
                "mobile_skill.android.run_adb",
                side_effect=[
                    "com.github.uiautomator/.AdbKeyboard\n",
                    "com.example/.Ime\n",
                    "com.example/.Ime\n",
                    "Input method enabled\n",
                    "Input method selected\n",
                    "Broadcast completed: result=-1\n",
                    "Input method selected\n",
                    "Input method disabled\n",
                ],
            ) as run_adb,
        ):
            method = android.type_text("device-a", "测试文本")

        self.assertEqual(method, "adb-keyboard")
        broadcast = run_adb.call_args_list[5]
        self.assertEqual(
            broadcast.args[0:5],
            ("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_INPUT_TEXT"),
        )

    def test_unicode_input_without_helper_has_stable_error(self):
        with (
            patch("mobile_skill.android.ensure_unlocked"),
            patch("mobile_skill.android.run_adb", return_value="com.example/.Ime\n"),
        ):
            with self.assertRaises(android.AndroidError) as caught:
                android.type_text("device-a", "测试文本")

        self.assertEqual(caught.exception.code, "unicode_input_unavailable")

    def test_unicode_input_rejects_unfocused_field(self):
        with (
            patch("mobile_skill.android.ensure_unlocked"),
            patch("mobile_skill.android.time.sleep"),
            patch(
                "mobile_skill.android.run_adb",
                side_effect=[
                    "com.github.uiautomator/.AdbKeyboard\n",
                    "com.github.uiautomator/.AdbKeyboard\n",
                    "com.example/.Ime\n",
                    "Input method selected\n",
                    "Broadcast completed: result=0\n",
                    "Input method selected\n",
                ],
            ),
        ):
            with self.assertRaises(android.AndroidError) as caught:
                android.type_text("device-a", "测试文本")

        self.assertEqual(caught.exception.code, "unicode_input_failed")

    def test_unlocked_gate(self):
        with patch(
            "mobile_skill.android.run_adb",
            side_effect=["mWakefulness=Awake", "isKeyguardShowing=false"],
        ):
            android.ensure_unlocked("device-a")

    def test_locked_gate(self):
        with patch(
            "mobile_skill.android.run_adb",
            side_effect=["mWakefulness=Awake", "isKeyguardShowing=true"],
        ):
            with self.assertRaises(android.AndroidError) as caught:
                android.ensure_unlocked("device-a")
        self.assertEqual(caught.exception.code, "device_locked")

    def test_launch_app_requires_exact_installed_package(self):
        with (
            patch("mobile_skill.android.ensure_unlocked"),
            patch("mobile_skill.android.run_adb", return_value=""),
        ):
            with self.assertRaises(android.AndroidError) as caught:
                android.launch_app("device-a", "com.example.missing")

        self.assertEqual(caught.exception.code, "app_not_found")

    def test_launch_app_uses_exact_package(self):
        with (
            patch("mobile_skill.android.ensure_unlocked"),
            patch(
                "mobile_skill.android.run_adb",
                side_effect=[
                    "package:com.example.app\n",
                    "Events injected: 1\n",
                ],
            ) as run_adb,
        ):
            package = android.launch_app("device-a", "com.example.app")

        self.assertEqual(package, "com.example.app")
        self.assertEqual(
            run_adb.call_args_list[1].args,
            ("shell", "monkey", "-p", "com.example.app", "1"),
        )
