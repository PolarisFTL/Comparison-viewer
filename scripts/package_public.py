#!/usr/bin/env python3
"""Build an allowlisted source ZIP. Runtime workspaces are never traversed."""
import argparse
import hashlib
import re
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = {
    '.gitignore', 'LICENSE', 'README.md', 'README_EN.md', 'server.py', 'collaboration.py', 'batch_export.py',
    'build_index.py', 'dataset_config.py', 'demo_data.py', 'desktop.py',
    'platform_support.py', 'workspace_state.py', 'image_metadata.py',
    'index.html', 'login.html', 'setup.html',
    'Start-Windows.bat', 'Start-macOS.command',
    'Start-LAN-Windows.bat', 'Start-LAN-macOS.command',
}
FILES = {
    'assets/brand.png', 'assets/README.md', 'examples/config.example.json',
    '.github/workflows/ci.yml', 'scripts/package_public.py',
    'scripts/build_portable.py', 'scripts/build_report.py',
    'tests/frontend_unit.cjs', 'tests/viewer_retry_unit.cjs',
    'tests/export_layout_unit.cjs', 'tests/export_pixels.cjs', 'tests/batch_export_unit.cjs',
    'tests/batch_workflow_unit.cjs',
    'docs/screenshots/setup.png', 'docs/screenshots/viewer.png',
    'docs/screenshots/collaboration.png', 'docs/screenshots/export.png',
    'docs/screenshots/batch-export.png', 'docs/screenshots/batch-result.png',
}
TEXT_EXTENSIONS = {'.py', '.js', '.cjs', '.html', '.css', '.md', '.json',
                   '.yml', '.yaml', '.bat', '.command', '.txt'}
PRIVATE_PATTERNS = (
    # Known machine-specific source roots and user profiles are never publishable.
    re.compile(r'(?i)(?<![a-z0-9])[a-z]:[\\/]+(?:phd|codexfiles|Anaconda\d*|Users[\\/]+(?!YOUR_NAME\b))'),
    re.compile(r'(?i)/[U]sers/(?!YOUR_NAME(?:/|\b))[^/\s"\']+'),
    re.compile(r'(?i)(?:rgbt_session_[a-f0-9_]+|"recovery"\s*:\s*"[a-z0-9_-]{16,}")'),
    re.compile(r'(?i)"(?:code|salt|hash)"\s*:\s*"[a-f0-9]{20,}"'),
    re.compile(r'(?i)"code"\s*:\s*"[a-f0-9]{6}-[a-f0-9]{6}"'),
)


def selected(relative):
    """Only public source patterns; no runtime directory is recursively included."""
    name = relative.as_posix()
    if len(relative.parts) == 1:
        return name in TOP
    if name in FILES:
        return True
    if len(relative.parts) == 2 and relative.parts[0] in ('js', 'css'):
        return relative.suffix == ('.js' if relative.parts[0] == 'js' else '.css')
    if len(relative.parts) == 2 and relative.parts[0] == 'docs':
        return relative.suffix == '.md' or relative.name in ('技术与使用报告-中文.pdf', 'Technical-and-User-Report-English.pdf')
    if len(relative.parts) == 2 and relative.parts[0] == 'tests':
        return relative.name.startswith('test_') and relative.suffix == '.py'
    return False


def collect(root=ROOT):
    """Inspect only explicitly allowed top-level folders, never local/ or dist/."""
    paths = []
    for name in sorted(TOP):
        path = root / name
        if path.exists():
            paths.append(path)
    for folder in ('assets', 'examples', 'docs', 'js', 'css', 'tests', 'scripts', '.github'):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob('*'):
            relative = path.relative_to(root)
            if selected(relative) and (path.is_file() or path.is_symlink()):
                paths.append(path)
    result = sorted(set(paths), key=lambda value: value.relative_to(root).as_posix())
    for path in result:
        relative = path.relative_to(root)
        if path.is_symlink() or root.resolve() not in path.resolve().parents:
            raise ValueError('Symbolic links or paths outside source root are forbidden: ' + str(relative))
        if path.suffix.lower() in TEXT_EXTENSIONS or path.name in ('.gitignore', 'LICENSE'):
            text = path.read_text(encoding='utf-8-sig')
            for pattern in PRIVATE_PATTERNS:
                if pattern.search(text):
                    raise ValueError('Potential private content; review file before publishing: ' + str(relative))
    for required in ('server.py', 'index.html', 'setup.html', 'README.md', 'LICENSE',
                     'Start-Windows.bat', 'Start-macOS.command'):
        if root / required not in result:
            raise ValueError('Required public file missing: ' + required)
    return result


def package(root=ROOT, output=None):
    root = Path(root).resolve()
    paths = collect(root)
    destination = Path(output) if output else root / 'dist' / 'Comparison-Viewer-source.zip'
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in paths:
                relative = path.relative_to(root)
                member = 'Comparison-Viewer/' + relative.as_posix()
                info = zipfile.ZipInfo(member)
                info.create_system = 3
                mode = 0o755 if path.suffix == '.command' else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(destination.suffix + '.sha256')
    checksum.write_text(digest + '  ' + destination.name + '\n', encoding='ascii')
    return destination, len(paths), digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate selected public files without writing an archive')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.check:
            print('Public source validation passed: {} files'.format(len(collect())))
        else:
            path, count, digest = package(output=args.output)
            print('Created {} ({} files)\nSHA256 {}'.format(path, count, digest))
    except (OSError, UnicodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
