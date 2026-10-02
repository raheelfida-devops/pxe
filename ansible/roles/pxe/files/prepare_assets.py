#!/usr/bin/env python3
"""Prepare canonical boot paths from a read-only ISO mount without editing it."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


def resolve_case(root, relative):
    path = root
    for part in relative.split('/'):
        matches = [p for p in path.iterdir() if p.name.casefold() == part.casefold()]
        if len(matches) != 1:
            raise ValueError(f'Missing or ambiguous asset: {relative} in {root}')
        path = matches[0]
    if not path.is_file():
        raise ValueError(f'Not a file: {path}')
    return path


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.digest()


def prepare(kind, source, destination):
    paths = {'ubuntu': [('casper/vmlinuz', 'vmlinuz'), ('casper/initrd', 'initrd')],
             'windows': [('boot/bcd', 'BCD'), ('boot/boot.sdi', 'boot.sdi'),
                         ('sources/boot.wim', 'boot.wim')]}
    if kind not in paths:
        raise ValueError(f'Unsupported media kind: {kind}')
    assets = [(resolve_case(source, src), destination / dst) for src, dst in paths[kind]]
    if kind == 'windows':
        sources = resolve_case(source, 'sources/boot.wim').parent
        if not any(p.name.casefold() in ('install.wim', 'install.esd', 'install.swm') for p in sources.iterdir()):
            raise ValueError('Windows ISO lacks a full WIM/ESD/split-WIM installation source')
        if not any((source / p).is_file() for p in ['setup.exe', 'sources/setup.exe', 'SETUP.EXE', 'SOURCES/SETUP.EXE']):
            # General case-insensitive lookup for mixed-case UDF layouts.
            try:
                resolve_case(source, 'setup.exe')
            except ValueError:
                resolve_case(source, 'sources/setup.exe')
    destination.mkdir(parents=True, exist_ok=True)
    changed = False
    for src, dst in assets:
        if dst.name == 'boot.wim':
            # Serve the mounted ISO's image; never make an unnecessary large copy.
            if not dst.is_symlink() or os.readlink(dst) != str(src):
                if dst.exists() or dst.is_symlink():
                    dst.unlink()
                dst.symlink_to(src)
                changed = True
        elif not dst.is_file() or dst.is_symlink() or digest(src) != digest(dst):
            if dst.is_symlink():
                dst.unlink()
            temporary = dst.with_name(dst.name + '.tmp')
            shutil.copyfile(src, temporary)
            temporary.chmod(0o644)
            temporary.replace(dst)
            changed = True
    return changed


if __name__ == '__main__':
    try:
        modified = prepare(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
        message = 'changed' if modified else 'unchanged'
        # Use distinct JSON-like tokens so Ansible does not confuse unchanged with changed.
        print('changed=true' if modified else 'changed=false')
        subprocess.run(['logger', '-t', 'pxe-media', f'{sys.argv[1]} assets {message}: {sys.argv[3]}'], check=True)
    except (ValueError, OSError, IndexError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
