"""Local deployment checks; never connect to a host or start a service."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles' / 'pxe'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


ASSETS = module('pxe_assets', ROLE / 'files' / 'prepare_assets.py')
NETWORK = module('pxe_network', ROLE / 'filter_plugins' / 'pxe.py')
MENU_PATCH = module('pxe_menu_patch', ROLE / 'files' / 'patch_menu.py')


class MediaPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'iso'
        self.destination = Path(self.temp.name) / 'boot'
        self.source.mkdir()

    def write_source(self, relative, content=b'fixture'):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def snapshot(self):
        return {str(p.relative_to(self.source)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.source.rglob('*') if p.is_file()}

    def windows_source(self, install='INSTALL.ESD'):
        for filename in ['BOOT/BCD', 'BOOT/BOOT.SDI', 'SOURCES/BOOT.WIM',
                         'SOURCES/SETUP.EXE']:
            self.write_source(filename)
        if install:
            self.write_source('SOURCES/' + install)

    def test_ubuntu_copy_is_idempotent_and_refreshes_changed_kernel(self):
        kernel = self.write_source('casper/vmlinuz', b'kernel one')
        self.write_source('casper/initrd', b'initrd')
        original = self.snapshot()
        self.assertTrue(ASSETS.prepare('ubuntu', self.source, self.destination))
        self.assertFalse(ASSETS.prepare('ubuntu', self.source, self.destination))
        self.assertEqual(self.snapshot(), original)
        kernel.write_bytes(b'kernel two')
        self.assertTrue(ASSETS.prepare('ubuntu', self.source, self.destination))
        self.assertEqual((self.destination / 'vmlinuz').read_bytes(), b'kernel two')
        self.assertFalse(ASSETS.prepare('ubuntu', self.source, self.destination))

    def test_windows_uppercase_paths_and_large_wim_symlink_preserve_source(self):
        self.windows_source()
        original = self.snapshot()
        self.assertTrue(ASSETS.prepare('windows', self.source, self.destination))
        self.assertFalse(ASSETS.prepare('windows', self.source, self.destination))
        self.assertTrue((self.destination / 'boot.wim').is_symlink())
        self.assertEqual((self.destination / 'boot.wim').resolve(),
                         self.source / 'SOURCES/BOOT.WIM')
        self.assertEqual((self.destination / 'BCD').read_bytes(), b'fixture')
        self.assertEqual(self.snapshot(), original)

    def test_missing_windows_install_image_fails_before_writing_boot_assets(self):
        self.windows_source(install=None)
        original = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'installation source'):
            ASSETS.prepare('windows', self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.snapshot(), original)

    def test_ambiguous_case_variants_are_rejected(self):
        self.windows_source()
        self.write_source('BOOT/bcd', b'conflicting BCD')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            ASSETS.prepare('windows', self.source, self.destination)
        self.assertFalse(self.destination.exists())


class AddressPlanTests(unittest.TestCase):
    def plan(self, **changes):
        values = dict(address='192.168.77.1', subnet='192.168.77.0/24', prefix=24,
                      netmask='255.255.255.0', start='192.168.77.100', end='192.168.77.200')
        values.update(changes)
        return NETWORK.valid_address_plan(**values)

    def test_valid_isolated_address_plan(self):
        self.assertTrue(self.plan())

    def test_invalid_or_conflicting_plans(self):
        for changes in [dict(address='192.168.77.150'), dict(start='192.168.77.201'),
                        dict(end='192.168.78.200'), dict(start='192.168.77.0'),
                        dict(end='192.168.77.255'), dict(netmask='255.255.0.0'),
                        dict(prefix=23), dict(subnet='192.168.77.1/24'),
                        dict(subnet='malformed'), dict(address='::1')]:
            with self.subTest(changes=changes):
                self.assertFalse(self.plan(**changes))


class RecoveredAssetTests(unittest.TestCase):
    def test_recovered_assets_match_recorded_lengths_and_hashes(self):
        base = ROOT / 'files' / 'recovered'
        manifest = json.loads((base / 'manifest.json').read_text())
        self.assertTrue(manifest['files'])
        for item in manifest['files']:
            with self.subTest(asset=item['file']):
                path = base / item['file']
                self.assertEqual(path.stat().st_size, item['size'])
                hasher = hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        hasher.update(block)
                self.assertEqual(hasher.hexdigest(), item['sha256'])


class ExistingMenuTests(unittest.TestCase):
    def test_preserves_installer_entries_and_is_idempotent(self):
        original = ('#!ipxe\nset base http://192.168.77.1\n:menu\n'
                    'menu PXE installers\nitem ubuntu Ubuntu Desktop\n'
                    'choose --default ubuntu --timeout 60000 target || goto menu\n'
                    'goto ${target}\n:ubuntu\nchain ${base}/ubuntu.ipxe\n'
                    ':failed\ngoto menu\n')
        patched = MENU_PATCH.patch(original, '192.168.77.1', 'localboot', 30000)
        self.assertIn('item ubuntu Ubuntu Desktop', patched)
        self.assertIn('chain ${base}/ubuntu.ipxe', patched)
        self.assertIn('choose --default localboot --timeout 30000 target || goto menu', patched)
        self.assertEqual(MENU_PATCH.patch(patched, '192.168.77.1', 'localboot', 30000), patched)

    def test_rejects_unrecognized_layout_without_overwriting(self):
        with self.assertRaises(ValueError):
            MENU_PATCH.patch('#!ipxe\nshell\n', '192.168.77.1', 'localboot', 30000)


class RenderedBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=FileSystemLoader(ROLE / 'templates'),
                               undefined=StrictUndefined)
        self.env.filters['bool'] = bool

    def test_efi_path_validation_accepts_bootloaders_and_rejects_command_syntax(self):
        self.assertTrue(NETWORK.valid_efi_path(r'\EFI\Microsoft\Boot\bootmgfw.efi'))
        self.assertTrue(NETWORK.valid_efi_path(r'\EFI\ubuntu\shimx64.efi'))
        for value in [r'\EFI\ubuntu\shimx64.efi || shell',
                      r'\EFI\..\BOOTX64.EFI', '/EFI/BOOT/BOOTX64.EFI']:
            self.assertFalse(NETWORK.valid_efi_path(value))

    def test_production_menu_exposes_only_validated_installer_paths(self):
        media = [dict(id='approved', label='Approved', validated=True),
                 dict(id='candidate', label='Candidate', validated=False)]
        rendered = self.env.get_template('menu.ipxe.j2').render(
            pxe_address='192.168.77.1', pxe_menu_mode='production', pxe_media=media,
            pxe_debian_enabled=True, pxe_debian_validated=False,
            pxe_menu_default='localboot', pxe_menu_timeout=30000)
        self.assertIn('item approved ', rendered)
        self.assertIn('/approved/boot.ipxe', rendered)
        self.assertNotIn('candidate', rendered)
        self.assertNotIn('/debian13-network/boot.ipxe', rendered)

    def test_nfs_supports_casper_tcp_and_udp(self):
        import configparser
        settings = configparser.ConfigParser()
        settings.read_string(self.env.get_template('nfs.conf.j2').render())
        for setting in ['vers3', 'tcp', 'udp']:
            self.assertEqual(settings['nfsd'][setting], 'y')

    def test_authenticated_windows_launcher_prompts_without_embedding_password(self):
        secret_fixture = 'TEST_SECRET_DO_NOT_RENDER'
        rendered = self.env.get_template('install-windows.bat.j2').render(
            pxe_address='192.168.77.1', pxe_smb_auth='authenticated',
            pxe_smb_user='pxeinstall', pxe_smb_password=secret_fixture,
            item=dict(id='win10'))
        self.assertNotIn(secret_fixture, rendered)
        self.assertIn('/user:pxeinstall * /persistent:no', rendered)
        self.assertLess(rendered.index('wpeutil WaitForNetwork'), rendered.index('net use'))
        self.assertIn('sources\\setup.exe', rendered)

    def test_local_disk_entry_is_available_in_both_menu_modes(self):
        for mode in ['lab', 'production']:
            rendered = self.env.get_template('menu.ipxe.j2').render(
                pxe_address='192.168.77.1', pxe_menu_mode=mode, pxe_media=[],
                pxe_debian_enabled=False, pxe_debian_validated=False,
                pxe_menu_default='localboot', pxe_menu_timeout=30000)
            self.assertIn('item localboot Boot from local hard disk', rendered)
            self.assertIn('chain ${base}/localboot.ipxe || goto failed', rendered)
            self.assertIn('item exit Return to firmware', rendered)
            self.assertIn('choose --default localboot', rendered)

    def test_local_disk_boot_handles_bios_efi_and_no_bootable_disk(self):
        paths = [r'\EFI\ubuntu\shimx64.efi', r'\EFI\BOOT\BOOTX64.EFI']
        rendered = self.env.get_template('localboot.ipxe.j2').render(
            pxe_local_efi_paths=paths)
        self.assertIn('iseq ${platform} efi && goto efi || goto bios', rendered)
        self.assertIn('sanboot --no-describe --drive 0x80 || goto failed', rendered)
        for path in paths:
            self.assertIn(f'sanboot --no-describe --drive 0 --filename {path}', rendered)
        self.assertLess(rendered.index(paths[0]), rendered.index(paths[1]))
        self.assertTrue(rendered.rstrip().endswith('exit 1'))


if __name__ == '__main__':
    unittest.main()
