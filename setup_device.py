#!/usr/bin/env python3
"""Explicit, USB-only Android enrollment. No root, firmware or private app data."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.request import urlopen

import backend

AVNC_VERSION = '3.3.1'
AVNC_URL = 'https://github.com/gujjwal00/avnc/releases/download/v3.3.1/AVNC-3.3.1.apk'
AVNC_SHA256 = '61cb507e9f334f0276eacc8e9574bae6934d18e59c96b49f900a1183637d8f88'
PACKAGE = 'com.gaurav.avnc'


def select_device(devices, serial=None):
    if serial:
        matches = [d for d in devices if d['serial'] == serial]
        if not matches:
            raise ValueError('El número de serie no corresponde a un dispositivo USB conectado')
    else:
        matches = devices
    if not matches:
        raise ValueError('No hay dispositivos USB. Conecta un cable de datos y activa Depuración USB.')
    if len(matches) != 1:
        raise ValueError('Hay varios dispositivos. Usa --serial con uno de: ' + ', '.join(d['serial'] for d in matches))
    device = matches[0]
    if device['state'] != 'device':
        raise ValueError('Dispositivo ' + device['state'] + ': desbloquéalo y acepta la autorización de Depuración USB; después repite omadesk setup.')
    return device


def parse_display(size, display):
    match = re.search(r'Physical size:\s*(\d+)x(\d+)', size)
    if not match:
        raise ValueError('Android no informó una resolución física válida')
    width, height = map(int, match.groups())
    modes = [(int(w), int(h), float(hz)) for w,h,hz in re.findall(
        r'width=(\d+),\s*height=(\d+),\s*fps=([\d.]+)', display)]
    rates = [hz for w,h,hz in modes if sorted((w,h)) == sorted((width,height)) and math.isfinite(hz) and 10 <= hz <= 240]
    # Some Android vendors don't expose supportedModes in dumpsys.
    refresh = round(max(rates)) if rates else 60
    return dict(width=width, height=height, refresh=refresh,
                refreshDetected=bool(rates))


def proposed_config(device, cap):
    width, height = sorted((cap['width'], cap['height']), reverse=True)
    ratio = min(1, 4096 / width, 4096 / height, math.sqrt((4096*2160)/(width*height)))
    width, height = int(width*ratio)//2*2, int(height*ratio)//2*2
    scale = next((s for s in ([1.6,1.25,1] if width > 1920 else [1])
                  if all(abs(n/s - round(n/s)) < 0.01 for n in (width,height))), 1)
    return backend.validate(backend.DEFAULTS | dict(serial=device['serial'], width=width,
        height=height, refresh=min(120,cap['refresh']), fps=min(60,cap['refresh']), scale=scale))


def verified_apk(source=None):
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache')) / 'omadesk'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f'AVNC-{AVNC_VERSION}.apk'
    if source:
        source = Path(source).expanduser().resolve()
        if hashlib.sha256(source.read_bytes()).hexdigest() != AVNC_SHA256:
            raise ValueError('El APK local no coincide con el SHA-256 fijado de AVNC ' + AVNC_VERSION)
        return source
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == AVNC_SHA256:
        return target
    fd, name = tempfile.mkstemp(dir=cache, prefix='.download-')
    try:
        print('Descargando AVNC oficial ' + AVNC_VERSION + '…', flush=True)
        with os.fdopen(fd,'wb') as stream, urlopen(AVNC_URL, timeout=60) as response:
            digest = hashlib.sha256()
            total = 0
            while chunk := response.read(65536):
                total += len(chunk)
                if total > 50*1024*1024:
                    raise ValueError('El APK supera el tamaño permitido')
                digest.update(chunk)
                stream.write(chunk)
        if digest.hexdigest() != AVNC_SHA256:
            raise ValueError('Falló la verificación SHA-256; no se instalará el APK')
        os.replace(name,target)
    finally:
        Path(name).unlink(missing_ok=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='Omadesk: prepara Android por USB e instala AVNC si falta')
    parser.add_argument('--serial', help='Número de serie de adb devices -l')
    parser.add_argument('--reset-image', action='store_true', help='Usar ajustes detectados incluso si ya existen ajustes de este dispositivo')
    parser.add_argument('--apk', help='APK oficial AVNC 3.3.1 local; se verifica SHA-256')
    parser.add_argument('--dry-run', action='store_true', help='Solo detectar y mostrar; no descargar, instalar ni guardar')
    args = parser.parse_args(argv)
    device = select_device(backend.usb_devices(), args.serial)
    adb = ['adb','-s',device['serial']]
    sdk = int(backend.command(adb + ['shell','getprop','ro.build.version.sdk']))
    if sdk < 21:
        raise ValueError('Esta versión de AVNC requiere Android 5.0 (API 21) o posterior')
    cap = parse_display(backend.command(adb+['shell','wm','size']),
                        backend.command(adb+['shell','dumpsys','display']))
    cap['model'] = device['model']
    proposal = proposed_config(device, cap)
    installed = backend.command(adb+['shell','pm','path','--user','0',PACKAGE], check=False).startswith('package:')
    print(json.dumps(dict(device=device, panel=cap, avncInstalled=installed, proposed=proposal), indent=2, ensure_ascii=False), flush=True)
    if args.dry_run:
        return
    if not installed:
        apk = verified_apk(args.apk)
        print('Instalando AVNC en el dispositivo autorizado…', flush=True)
        result = backend.command(adb+['install',str(apk)], timeout=120)
        if 'Success' not in result:
            raise RuntimeError('Android no confirmó la instalación: ' + result)
        if not backend.command(adb+['shell','pm','path','--user','0',PACKAGE],check=False).startswith('package:'):
            raise RuntimeError('No se pudo confirmar AVNC. Comprueba si Android requiere aprobar la instalación USB.')
    else:
        print('AVNC ya está instalado; se conserva su versión y sus datos.', flush=True)
    with (backend.RUNTIME / 'tablet-usb-control.lock').open('w') as lock:
        import fcntl
        fcntl.flock(lock,fcntl.LOCK_EX)
        known_path = backend.CONFIG.parent / 'devices.json'
        known = json.loads(known_path.read_text()) if known_path.exists() else {}
        known[device['serial']] = cap
        backend.atomic_json(known_path,known)
        existing = json.loads(backend.CONFIG.read_text()) if backend.CONFIG.exists() else None
        if existing and existing.get('serial') == device['serial'] and not args.reset_image:
            print('Se conservan tus ajustes actuales de imagen y posición.',flush=True)
        else:
            if existing:
                fd, backup = tempfile.mkstemp(dir=backend.CONFIG.parent,prefix='settings.backup-',suffix='.json')
                with os.fdopen(fd,'w') as stream:
                    json.dump(existing,stream,indent=2)
                print('Respaldo de ajustes anteriores: ' + backup,flush=True)
            backend.atomic_json(backend.CONFIG,proposal)
    print('Omadesk listo. Abre el panel o ejecuta: omadesk start',flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Omadesk: ' + str(error),file=sys.stderr)
        sys.exit(1)
