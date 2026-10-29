#!/usr/bin/env python3
"""Local RFB 3.8 proxy: override JPEG quality/compression pseudo-encodings.

Frame pixels and input are not transformed. Only SetEncodings is rewritten.
Both ends bind/connect to IPv4 loopback; the public end is forwarded by ADB.
"""
import argparse
import logging
import socket
import socketserver
import struct
import threading


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
        raise ValueError('Loopback upstream must offer None security')
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
        try:
            with socket.create_connection(('127.0.0.1', self.server.upstream), timeout=10) as upstream:
                client.settimeout(10)
                handshake(client, upstream)
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


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5909)
    parser.add_argument('--upstream', type=int, default=5910)
    parser.add_argument('--quality', type=int, choices=range(10), default=8)
    parser.add_argument('--compression', type=int, choices=range(10), default=2)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='RFB: %(message)s')
    with Server(('127.0.0.1', args.port), Handler) as server:
        server.upstream = args.upstream
        server.quality = args.quality
        server.compression = args.compression
        server.serve_forever()
