"""OS boundary tests; no GUI, Explorer, Finder, or network connection is opened."""
from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_support as platform


class PlatformTests(unittest.TestCase):
    def test_windows_localized_ipconfig_and_real_23bit_mask(self):
        text = """无线局域网适配器 WLAN:
   IPv4 地址 . . . . . . . . . . . . : 192.168.11.37(首选)
   子网掩码  . . . . . . . . . . . . : 255.255.254.0
   默认网关. . . . . . . . . . . . . : 192.168.10.1
"""
        self.assertEqual(platform.parse_interfaces(text, "win32"), [("192.168.11.37", "192.168.10.0/23")])

    def test_windows_multiple_network_adapters(self):
        text = """Ethernet adapter Ethernet:
 IPv4 Address. . . . . . . . . . . : 10.24.9.17
 Subnet Mask . . . . . . . . . . . : 255.255.0.0
 Default Gateway . . . . . . . . . : 10.24.0.1

Wireless LAN adapter Wi-Fi:
 IPv4 Address. . . . . . . . . . . : 192.168.55.18
 Subnet Mask . . . . . . . . . . . : 255.255.255.0
 Default Gateway . . . . . . . . . : 192.168.55.1
"""
        self.assertEqual(platform.parse_interfaces(text, "win32"),
                         [("10.24.9.17", "10.24.0.0/16"), ("192.168.55.18", "192.168.55.0/24")])

    def test_windows_skip_loopback_linklocal_public_and_invalid_masks(self):
        text = """IPv4: 127.0.0.1
mask: 255.255.255.0
IPv4: 169.254.24.3
mask: 255.255.0.0
IPv4: 8.8.8.8
mask: 255.255.255.0
IPv4: 10.30.40.50
mask: 255.0.255.0
"""
        self.assertEqual(platform.parse_interfaces(text, "win32"), [])

    def test_windows_does_not_invent_24bit_mask(self):
        self.assertEqual(platform.parse_interfaces("IPv4 Address: 192.168.5.10\nNo netmask available", "win32"), [])

    def test_macos_ifconfig_hexadecimal_and_dotted_masks(self):
        text = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
 inet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
 inet 172.22.6.17 netmask 0xfffffc00 broadcast 172.22.7.255
en1: flags=8863<UP,BROADCAST,RUNNING> mtu 1500
 inet 192.168.7.22 netmask 255.255.255.0 broadcast 192.168.7.255
