#!/usr/bin/env python3
"""Build on the target OS; PyInstaller and Pillow are build-time dependencies."""
import argparse
import hashlib
import os
import platform
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output=None):
    if sys.platform not in ('win32', 'darwin'):
        raise RuntimeError('Portable applications must be built on Windows or macOS.')
    if sys.version_info < (3, 9):
        raise RuntimeError('Python 3.9 or newer is required.')
    destination = Path(output).resolve() if output else ROOT / 'dist'
    if destination == ROOT:
        raise ValueError('Output must be a dedicated build folder, not the source root.')
    destination.mkdir(parents=True, exist_ok=True)
    work = ROOT / 'local' / 'build'
    work.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--name', 'RGBTViewer', '--windowed',
               '--distpath', str(destination), '--workpath', str(work / 'pyinstaller'),
               '--specpath', str(work), '--icon', str(ROOT / 'assets' / 'brand.png'),
               '--hidden-import', 'tkinter', '--hidden-import', '_tkinter']
    command.append('--onefile' if sys.platform == 'win32' else '--onedir')
    if sys.platform == 'darwin':
        command.extend(['--osx-bundle-identifier', 'org.rgbtviewer.desktop'])
    for relative in ('index.html', 'login.html', 'setup.html', 'js', 'css', 'assets'):
        source = ROOT / relative
        if not source.exists():
            raise FileNotFoundError('Missing application resource: ' + relative)
        target = '.' if source.is_file() else relative
        command.extend(['--add-data', str(source) + os.pathsep + target])
    command.append(str(ROOT / 'desktop.py'))
    environment=os.environ.copy()
    environment['PYINSTALLER_CONFIG_DIR']=str(work/'cache')
    subprocess.run(command, cwd=str(ROOT), env=environment, check=True)
    bundle = destination / ('RGBTViewer.exe' if sys.platform == 'win32' else 'RGBTViewer.app')
    if not bundle.exists():
        raise RuntimeError('Builder finished without producing the expected application.')
    system = 'windows' if sys.platform == 'win32' else 'macos'
    architecture = platform.machine().lower()
    archive_path = destination / ('RGBT-Comparison-Viewer-{}-{}-portable.zip'.format(system, architecture))
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        bundle_files = [bundle] if bundle.is_file() else sorted(bundle.rglob('*'))
        for path in bundle_files:
            if path.is_file() or path.is_symlink():
                _write_member(archive, path, path.relative_to(destination))
        launchers = ('Start-Windows.bat', 'Start-LAN-Windows.bat') if sys.platform == 'win32' else ('Start-macOS.command', 'Start-LAN-macOS.command')
        extras = [ROOT / 'README.md', ROOT / 'README_EN.md', ROOT / 'LICENSE', ROOT / 'assets' / 'README.md',
                  ROOT / 'assets' / 'brand.png']
        extras.extend(ROOT / name for name in launchers)
        extras.extend(sorted((ROOT / 'docs').glob('*.md')))
        extras.extend(ROOT / 'docs' / 'screenshots' / name for name in ('setup.png', 'viewer.png', 'collaboration.png', 'export.png', 'batch-export.png', 'batch-result.png'))
        for report_name in ('技术与使用报告-中文.pdf', 'Technical-and-User-Report-English.pdf'):
            report = ROOT / 'docs' / report_name
            if report.is_file():
                extras.append(report)
        for path in extras:
            if path.is_file():
                _write_member(archive, path, path.relative_to(ROOT))
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix('.zip.sha256').write_text(digest + '  ' + archive_path.name + '\n', encoding='ascii')
    print('Built {} ({})\nSHA256 {}'.format(archive_path, architecture, digest))
    print('This is an unsigned target-platform build; OS GUI and network acceptance remain separate tests.')
    return archive_path


def _write_member(archive, path, relative):
    info = zipfile.ZipInfo('RGBT-Comparison-Viewer/' + relative.as_posix())
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    if path.is_symlink():
        # Preserve .app framework links; recursively copying them breaks bundles.
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, os.readlink(str(path)).encode('utf-8'))
        return
    mode = 0o755 if path.suffix == '.command' or os.access(str(path), os.X_OK) else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    archive.writestr(info, path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        build(args.output)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
