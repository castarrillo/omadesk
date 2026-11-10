#!/usr/bin/env python3
"""Local RFB 3.8 proxy: override JPEG quality/compression pseudo-encodings.

Frame pixels and input are not transformed. Only SetEncodings is rewritten.
Both ends use owner-only filesystem Unix sockets; the frontend is forwarded by
a private, filesystem-socket ADB server. There is no host TCP listener.
"""
import argparse
import logging
import socket
import socketserver
import struct
import threading
import json
import os
import tempfile
from secure_transport import private_path, require_owner_peer


def read_exact(sock, length):
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(min(length - len(data), 65536))
        if not chunk:
            raise EOFError()
        data.extend(chunk)
    return bytes(data)


def encodings_packet(encodings, quality, compression):
    encodings = [x for x in encodings if not (-32 <= x <= -23 or -256 <= x <= -247)]
    encodings.extend([-32 + quality, -256 + compression])
    return struct.pack('>BBH', 2, 0, len(encodings)) + b''.join(
        struct.pack('>i', x) for x in encodings)


def forward_client(client, upstream, quality, compression):
    """Parse bounded standard RFB client messages, never guess unknown lengths."""
    fixed = {0: 19, 3: 9, 4: 7, 5: 5, 150: 9, 255: 3}
    while True:
        kind = read_exact(client, 1)
        message_type = kind[0]
        if message_type == 2:
            header = read_exact(client, 3)
            count = struct.unpack('>H', header[1:])[0]
            values = struct.unpack('>' + 'i' * count, read_exact(client, count * 4))
            upstream.sendall(encodings_packet(values, quality, compression))
            logging.info('SetEncodings: quality=%s compression=%s', quality, compression)
        elif message_type in fixed:
            upstream.sendall(kind + read_exact(client, fixed[message_type]))
        elif message_type == 6:  # ClientCutText, including extended clipboard
            header = read_exact(client, 7)
            size = abs(struct.unpack('>i', header[3:])[0])
            if size > 16 * 1024 * 1024:
                raise ValueError('Clipboard exceeds 16 MiB')
            upstream.sendall(kind + header + read_exact(client, size))
        elif message_type == 248:  # Fence
            header = read_exact(client, 8)
            upstream.sendall(kind + header + read_exact(client, header[7]))
        elif message_type == 251:  # SetDesktopSize
            header = read_exact(client, 7)
            upstream.sendall(kind + header + read_exact(client, header[5] * 16))
        else:
            raise ValueError(f'Unsupported RFB client message: {message_type}')


def handshake(client, upstream):
    version = read_exact(upstream, 12)
    if version != b'RFB 003.008\n':
        raise ValueError('Requires RFB 3.8')
    client.sendall(version)
    if read_exact(client, 12) != version:
        raise ValueError('Requires RFB 3.8 client')
    upstream.sendall(version)
    count = read_exact(upstream, 1)
    types = read_exact(upstream, count[0])
    if 1 not in types:
        raise ValueError('Owner-only Unix upstream must offer None security')
    client.sendall(b'\x01\x01')
    if read_exact(client, 1) != b'\x01':
        raise ValueError('Unexpected security selection')
    upstream.sendall(b'\x01')
    result = read_exact(upstream, 4)
    client.sendall(result)
    if result != b'\0\0\0\0':
        raise ValueError('Upstream rejected connection')
    upstream.sendall(read_exact(client, 1))
    info = read_exact(upstream, 24)
    length = struct.unpack('>I', info[20:])[0]
    if length > 65536:
        raise ValueError('Invalid server name')
    client.sendall(info + read_exact(upstream, length))


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        registered = False
        try:
            require_owner_peer(client)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
                upstream.settimeout(10)
                upstream.connect(str(self.server.upstream))
                client.settimeout(10)
                handshake(client, upstream)
                self.server.client_delta(1)
                registered = True
                client.settimeout(None)
                upstream.settimeout(None)

                def pixels():
                    try:
                        while chunk := upstream.recv(65536):
                            client.sendall(chunk)
                    except OSError:
                        pass
                    finally:
                        try:
                            client.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass

                thread = threading.Thread(target=pixels, daemon=True)
                thread.start()
                try:
                    forward_client(client, upstream, self.server.quality, self.server.compression)
                finally:
                    try:
                        upstream.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    thread.join(timeout=2)
        except (OSError, EOFError, ValueError) as error:
            logging.info('Client disconnected: %s', error)
        finally:
            if registered:
                self.server.client_delta(-1)


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, address, handler, status_path=None):
        self.status_path = status_path
        self.status_lock = threading.Lock()
        self.clients = 0
        super().__init__(str(address), handler)
        os.chmod(address, 0o600)
        self.client_delta(0)

    def client_delta(self, delta):
        with self.status_lock:
            self.clients += delta
            if self.status_path is not None:
                fd, name = tempfile.mkstemp(dir=self.status_path.parent, prefix='.clients-')
                try:
                    with os.fdopen(fd, 'w') as stream:
                        json.dump({'clients': self.clients}, stream)
                    os.replace(name, self.status_path)
                finally:
                    if os.path.exists(name):
                        os.unlink(name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--quality', type=int, choices=range(10), default=8)
    parser.add_argument('--compression', type=int, choices=range(10), default=2)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='RFB: %(message)s')
    os.umask(0o077)
    with Server(private_path('quality.sock'), Handler, private_path('clients.json')) as server:
        server.upstream = private_path('vnc.sock')
        server.quality = args.quality
        server.compression = args.compression
        server.serve_forever()
