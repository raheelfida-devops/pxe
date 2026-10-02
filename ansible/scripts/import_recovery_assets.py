#!/usr/bin/env python3
"""Import only known boot binaries; never extract configs, credentials or ISOs."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

ASSETS = {
    'srv/pxe/boot/debian13-network/vmlinuz': (
        'debian13-network/vmlinuz',
        '2b2358b37674d2505350528875bb17afae2a36522a9e8a9417eaca65a7da0e08'),
    'srv/pxe/boot/debian13-network/initrd.gz': (
        'debian13-network/initrd.gz',
        '57303d157cffce3fa402301667fbc9b2280aa7372082b081e777375ae49da5f2'),
    'srv/pxe/tftp/undionly.kpxe': ('undionly.kpxe', None),
    'srv/pxe/boot/wimboot': ('wimboot', None),
}


def import_assets(archive, output):
    manifest = []
    with tarfile.open(archive, 'r:gz') as bundle:
        for member_name, (relative, expected_hash) in ASSETS.items():
            member = bundle.getmember(member_name)
            if not member.isfile() or not 0 < member.size < 150 * 1024 * 1024:
                raise ValueError(f'Invalid asset member: {member_name}')
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError(f'Unreadable member: {member_name}')
            data = stream.read()
            digest = hashlib.sha256(data).hexdigest()
            if expected_hash and digest != expected_hash:
                raise ValueError(f'Historical hash mismatch: {relative}')
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
            manifest.append({'file': relative, 'sha256': digest, 'size': len(data),
                             'origin': member_name})
    (output / 'manifest.json').write_text(json.dumps({
        'snapshot': '2026-10-02 PXE recovery archive',
        'source_session': '01a0e8dd-47fa-7361-905e-c4ee96e7cc4e',
        'note': 'Historical boot assets only; not proof of client compatibility.',
        'files': manifest,
    }, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'files/recovered')
    arguments = parser.parse_args()
    import_assets(arguments.archive, arguments.output)
    print('Imported four allowlisted assets; all configs and other media excluded.')
