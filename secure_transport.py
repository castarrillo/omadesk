"""Linux owner-only transport. Never fall back to TCP or abstract sockets."""
import os
from pathlib import Path
import socket
import stat
import struct


def private_directory(runtime=None):
    runtime = Path(runtime or os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with_fd = os.open(runtime, flags)
    try:
        info = os.fstat(with_fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('XDG_RUNTIME_DIR debe pertenecer al usuario y ser privado (0700)')
        try:
            os.mkdir('omadesk', mode=0o700, dir_fd=with_fd)
        except FileExistsError:
            pass
        child = os.open('omadesk', flags, dir_fd=with_fd)
        try:
            info = os.fstat(child)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise PermissionError('El directorio de transporte Omadesk debe ser privado (0700)')
        finally:
            os.close(child)
    finally:
        os.close(with_fd)
    return runtime / 'omadesk'


def private_path(name, runtime=None):
    if name not in ('vnc.sock', 'quality.sock', 'adb.sock', 'wayvncctl', 'clients.json'):
        raise ValueError('Nombre de transporte desconocido')
    path = private_directory(runtime) / name
    if len(os.fsencode(path)) > 100:
        raise ValueError('La ruta del socket Unix es demasiado larga')
    return path


def remove_stale_socket(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
        raise PermissionError('No se sustituirá una ruta que no sea un socket propio: ' + str(path))
    path.unlink()


def require_owner_peer(client):
    if not hasattr(socket, 'SO_PEERCRED'):
        raise PermissionError('Se requiere SO_PEERCRED de Linux')
    _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != os.getuid():
        raise PermissionError('El cliente Unix pertenece a otra cuenta')


def adb_command(args, runtime=None):
    refuse_shared_adb()
    # -L explicitly selects the client AND server socket. No default port 5037.
    return [args[0], '-L', 'localfilesystem:' + str(private_path('adb.sock', runtime))] + args[1:]


def refuse_shared_adb():
    """A shared same-UID ADB daemon is a privileged local proxy; don't use it.

    We don't kill unrelated servers. Reject the conventional owner TCP server
    before every ADB operation (also checked by the active monitor loop).
    """
    for source in ('/proc/net/tcp', '/proc/net/tcp6'):
        for line in Path(source).read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 7 and fields[3] == '0A' and int(fields[1].rsplit(':', 1)[1], 16) == 5037 and int(fields[7]) == os.getuid():
                raise RuntimeError('Hay un servidor ADB TCP compartido de esta cuenta en 5037. Detén las herramientas que lo usan y ejecuta adb kill-server; Omadesk solo utiliza su socket ADB privado.')