"""
        self.assertEqual(platform.parse_interfaces(text, "darwin"),
                         [("172.22.6.17", "172.22.4.0/22"), ("192.168.7.22", "192.168.7.0/24")])

    def test_macos_skip_noncontiguous_and_invalid_masks(self):
        text = "inet 10.2.3.4 netmask 0xff00ff00\ninet 10.2.3.5 netmask 999.255.255.0\ninet 169.254.4.5 netmask 0xffff0000"
        self.assertEqual(platform.parse_interfaces(text, "darwin"), [])

    def test_deduplicated_interfaces(self):
        text = "inet 192.168.7.22 netmask 0xffffff00\n" * 2
        self.assertEqual(platform.parse_interfaces(text, "darwin"), [("192.168.7.22", "192.168.7.0/24")])

    def test_windows_reveal_uses_arguments_without_a_shell(self):
        path = Path(__file__).resolve().parent / "中文 sample & result.png"
        self.assertEqual(platform.reveal_command(path, "win32"), ["explorer.exe", "/select," + str(path)])

    def test_macos_reveal_uses_finder_selection(self):
        path = Path(__file__).resolve().parent / "中文 sample.png"
        self.assertEqual(platform.reveal_command(path, "darwin"), ["open", "-R", str(path)])

    def test_unsupported_native_reveal_has_explicit_error(self):
        with self.assertRaises(ValueError):
            platform.reveal_command(Path("example.png"), "linux")

    def test_source_resource_and_workspace_root_independent_of_cwd(self):
        expected = Path(platform.__file__).resolve().parent
        with mock.patch.object(platform.sys, "frozen", False, create=True):
            self.assertEqual(platform.resource_root(), expected)
            self.assertEqual(platform.project_root(), expected)

    def test_frozen_resource_root_uses_bundle_extraction_directory(self):
        extraction = Path(__file__).resolve().parent / "bundle-resources"
        with mock.patch.object(platform.sys, "_MEIPASS", str(extraction), create=True):
            self.assertEqual(platform.resource_root(), extraction)

    def test_frozen_macos_workspace_not_inside_app_contents_or_extraction(self):
        folder = Path(__file__).resolve().parents[1] / "local" / "test-tmp"
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(folder)) as temporary:
            app = Path(temporary).resolve() / "Viewer.app"
            executable = app / "Contents" / "MacOS" / "Viewer"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"test fixture, not executable")
            with mock.patch.object(platform.sys, "frozen", True, create=True), \
                    mock.patch.object(platform.sys, "platform", "darwin"), \
                    mock.patch.object(platform.sys, "executable", str(executable)):
                root = platform.project_root()
            self.assertTrue(root.is_absolute())
            self.assertNotIn(app, root.parents)
            self.assertNotEqual(root, executable.parent)

    def test_picker_source_command_preserves_unicode_and_output_argument(self):
        initial = str(Path(__file__).resolve().parent / "中文 images")
        output = str(Path(__file__).resolve().parent / "unused-picker-output.json")
        with mock.patch.object(platform.sys, "frozen", False, create=True):
            command = platform.picker_command(initial, output)
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[1]).name, "desktop.py")
        self.assertEqual(command[2:], ["--pick-directory", initial, "--picker-output", output])

    def test_picker_frozen_command_does_not_require_external_python(self):
        with mock.patch.object(platform.sys, "frozen", True, create=True):
            command = platform.picker_command("chosen directory", "result.json")
        self.assertEqual(command, [sys.executable, "--pick-directory", "chosen directory", "--picker-output", "result.json"])

    def test_interface_collection_uses_only_expected_local_commands(self):
        fixture = "inet 192.168.7.22 netmask 0xffffff00"
        with mock.patch.object(platform.sys, "platform", "darwin"), mock.patch.object(platform, "_run", return_value=fixture) as run:
            self.assertEqual(platform.local_interfaces(), [("192.168.7.22", "192.168.7.0/24")])
            run.assert_called_once_with(["/sbin/ifconfig"])

    def test_gui_picker_writes_result_even_when_frozen_stdout_is_absent(self):
        folder = Path(__file__).resolve().parents[1] / "local" / "test-tmp"
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(folder)) as temporary:
            selected = Path(temporary).resolve()
            output = selected / "picker.json"
            root = mock.MagicMock()
            dialog = SimpleNamespace(askdirectory=mock.Mock(return_value=str(selected)))
            tk = SimpleNamespace(Tk=mock.Mock(return_value=root), TclError=RuntimeError, filedialog=dialog)
            with mock.patch.dict(sys.modules, {"tkinter": tk}), mock.patch.object(platform.sys, "stdout", None):
                result = platform.pick_directory_main(str(selected), str(output))
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"path": str(selected), "cancelled": False})
            root.destroy.assert_called_once()

    def test_gui_picker_cancel_and_error_are_explicit_json(self):
        folder = Path(__file__).resolve().parents[1] / "local" / "test-tmp"
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(folder)) as temporary:
            output = Path(temporary).resolve() / "picker.json"
            tk = SimpleNamespace(Tk=mock.Mock(return_value=mock.MagicMock()), TclError=RuntimeError,
                                 filedialog=SimpleNamespace(askdirectory=mock.Mock(return_value="")))
            with mock.patch.dict(sys.modules, {"tkinter": tk}):
                self.assertEqual(platform.pick_directory_main("", str(output)), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"path": None, "cancelled": True})
            tk.Tk.side_effect = RuntimeError("Tk unavailable fixture")
            with mock.patch.dict(sys.modules, {"tkinter": tk}):
                self.assertEqual(platform.pick_directory_main("", str(output)), 1)
            self.assertIn("error", json.loads(output.read_text(encoding="utf-8")))

    def test_readonly_app_workspace_uses_only_explicit_selected_folder(self):
        chosen = Path(__file__).resolve().parent
        root = mock.MagicMock()
        dialog = SimpleNamespace(askdirectory=mock.Mock(return_value=str(chosen)))
        tk = SimpleNamespace(Tk=mock.Mock(return_value=root), filedialog=dialog)
        with mock.patch.dict(sys.modules, {"tkinter": tk}):
            result = platform.choose_workspace()
        self.assertEqual(result, chosen.resolve() / "RGBTViewer-local")
        self.assertTrue(dialog.askdirectory.call_args.kwargs["mustexist"])
        root.destroy.assert_called_once()

    def test_readonly_app_workspace_cancel_does_not_choose_implicit_location(self):
        root = mock.MagicMock()
        tk = SimpleNamespace(Tk=mock.Mock(return_value=root),
                             filedialog=SimpleNamespace(askdirectory=mock.Mock(return_value="")))
        with mock.patch.dict(sys.modules, {"tkinter": tk}):
            self.assertIsNone(platform.choose_workspace())
        root.destroy.assert_called_once()

    def test_workspace_dialog_does_not_write_appsupport_or_any_directory_itself(self):
        chosen = Path(__file__).resolve().parent
        home = chosen / "mock-user-home"
        tk = SimpleNamespace(Tk=mock.Mock(return_value=mock.MagicMock()),
                             filedialog=SimpleNamespace(askdirectory=mock.Mock(return_value=str(chosen))))
        with mock.patch.dict(sys.modules, {"tkinter": tk}), \
                mock.patch.object(Path, "home", return_value=home), \
                mock.patch.object(Path, "mkdir", side_effect=AssertionError("The chooser must not create files")), \
                mock.patch.object(Path, "write_text", side_effect=AssertionError("The chooser must not write files")):
            self.assertEqual(platform.choose_workspace(), chosen.resolve() / "RGBTViewer-local")
        self.assertEqual(tk.filedialog.askdirectory.call_args.kwargs["initialdir"], str(home))


if __name__ == "__main__":
    unittest.main()
