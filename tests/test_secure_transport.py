import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secure_transport as transport
import rfb_quality as rfb
import backend


class TransportTests(unittest.TestCase):
    def test_runtime_and_socket_directory_are_private(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = transport.private_directory(folder)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(transport.private_directory(folder), directory)

    def test_group_accessible_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder, 0o750)
            with self.assertRaises(PermissionError): transport.private_directory(folder)

    def test_symlink_or_non_private_subdirectory_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other:
            link = Path(folder) / 'omadesk'
            link.symlink_to(other, target_is_directory=True)
            with self.assertRaises(OSError): transport.private_directory(folder)
            link.unlink()
            link.mkdir(mode=0o755)
            with self.assertRaises(PermissionError): transport.private_directory(folder)

    def test_foreign_owner_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(transport.os, 'getuid', return_value=os.getuid()+1):
            with self.assertRaises(PermissionError): transport.private_directory(folder)

    def test_regular_file_is_never_removed_as_stale_socket(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'file'
            path.write_text('keep')
            with self.assertRaises(PermissionError): transport.remove_stale_socket(path)
            self.assertEqual(path.read_text(),'keep')

    def test_peer_uid_checked(self):
        client=Mock()
        client.getsockopt.return_value=struct.pack('3i',123,os.getuid()+1,123)
        with self.assertRaises(PermissionError): transport.require_owner_peer(client)
        client.getsockopt.return_value=struct.pack('3i',123,os.getuid(),123)
        transport.require_owner_peer(client)

    def test_adb_is_explicitly_private_even_with_tcp_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'ADB_SERVER_SOCKET':'tcp:localhost:5037'}):
            with patch.object(transport,'refuse_shared_adb'):
                args=transport.adb_command(['adb','-s','TEST','devices','-l'],folder)
            self.assertEqual(args[:3],['adb','-L','localfilesystem:'+str(Path(folder)/'omadesk/adb.sock')])
            self.assertEqual(args[3:],['-s','TEST','devices','-l'])

    def test_backend_routes_all_adb_commands(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(backend,'RUNTIME',Path(folder)), \
             patch.object(transport,'refuse_shared_adb'), patch.object(backend.subprocess,'run') as run:
            run.return_value=Mock(returncode=0,stdout='ok',stderr='')
            self.assertEqual(backend.command(['adb','devices','-l']),'ok')
            self.assertIn('localfilesystem:',run.call_args.args[0][2])
            self.assertEqual(run.call_args.kwargs['umask'],0o077)

    def test_shared_same_uid_adb_is_rejected(self):
        line=f'header\n 0: 0100007F:13AD 00000000:0000 0A 0:0 00:0 0 {os.getuid()} 0\n'
        with patch.object(Path,'read_text',return_value=line):
            with self.assertRaisesRegex(RuntimeError,'compartido'): transport.refuse_shared_adb()

    def test_rfb_stream_over_private_unix_sockets(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=transport.private_directory(folder)
            upstream_path=directory/'vnc.sock'
            quality_path=directory/'quality.sock'
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            listener.bind(str(upstream_path)); listener.listen(1); listener.settimeout(3)
            server=rfb.Server(quality_path,rfb.Handler,directory/'clients.json')
            server.upstream=upstream_path; server.quality=8; server.compression=2
            errors=[]
            expected=rfb.encodings_packet([7,-239],8,2)
            pointer=b'\x05\x00\x00\x14\x00\x28'
            header=struct.pack('>HH',1920,1200)+bytes(16)+struct.pack('>I',4)
            def upstream_worker():
                try:
                    with listener.accept()[0] as peer:
                        peer.settimeout(3)
                        peer.sendall(b'RFB 003.008\n')
                        self.assertEqual(rfb.read_exact(peer,12),b'RFB 003.008\n')
                        peer.sendall(b'\x01\x01')
                        self.assertEqual(rfb.read_exact(peer,1),b'\x01')
                        peer.sendall(bytes(4))
                        self.assertEqual(rfb.read_exact(peer,1),b'\x01')
                        peer.sendall(header+b'Test')
                        self.assertEqual(rfb.read_exact(peer,len(expected)+len(pointer)),expected+pointer)
                        peer.sendall(b'frame-data')
                        peer.recv(1)
                except Exception as error: errors.append(error)
            worker=threading.Thread(target=upstream_worker)
            serving=threading.Thread(target=server.serve_forever)
            worker.start(); serving.start()
            try:
                self.assertEqual(server.address_family,socket.AF_UNIX)
                self.assertEqual(stat.S_IMODE(quality_path.stat().st_mode),0o600)
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.settimeout(3); client.connect(str(quality_path))
                    self.assertEqual(rfb.read_exact(client,12),b'RFB 003.008\n')
                    client.sendall(b'RFB 003.008\n')
                    self.assertEqual(rfb.read_exact(client,2),b'\x01\x01')
                    client.sendall(b'\x01')
                    self.assertEqual(rfb.read_exact(client,4),bytes(4))
                    client.sendall(b'\x01')
                    self.assertEqual(rfb.read_exact(client,28),header+b'Test')
                    client.sendall(rfb.encodings_packet([7,-239],0,9)+pointer)
                    self.assertEqual(rfb.read_exact(client,10),b'frame-data')
                    self.assertEqual(json.loads((directory/'clients.json').read_text())['clients'],1)
            finally:
                server.shutdown(); server.server_close(); listener.close()
                serving.join(timeout=3); worker.join(timeout=3)
            self.assertFalse(errors)


if __name__=='__main__': unittest.main()
