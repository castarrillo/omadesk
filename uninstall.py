#!/usr/bin/env python3
"""Explicit uninstaller: preserve settings, APK, dependencies and backups."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from secure_transport import private_path

PLUGIN_ID = 'io.github.castarrillo.omadesk'


def owned_wrapper(path):
    return path.is_file() and not path.is_symlink() and f'/omarchy/plugins/{PLUGIN_ID}/backend.py' in path.read_text()


def main():
    parser=argparse.ArgumentParser(description='Desinstala Omadesk sin borrar tus ajustes ni AVNC')
    parser.add_argument('--yes',action='store_true',help='Confirmar la retirada del plugin, sus comandos y lanzador')
    args=parser.parse_args()
    config=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))
    data=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))
    target=config/'omarchy/plugins'/PLUGIN_ID
    if not (target/'manifest.json').is_file() or json.loads((target/'manifest.json').read_text()).get('id')!=PLUGIN_ID:
        raise RuntimeError('No se encuentra una instalación válida de Omadesk en el destino esperado')
    if not args.yes:
        print(f'Se retirará {target}, sus wrappers propios y el lanzador. Se conservan ajustes, AVNC y dependencias. Repite con --yes para confirmar.')
        return
    backups=data/'omadesk/backups'
    backups.mkdir(parents=True,exist_ok=True)
    backup=Path(tempfile.mkdtemp(prefix='uninstall-',dir=backups))
    shutil.copytree(target,backup/PLUGIN_ID,symlinks=True)
    subprocess.run(['systemctl','--user','stop','tablet-usb.service'],check=False,timeout=20)
    check=subprocess.run(['systemctl','--user','is-active','tablet-usb.service'],capture_output=True,text=True)
    if check.stdout.strip() in ('active','activating','deactivating'):
        raise RuntimeError('La transmisión sigue activa; no se retirará su código')
    subprocess.run(['adb','-L','localfilesystem:'+str(private_path('adb.sock')),'kill-server'],check=False,timeout=10,umask=0o077)
    for name in ('omadesk','tablet-usb'):
        path=Path.home()/'.local/bin'/name
        if owned_wrapper(path):
            shutil.copy2(path,backup/name)
            path.unlink()
    launcher=data/'applications/omadesk.desktop'
    if launcher.is_file() and 'Comment=Monitor extendido Android por USB' in launcher.read_text():
        shutil.copy2(launcher,backup/launcher.name)
        launcher.unlink()
    # Delegate exact-directory removal to the supported plugin manager.
    subprocess.run(['omarchy','plugin','remove',PLUGIN_ID,'--yes'],check=True)
    print(f'Omadesk retirado. Respaldo: {backup}')
    print('Se conservaron los ajustes, AVNC, los paquetes del sistema y cualquier instalación local.tablet-usb antigua.')


if __name__=='__main__':
    main()
