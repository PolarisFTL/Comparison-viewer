"""Small, testable OS boundary. No network traffic or security changes."""
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def project_root():
    if not getattr(sys, 'frozen', False):
        return Path(__file__).resolve().parent
    executable = Path(sys.executable).resolve()
    if sys.platform == 'darwin':
        for parent in executable.parents:
            if parent.suffix == '.app':
                return parent.parent
    return executable.parent


def reveal_command(path, platform=None):
    platform = platform or sys.platform
    if platform == 'win32':
        return ['explorer.exe', '/select,' + str(path)]
    if platform == 'darwin':
        return ['open', '-R', str(path)]
    raise ValueError('This platform has no supported native file reveal command')


def _run(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=True)
    return result.stdout.decode('utf-8', errors='replace')


def parse_interfaces(text, platform):
    pairs = []
    if platform == 'win32':
        # ipconfig labels are localized. Values and netmask arithmetic are not.
        lines = text.splitlines()
        for i, line in enumerate(lines):
            values = re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', line)
            for address in values:
                try:
                    ip = ipaddress.ip_address(address)
                    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local or address.startswith('255.'):
                        continue
                    for after in lines[i+1:i+4]:
                        mask_match = re.search(r'(255(?:\.\d{1,3}){3})', after)
                        if mask_match:
                            pairs.append((address, str(ipaddress.ip_network(address+'/'+mask_match[1], strict=False))))
                            break
                except ValueError:
                    continue
    else:
        for address, mask in re.findall(r'\binet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(0x[0-9a-fA-F]+|[\d.]+)', text):
            try:
                if mask.startswith('0x'):
                    mask = str(ipaddress.IPv4Address(int(mask,16)))
                ip = ipaddress.ip_address(address)
                if ip.is_private and not ip.is_loopback and not ip.is_link_local:
                    pairs.append((address,str(ipaddress.ip_network(address+'/'+mask,strict=False))))
            except ValueError:
                continue
    return sorted(set(pairs))


def local_interfaces():
    try:
        if sys.platform == 'win32':
            return parse_interfaces(_run(['ipconfig']), 'win32')
        if sys.platform == 'darwin':
            return parse_interfaces(_run(['/sbin/ifconfig']), 'darwin')
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return []


def picker_command(initial, output):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--pick-directory', initial, '--picker-output', output]
    return [sys.executable, str(resource_root()/'desktop.py'), '--pick-directory', initial, '--picker-output', output]


def pick_directory_main(initial='', output=None):
    # Runs in a separate main-thread process (including on macOS).
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes('-topmost', True)
        except tk.TclError:
            pass
        candidate=Path(initial).expanduser() if initial else Path.home()
        if not candidate.is_dir():
            candidate=Path.home()
        value=filedialog.askdirectory(title='选择可视化图片目录 / Choose image directory',initialdir=str(candidate),mustexist=True,parent=root)
        root.destroy()
        result={'path':str(Path(value).resolve()) if value else None,'cancelled':not bool(value)}
        if output:Path(output).write_text(json.dumps(result,ensure_ascii=True),encoding='utf-8')
        elif sys.stdout:print(json.dumps(result,ensure_ascii=True),flush=True)
        return 0
    except Exception as error:
        result={'error':'系统目录选择器不可用，可在页面粘贴绝对路径。'+str(error)}
        if output:Path(output).write_text(json.dumps(result,ensure_ascii=True),encoding='utf-8')
        elif sys.stdout:print(json.dumps(result,ensure_ascii=True),flush=True)
        return 1


def notify_error(message):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk();root.withdraw();messagebox.showerror('RGBT Comparison Viewer',message,parent=root);root.destroy()
    except Exception:
        if sys.stderr:
            print(message,file=sys.stderr)


def choose_workspace():
    """Ask the user before writing outside a read-only application folder."""
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw()
    try:
        value=filedialog.askdirectory(title='应用目录只读：请选择用于保存索引和收藏的可写工作区',initialdir=str(Path.home()),mustexist=True,parent=root)
        return Path(value).resolve()/'RGBTViewer-local' if value else None
    finally:root.destroy()
