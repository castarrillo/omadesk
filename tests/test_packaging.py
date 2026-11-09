import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import install
import uninstall


class PackagingTests(unittest.TestCase):
    def test_public_identity_matches_manifest_and_paths(self):
        root=Path(__file__).resolve().parents[1]
        manifest=json.loads((root/'manifest.json').read_text())
        self.assertEqual(manifest['id'],install.PLUGIN_ID)
        self.assertEqual(manifest['author'],'castarrillo')
        self.assertEqual(uninstall.PLUGIN_ID,install.PLUGIN_ID)
        self.assertIn(install.PLUGIN_ID,(root/'Main.qml').read_text())
        self.assertNotIn('/plugins/local.tablet-usb/',(root/'Main.qml').read_text())

    def test_layout_migration_keeps_placement_and_settings(self):
        old={'bar':{'layout':{'right':[{'id':'other.widget'},{'id':install.LEGACY_ID,'custom':42}]}},
             'notes':install.LEGACY_ID,'idle':{'lock':300}}
        migrated=install.migrate_layout(old)
        self.assertEqual(migrated['bar']['layout']['right'][1],{'id':install.PLUGIN_ID,'custom':42})
        self.assertEqual(migrated['bar']['layout']['right'][0],{'id':'other.widget'})
        self.assertEqual(migrated['notes'],install.LEGACY_ID)
        self.assertEqual(migrated['idle'],old['idle'])
        self.assertEqual(old['bar']['layout']['right'][1]['id'],install.LEGACY_ID)
        self.assertEqual(install.migrate_layout(migrated),migrated)

    def test_shell_migration_is_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shell=root/'omarchy/shell.json'
            shell.parent.mkdir()
            original=json.dumps({'bar':{'layout':{'left':[{'id':install.LEGACY_ID}]}}})
            shell.write_text(original)
            backup=root/'backup'
            backup.mkdir()
            with patch.object(install,'CONFIG',root):
                install.migrate_shell(backup)
            self.assertEqual((backup/'shell.json').read_text(),original)
            self.assertEqual(json.loads(shell.read_text())['bar']['layout']['left'][0]['id'],install.PLUGIN_ID)

    def test_uninstaller_does_not_own_other_wrappers_or_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            wrapper=Path(directory)/'omadesk'
            wrapper.write_text('#!/bin/sh\necho unrelated\n')
            self.assertFalse(uninstall.owned_wrapper(wrapper))
            wrapper.write_text(f'exec python /home/test/.config/omarchy/plugins/{install.PLUGIN_ID}/backend.py')
            self.assertTrue(uninstall.owned_wrapper(wrapper))
            link=Path(directory)/'link'
            link.symlink_to(wrapper)
            self.assertFalse(uninstall.owned_wrapper(link))

    def test_install_sources_are_present(self):
        root=Path(__file__).resolve().parents[1]
        for name in install.FILES:
            with self.subTest(name=name): self.assertTrue((root/name).is_file())


if __name__=='__main__': unittest.main()
