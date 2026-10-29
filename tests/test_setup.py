import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
import json
import backend

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import setup_device as setup


class EnrollmentTests(unittest.TestCase):
    def test_one_authorized_usb(self):
        device=dict(serial='DEMO',state='device',model='Test')
        self.assertEqual(setup.select_device([device]),device)

    def test_refuse_missing_unauthorized_and_ambiguous_devices(self):
        for devices in ([],[dict(serial='DEMO',state='unauthorized')],
                        [dict(serial='A',state='device'),dict(serial='B',state='device')]):
            with self.subTest(devices=devices),self.assertRaises(ValueError):
                setup.select_device(devices)
        with self.assertRaises(ValueError):
            setup.select_device([dict(serial='A',state='device')],'B')

    def test_display_modes_match_physical_panel(self):
        cap=setup.parse_display('Physical size: 1600x2560\nOverride size: 800x1280',
            'width=1600, height=2560, fps=60.000004 width=1920, height=1080, fps=144.0')
        self.assertEqual(cap['refresh'],60)
        self.assertEqual(cap['supportedModes'],[dict(width=1600,height=2560,refresh=60)])
        self.assertEqual(cap['modeSource'],'matching-physical-fallback')

    def test_builtin_modes_exclude_hdmi_and_virtual(self):
        display='''DisplayDeviceInfo{"Internal": supportedModes [{width=1600, height=2560, fps=60.0}, {width=1200, height=1920, fps=90.0}], type BUILT_IN, FLAG_DEFAULT_DISPLAY}
DisplayDeviceInfo{"HDMI": supportedModes [{width=1600, height=2560, fps=144.0}], type HDMI}'''
        cap=setup.parse_display('Physical size: 1600x2560',display)
        self.assertEqual(cap['modeSource'],'built-in')
        self.assertEqual(cap['refresh'],60)
        self.assertEqual(cap['supportedModes'],[dict(width=1200,height=1920,refresh=90),dict(width=1600,height=2560,refresh=60)])

    def test_scale_150_only_when_compatible(self):
        cfg=setup.proposed_config(dict(serial='TEST'),dict(width=1440,height=2560,refresh=60))
        self.assertNotEqual(cfg['scale'],1.5)
        backend.validate(backend.DEFAULTS | dict(width=1920,height=1200,scale=1.5))
        with self.assertRaises(ValueError):
            backend.validate(backend.DEFAULTS | dict(width=2560,height=1600,scale=1.5))

    def test_phone_high_refresh_and_scale(self):
        cap=setup.parse_display('Physical size: 1080x2400','width=1080, height=2400, fps=120.0')
        cfg=setup.proposed_config(dict(serial='TEST'),cap)
        self.assertEqual((cfg['width'],cfg['height'],cfg['refresh'],cfg['fps']),(2400,1080,120,60))

    def test_missing_mode_uses_explicit_fallback(self):
        self.assertFalse(setup.parse_display('Physical size: 1920x1200','')['refreshDetected'])
        with self.assertRaises(ValueError): setup.parse_display('unavailable','')

    def test_huge_screen_is_bounded(self):
        cfg=setup.proposed_config(dict(serial='TEST'),dict(width=7680,height=4320,refresh=240))
        self.assertLessEqual(cfg['width'],4096)
        self.assertLessEqual(cfg['width']*cfg['height'],4096*2160)
        self.assertEqual(cfg['refresh'],120)

    def test_local_apk_hash_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            apk=Path(directory)/'fake.apk'
            apk.write_bytes(b'not an APK')
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                setup.verified_apk(apk)
            with patch.object(setup,'AVNC_SHA256',hashlib.sha256(apk.read_bytes()).hexdigest()):
                self.assertEqual(setup.verified_apk(apk),apk)

    def test_missing_app_installs_then_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            config=path/'settings.json'
            original=backend.DEFAULTS | dict(serial='TEST',scale=1,position='custom',x=100,y=200)
            config.write_text(json.dumps(original))
            count=0
            calls=[]
            def command(args,**kwargs):
                nonlocal count
                calls.append(args)
                if args[-1]=='ro.build.version.sdk': return '29'
                if args[-2:]==['wm','size']: return 'Physical size: 1600x2560'
                if args[-2:]==['dumpsys','display']: return 'width=1600, height=2560, fps=60.0'
                if 'path' in args:
                    count+=1
                    return '' if count==1 else 'package:/data/app/avnc/base.apk'
                if 'install' in args: return 'Success'
                raise AssertionError(args)
            with patch.object(backend,'CONFIG',config),patch.object(backend,'RUNTIME',path), \
                 patch.object(backend,'usb_devices',return_value=[dict(serial='TEST',state='device',model='Test')]), \
                 patch.object(backend,'command',side_effect=command), \
                 patch.object(setup,'verified_apk',return_value=Path('/verified.apk')) as download, \
                 contextlib.redirect_stdout(io.StringIO()):
                setup.main([])
            download.assert_called_once()
            self.assertIn(['adb','-s','TEST','install','/verified.apk'],calls)
            self.assertEqual(json.loads(config.read_text()),original)
            self.assertEqual(json.loads((path/'devices.json').read_text())['TEST']['refresh'],60)


if __name__ == '__main__': unittest.main()
