import json
from pathlib import Path
import socket
import struct
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend
import rfb_quality as rfb


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(backend.validate({}), backend.DEFAULTS)

    def test_reject_injection_and_invalid_values(self):
        for patch in [{'serial': 'x;echo test'}, {'scale': float('nan')}, {'scale': 0},
                      {'width': 8192}, {'width': 641}, {'fps': 61}, {'quality': 10},
                      {'input': 'false'}, {'unexpected': 1}, {'refresh': 30, 'fps': 60},
                      {'width': 4096, 'height': 4096}, {'scale': 1.3}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                backend.validate(patch)

    def test_presets_and_portrait(self):
        for width, height, scale in [(2560,1600,1.25), (1920,1200,1.5), (1280,800,1),
                                      (1600,2560,1.25)]:
            self.assertEqual(backend.validate(dict(width=width, height=height, scale=scale))['width'], width)

    def test_position(self):
        screens = [dict(name='DP-1', x=0, y=0, width=1920, height=1080, scale=1),
                   dict(name='DP-2', x=1920, y=0, width=1920, height=1080, scale=1)]
        for side, expected in [('right',(3840,0)), ('left',(-1280,0)),
                               ('above',(0,-800)), ('below',(0,1080))]:
            self.assertEqual(backend.position(backend.DEFAULTS | {'position':side}, screens), expected)
        self.assertEqual(backend.position(backend.DEFAULTS | {'anchor':'DP-1'}, screens), (1920,0))
        self.assertEqual(backend.position(backend.DEFAULTS | {'position':'custom','x':-10,'y':50}, screens), (-10,50))
        with self.assertRaises(ValueError):
            backend.position(backend.DEFAULTS | {'anchor':'missing'}, screens)

    def test_rotated_monitor(self):
        screen = dict(name='DP-1', x=0, y=0, width=1920, height=1080, scale=1, transform=1)
        self.assertEqual(backend.position(backend.DEFAULTS, [screen]), (1080,0))

    def test_apply_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg_path = Path(folder) / 'settings.json'
            state_path = Path(folder) / 'state.json'
            old = backend.DEFAULTS | {'quality': 7}
            new = backend.DEFAULTS | {'quality': 9}
            cfg_path.write_text(json.dumps(old))
            state_path.write_text(json.dumps({'settings': old}))
            with patch.object(backend, 'CONFIG', cfg_path), patch.object(backend, 'STATE', state_path), \
                 patch.object(backend, 'RUNTIME', Path(folder)), patch.object(backend, 'active', return_value=True), \
                 patch.object(backend, 'require_usb'), patch.object(backend, 'monitors', return_value=[]), \
                 patch.object(backend, 'stop') as stop, \
                 patch.object(backend, 'start', side_effect=[RuntimeError('encoder failed'), None]) as start, \
                 patch.object(sys, 'argv', ['backend.py', 'apply', '--settings', json.dumps(new)]):
                with self.assertRaisesRegex(RuntimeError, 'configuración anterior restaurada'):
                    backend.main()
                self.assertEqual(json.loads(cfg_path.read_text()), old)
                self.assertEqual(start.call_count, 2)
                self.assertEqual(stop.call_count, 2)


class ProtocolTests(unittest.TestCase):
    def test_overrides_quality_and_compression_preserving_encodings(self):
        packet = rfb.encodings_packet([7,16,-32,-247,-239,-223], 9, 2)
        count = struct.unpack('>H', packet[2:4])[0]
        self.assertEqual(struct.unpack('>' + 'i'*count, packet[4:]), (7,16,-239,-223,-23,-254))

    def test_fragmented_client_input(self):
        client, peer = socket.socketpair()
        upstream, server = socket.socketpair()
        errors = []
        def work():
            try:
                rfb.forward_client(client, upstream, 8, 1)
            except EOFError:
                pass
            except Exception as e:
                errors.append(e)
            finally:
                upstream.close()
                client.close()
        thread = threading.Thread(target=work)
        thread.start()
        encoded = rfb.encodings_packet([7,-239], 3, 9)
        key = bytes([4,1,0,0,0,0,0,65])
        pointer = bytes([5,0,0,20,0,40])
        for byte in encoded + key + pointer:
            peer.sendall(bytes([byte]))
        peer.close()
        received = b''
        while chunk := server.recv(1024):
            received += chunk
        server.close()
        thread.join(timeout=2)
        self.assertFalse(errors)
        self.assertEqual(received, rfb.encodings_packet([7,-239],8,1) + key + pointer)

    def test_unknown_message_fails_closed(self):
        client, peer = socket.socketpair()
        upstream, server = socket.socketpair()
        try:
            peer.sendall(b'\x79')
            with self.assertRaises(ValueError):
                rfb.forward_client(client, upstream, 8, 2)
        finally:
            for item in (client,peer,upstream,server): item.close()

    def test_rfb_handshake(self):
        client, peer = socket.socketpair()
        upstream, server = socket.socketpair()
        errors=[]
        header = struct.pack('>HH',2560,1600) + bytes(16) + struct.pack('>I',4)
        def fake_server():
            try:
                server.sendall(b'RFB 003.008\n')
                self.assertEqual(rfb.read_exact(server,12), b'RFB 003.008\n')
                server.sendall(b'\x01\x01')
                self.assertEqual(rfb.read_exact(server,1),b'\x01')
                server.sendall(bytes(4))
                self.assertEqual(rfb.read_exact(server,1),b'\x01')
                server.sendall(header + b'Test')
            except Exception as e: errors.append(e)
        def fake_client():
            try:
                self.assertEqual(rfb.read_exact(peer,12),b'RFB 003.008\n')
                peer.sendall(b'RFB 003.008\n')
                self.assertEqual(rfb.read_exact(peer,2),b'\x01\x01')
                peer.sendall(b'\x01')
                self.assertEqual(rfb.read_exact(peer,4),bytes(4))
                peer.sendall(b'\x01')
                self.assertEqual(rfb.read_exact(peer,28),header + b'Test')
            except Exception as e: errors.append(e)
        threads=[threading.Thread(target=fake_server),threading.Thread(target=fake_client)]
        for s in (client,peer,upstream,server): s.settimeout(2)
        for t in threads: t.start()
        try:
            rfb.handshake(client,upstream)
            for t in threads: t.join(timeout=3)
            self.assertFalse(errors)
        finally:
            for s in (client,peer,upstream,server): s.close()


if __name__ == '__main__':
    unittest.main()
