#!/usr/bin/env python3
"""Omadesk controller. Settings are JSON, never evaluated as shell code."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'tablet-usb/settings.json'
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
STATE = RUNTIME / 'tablet-usb-state.json'
UNIT = 'tablet-usb.service'
OUTPUT = 'TABLET-USB'
DEFAULTS = dict(serial='', width=1920, height=1200, refresh=60,
                fps=60, scale=1.5, position='right', anchor='', x=0, y=0,
                quality=8, compression=2, input=True, cursor=True)


def command(args, timeout=10, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Falló el comando').strip())
    return result.stdout.strip()


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.tablet-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Configuración inválida o campos desconocidos')
    cfg = DEFAULTS | value
    for key, low, high in [('width', 480, 4096), ('height', 480, 4096),
                           ('refresh', 10, 120), ('fps', 1, 60), ('quality', 0, 9),
                           ('compression', 0, 9), ('x', -32768, 32768), ('y', -32768, 32768)]:
        if type(cfg[key]) is not int or not low <= cfg[key] <= high:
            raise ValueError(f'{key}: debe estar entre {low} y {high}')
    if cfg['width'] * cfg['height'] > 4096 * 2160:
        raise ValueError('La resolución supera el límite de 8 847 360 píxeles')
    if cfg['width'] % 2 or cfg['height'] % 2:
        raise ValueError('Las dimensiones deben ser pares')
    if cfg['fps'] > cfg['refresh']:
        raise ValueError('Los FPS no deben superar la frecuencia del monitor')
    if type(cfg['scale']) not in (float, int) or not math.isfinite(cfg['scale']) or not 1 <= cfg['scale'] <= 3:
        raise ValueError('Escala: debe estar entre 1 y 3')
    # Hyprland requires integral logical dimensions at the requested scale.
    if any(abs(n / cfg['scale'] - round(n / cfg['scale'])) > 0.01 for n in (cfg['width'], cfg['height'])):
        raise ValueError('Esta escala no divide la resolución en píxeles lógicos enteros; prueba 100 %, 125 %, 150 % o 200 %. A 2560×1600, usa 125 % o 200 %; para 150 %, prueba 1920×1200.')
    for key in ('input', 'cursor'):
        if type(cfg[key]) is not bool:
            raise ValueError(f'{key}: se requiere un booleano')
    if cfg['position'] not in ('right', 'left', 'above', 'below', 'custom'):
        raise ValueError('Posición desconocida')
    if not isinstance(cfg['serial'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{0,100}', cfg['serial']):
        raise ValueError('Número de serie USB inválido')
    if not isinstance(cfg['anchor'], str) or len(cfg['anchor']) > 150:
        raise ValueError('Monitor de referencia inválido')
    return cfg


def settings():
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    # Preserve compatibility with the original CLI environment overrides.
    if os.environ.get('TABLET_SERIAL'):
        cfg['serial'] = os.environ['TABLET_SERIAL']
    if os.environ.get('TABLET_SCALE'):
        cfg['scale'] = float(os.environ['TABLET_SCALE'])
    if os.environ.get('TABLET_MODE'):
        match = re.fullmatch(r'(\d+)x(\d+)@(\d+)', os.environ['TABLET_MODE'])
        if not match:
            raise ValueError('TABLET_MODE inválido')
        cfg.update(zip(('width', 'height', 'refresh'), map(int, match.groups())))
        cfg['fps'] = min(cfg.get('fps', 60), cfg['refresh'])
    return validate(cfg)


def monitors():
    return json.loads(command(['hyprctl', 'monitors', '-j']))


def position(cfg, screens):
    screens = [m for m in screens if m['name'] != OUTPUT]
    if cfg['position'] == 'custom':
        return cfg['x'], cfg['y']
    if cfg['anchor']:
        screens = [m for m in screens if m['name'] == cfg['anchor']]
        if not screens:
            raise ValueError('El monitor de referencia no está conectado')
    if not screens:
        return 0, 0
    def size(m):
        w, h = m['width'], m['height']
        if m.get('transform', 0) % 2:
            w, h = h, w
        return round(w / m['scale']), round(h / m['scale'])
    left, top = min(m['x'] for m in screens), min(m['y'] for m in screens)
    right = max(m['x'] + size(m)[0] for m in screens)
    bottom = max(m['y'] + size(m)[1] for m in screens)
    width, height = round(cfg['width'] / cfg['scale']), round(cfg['height'] / cfg['scale'])
    return {'right': (right, top), 'left': (left - width, top),
            'above': (left, top - height), 'below': (left, bottom)}[cfg['position']]


def active():
    return command(['systemctl', '--user', 'is-active', UNIT], check=False) == 'active'


def usb_devices():
    lines = command(['adb', 'devices', '-l']).splitlines()[1:]
    return [dict(serial=p[0], state=p[1], model=next((x[6:] for x in p if x.startswith('model:')), 'Android'))
            for line in lines if len(p := line.split()) >= 2 and any(x.startswith('usb:') for x in p)]


def require_usb(cfg):
    if not cfg['serial']:
        raise RuntimeError('Ejecuta omadesk setup para preparar el dispositivo Android conectado.')
    if not any(d['serial'] == cfg['serial'] and d['state'] == 'device' for d in usb_devices()):
        raise RuntimeError('Tablet USB no disponible. Conecta el cable, desbloquea y autoriza la depuración USB.')


def inspect_device(serial):
    from setup_device import parse_display
    require_usb({'serial': serial})
    adb = ['adb', '-s', serial, 'shell']
    cap = parse_display(command(adb + ['wm','size']), command(adb + ['dumpsys','display']))
    cap['model'] = command(adb + ['getprop','ro.product.model'])
    path = CONFIG.parent / 'devices.json'
    known = json.loads(path.read_text()) if path.exists() else {}
    known[serial] = cap
    atomic_json(path,known)
    return cap


def status():
    cfg = settings()
    screens = monitors()
    is_active = active()
    state = json.loads(STATE.read_text()) if STATE.exists() and is_active else {}
    clients = command(['ss', '-tnH', 'sport = :5909'], check=False)
    return dict(settings=cfg, active=is_active, connected=is_active and 'ESTAB' in clients,
                devices=usb_devices(), monitors=[dict(name=m['name'], description=m.get('description', ''))
                                               for m in screens if m['name'] != OUTPUT],
                monitor=next((m for m in screens if m['name'] == OUTPUT), None),
                applied=state.get('settings'), configPath=str(CONFIG),
                capabilities=capabilities(cfg['serial']))


def capabilities(serial):
    path = CONFIG.parent / 'devices.json'
    return json.loads(path.read_text()).get(serial, {}) if path.exists() else {}


def start():
    if active():
        return
    cfg = settings()
    require_usb(cfg)
    inspect_device(cfg['serial'])
    position(cfg, monitors())  # Fail before starting, not in the background.
    env = {key: os.environ[key] for key in ('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE') if os.environ.get(key)}
    if len(env) != 2:
        raise RuntimeError('Ejecuta este comando dentro de la sesión de Hyprland')
    STATE.unlink(missing_ok=True)
    args = ['systemd-run', '--user', '--collect', '--unit=tablet-usb',
            '--description=Omadesk — monitor extendido', '--property=TimeoutStopSec=12']
    args += [f'--setenv={k}={v}' for k, v in env.items()]
    # A validated immutable snapshot avoids races between edits and startup.
    args += [sys.executable, str(HERE / 'backend.py'), 'run', '--snapshot', json.dumps(cfg)]
    command(args)
    for _ in range(100):
        if STATE.exists():
            return
        service_state = command(['systemctl', '--user', 'is-active', UNIT], check=False)
        if service_state not in ('active', 'activating'):
            break
        time.sleep(0.1)
    log = command(['journalctl', '--user', '-u', UNIT, '-n', '6', '--no-pager'], check=False)
    raise RuntimeError('No se pudo iniciar. ' + log)


def stop():
    command(['systemctl', '--user', 'stop', UNIT], timeout=20, check=False)


def open_viewer(cfg):
    uri = 'vnc://127.0.0.1:5909?' + urlencode(dict(ConnectionName='Omarchy USB', ViewOnly=str(not cfg['input']).lower()))
    # ADB shell does not preserve argv quoting. URI is quoted, entirely generated.
    command(['adb', '-s', cfg['serial'], 'shell', 'am', 'start', '-S', '-a',
             'android.intent.action.VIEW', '-d', "'" + uri + "'", '-p', 'com.gaurav.avnc'])


def wait_port(port, proc):
    for _ in range(60):
        if proc.poll() is not None:
            raise RuntimeError(f'Proceso de transmisión terminó ({proc.returncode})')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f'No se abrió el puerto local {port}')


def monitor_matches(current, cfg, x, y):
    """Compare physical mode and logical geometry, tolerating refresh rounding."""
    return bool(current and current.get('width') == cfg['width']
                and current.get('height') == cfg['height']
                and abs(current.get('refreshRate', 0) - cfg['refresh']) < 0.15
                and abs(current.get('scale', 0) - cfg['scale']) < 0.001
                and current.get('x') == x and current.get('y') == y
                and current.get('transform', 0) == 0
                and not current.get('disabled', False))


def ensure_monitor(cfg, x, y):
    """Pin the active snapshot, not saved-but-unapplied settings or auto layout.

    Hyprland reload/hotplug may reset a headless output to its default mode.
    Reapply only our output and only on drift. Relative positions are resolved
    once when connecting: unplugging a physical monitor must not move Android.
    """
    current = next((m for m in monitors() if m['name'] == OUTPUT), None)
    if monitor_matches(current, cfg, x, y):
        return False
    if current is None:
        command(['hyprctl', 'output', 'create', 'headless', OUTPUT])
    mode = f'{cfg["width"]}x{cfg["height"]}@{cfg["refresh"]}'
    lua = f'hl.monitor({{output="{OUTPUT}",mode="{mode}",position="{x}x{y}",scale={cfg["scale"]},transform=0' + '})'
    result = command(['hyprctl', 'eval', lua])
    if result != 'ok':
        raise RuntimeError(result)
    return True


def run(cfg):
    lock = (RUNTIME / 'tablet-usb.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    children, created, reverse_installed = [], False, False
    # Do not interrupt cleanup when systemd signals the whole cgroup.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    try:
        require_usb(cfg)
        screens = monitors()
        if any(m['name'] == OUTPUT for m in screens):
            raise RuntimeError('TABLET-USB ya existe; no se modificará un monitor ajeno')
        for port in (5909, 5910):
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', port))
        x, y = position(cfg, screens)
        command(['hyprctl', 'output', 'create', 'headless', OUTPUT])
        created = True
        ensure_monitor(cfg, x, y)
        mode = f'{cfg["width"]}x{cfg["height"]}@{cfg["refresh"]}'
        args = ['wayvnc', '-C', '/dev/null', '-S', str(RUNTIME / 'tablet-usb-wayvnc'),
                '-o', OUTPUT, '-f', str(cfg['fps']), '-R', '-L', 'info']
        if cfg['cursor']:
            args.append('-r')
        if not cfg['input']:
            args.append('-d')
        children.append(subprocess.Popen(args + ['127.0.0.1', '5910']))
        wait_port(5910, children[-1])
        children.append(subprocess.Popen([sys.executable, str(HERE / 'rfb_quality.py'),
                                         '--quality', str(cfg['quality']), '--compression', str(cfg['compression'])]))
        wait_port(5909, children[-1])
        command(['adb', '-s', cfg['serial'], 'reverse', 'tcp:5909', 'tcp:5909'])
        reverse_installed = True
        open_viewer(cfg)
        atomic_json(STATE, dict(settings=cfg, position=[x, y], started=time.time()))
        print(f'Monitor USB listo: {mode}, escala {cfg["scale"]}, {x}x{y}', flush=True)
        while all(p.poll() is None for p in children):
            if command(['adb', '-s', cfg['serial'], 'get-state'], timeout=5, check=False) != 'device':
                print('USB desconectado', flush=True)
                return
            try:
                if ensure_monitor(cfg, x, y):
                    print(f'Geometría restaurada tras recarga/hotplug: {mode}, escala {cfg["scale"]}, {x}x{y}', flush=True)
            except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
                # Compositor topology may be unsettled while hotplug/reload runs.
                # Keep the USB session alive and retry on the next iteration.
                print(f'No se pudo restaurar el monitor todavía; se reintentará: {error}', flush=True)
            time.sleep(2)
        raise RuntimeError('Un proceso de transmisión terminó; consulta el registro')
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        try:
            if reverse_installed:
                command(['adb', '-s', cfg['serial'], 'reverse', '--remove', 'tcp:5909'], timeout=4, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            if created:
                command(['hyprctl', 'output', 'remove', OUTPUT], check=False)
        finally:
            STATE.unlink(missing_ok=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'setup':
        from setup_device import main as setup_main
        setup_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', default='start', choices=['start', 'stop', 'restart', 'status',
                        'save', 'apply', 'run', 'logs', 'viewer', 'detect'])
    parser.add_argument('--settings')
    parser.add_argument('--snapshot')
    args = parser.parse_args()
    if args.action == 'run':
        run(validate(json.loads(args.snapshot)))
        return
    with (RUNTIME / 'tablet-usb-control.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == 'apply':
            cfg = validate(json.loads(args.settings))
            require_usb(cfg)
            position(cfg, monitors())
            previous = CONFIG.read_bytes() if CONFIG.exists() else None
            previous_active = active()
            # Keep the running snapshot, not unapplied saved settings, for rollback.
            previous_running = json.loads(STATE.read_text()).get('settings') if STATE.exists() and previous_active else None
            stop()
            atomic_json(CONFIG, cfg)
            try:
                start()
            except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                stop()
                if previous_running:
                    atomic_json(CONFIG, previous_running)
                    try:
                        start()
                    except (RuntimeError, OSError, subprocess.SubprocessError):
                        pass
                if previous is None:
                    CONFIG.unlink(missing_ok=True)
                else:
                    atomic_json(CONFIG, json.loads(previous))
                raise RuntimeError(f'No se aplicaron los cambios; configuración anterior restaurada. {error}')
            print(json.dumps(status(), ensure_ascii=False))
            return
        if args.action in ('save', 'apply'):
            cfg = validate(json.loads(args.settings))
            atomic_json(CONFIG, cfg)
        if args.action in ('stop', 'restart') or args.action == 'apply' and active():
            stop()
        if args.action in ('start', 'restart', 'apply'):
            start()
        if args.action == 'viewer':
            require_usb(settings())
            if not active():
                raise RuntimeError('El monitor no está iniciado')
            open_viewer(settings())
        if args.action == 'logs':
            print(json.dumps(dict(logs=command(['journalctl', '--user', '-u', UNIT, '-n', '45', '--no-pager']))))
            return
        if args.action == 'detect':
            cfg = settings()
            require_usb(cfg)
            inspect_device(cfg['serial'])
            print(json.dumps(status(),ensure_ascii=False))
            return
        print(json.dumps(status(), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(error=str(error)), ensure_ascii=False))
        sys.exit(1)
