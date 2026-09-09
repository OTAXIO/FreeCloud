import unittest
from unittest.mock import Mock

from wyy_assist.adb import AdbClient, AdbError, foreground_package


class AppTests(unittest.TestCase):
    def test_current_focus_wins_over_stale_focused_app(self):
        self.assertEqual(foreground_package("mCurrentFocus=Window{0 u0 com.android.launcher3/.Launcher}\n"
                                           "mFocusedApp=Activity{0 com.example.app/.Main}"), "com.android.launcher3")
        self.assertEqual(foreground_package("mCurrentFocus=null\nmFocusedApp=com.example.app/.Main"), "")
        self.assertEqual(foreground_package("com.example.app/.Main"), "com.example.app")

    def test_resolved_launcher_is_cached(self):
        adb = AdbClient("adb.exe")
        adb.run = Mock(return_value="priority=0\ncom.android.launcher3/.Launcher\n")
        self.assertEqual(adb.launcher_package(), "com.android.launcher3")
        adb.launcher_package()
        adb.run.assert_called_once()

    def test_launch_uses_only_configured_apps_resolved_component(self):
        adb = AdbClient("adb.exe")
        adb.run = Mock(side_effect=["priority=0\ncom.example.app/.Main\n", "Status: ok"])
        adb.launch_app("com.example.app")
        self.assertEqual(adb.run.call_args.args, ("shell", "am", "start", "-W", "-n", "com.example.app/.Main"))

    def test_foreign_component_and_launch_error_are_rejected(self):
        for results in (["com.foreign.app/.Main"], ["com.example.app/.Main", "Error: permission denied"]):
            with self.subTest(results=results):
                adb = AdbClient("adb.exe")
                adb.run = Mock(side_effect=results)
                with self.assertRaises(AdbError):
                    adb.launch_app("com.example.app")
