#!/usr/bin/env python3
"""Install only Omadesk-owned files, with backups; never copy personal settings."""
import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

SOURCE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))
DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
PLUGIN_ID = 'io.github.castarrillo.omadesk'
LEGACY_ID = 'local.tablet-usb'
DEST = CONFIG/'omarchy/plugins'/PLUGIN_ID
FILES = ['Main.qml','manifest.json','backend.py','rfb_quality.py','setup_device.py',
         'install.sh','install.py','uninstall.py','README.md','LICENSE','.gitignore','preview.png']


def migrate_layout(value):
    """Only rename plugin ID fields; preserve placement and unrelated settings."""
    if isinstance(value,list):
        return [migrate_layout(item) for item in value]
    if isinstance(value,dict):
        return {key: PLUGIN_ID if key == 'id' and item == LEGACY_ID else migrate_layout(item)
                for key,item in value.items()}
    return value


def migrate_shell(backup):
    shell = CONFIG/'omarchy/shell.json'
    if not shell.exists():
        return
    old = json.loads(shell.read_text())
    new = migrate_layout(old)
    if old == new:
        return
    shutil.copy2(shell,backup/'shell.json')
    fd,name = tempfile.mkstemp(dir=shell.parent,prefix='.omadesk-migration-')
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(new,stream,indent=2,ensure_ascii=False)
            stream.write('\n')
        os.chmod(name,shell.stat().st_mode & 0o777)
        os.replace(name,shell)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    backups = DATA/'omadesk/backups'
    backups.mkdir(parents=True,exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='install-',dir=backups))
    if (DEST/'manifest.json').exists() and json.loads((DEST/'manifest.json').read_text()).get('id') != PLUGIN_ID:
        raise RuntimeError('El destino contiene otro plugin; no se sobrescribirá')
    DEST.mkdir(parents=True,exist_ok=True)
    for name in FILES:
        source, dest = SOURCE/name, DEST/name
        if source.resolve() == dest.resolve():
            continue
        if dest.is_file() and source.read_bytes() == dest.read_bytes():
            continue
        if dest.exists():
            shutil.copy2(dest,backup/name)
        shutil.copy2(source,dest)
    binary = Path.home()/'.local/bin'
    binary.mkdir(parents=True,exist_ok=True)
    for name in ('omadesk','tablet-usb'):
        dest = binary/name
        if dest.exists() or dest.is_symlink():
            shutil.copy2(dest,backup/name)
        # Resolve XDG paths at runtime, not a hard-coded home from the author.
        dest.write_text('#!/usr/bin/env bash\nexec /usr/bin/python "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.castarrillo.omadesk/backend.py" "$@"\n')
        dest.chmod(0o755)
    apps=DATA/'applications'
    apps.mkdir(parents=True,exist_ok=True)
    launcher=apps/'omadesk.desktop'
    if launcher.exists(): shutil.copy2(launcher,backup/launcher.name)
    executable=str(binary/'omadesk').replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')
    launcher.write_text('[Desktop Entry]\nType=Application\nName=Omadesk\nComment=Monitor extendido Android por USB\n'
        f'Exec="{executable}" start\nIcon=video-display\nTerminal=false\nCategories=Utility;\nActions=Stop;\n\n'
        f'[Desktop Action Stop]\nName=Desconectar Omadesk\nExec="{executable}" stop\n')
    old=apps/'tablet-usb.desktop'
    if old.exists() and 'tablet-usb start' in old.read_text():
        shutil.copy2(old,backup/'tablet-usb.desktop')
        old.unlink()
    subprocess.run(['omarchy','plugin','validate',str(DEST)],check=True)
    migrate_shell(backup)
    subprocess.run(['omarchy-shell','shell','rescanPlugins'],check=True,timeout=15)
    plugins=[]
    for _ in range(50):
        listing=subprocess.run(['omarchy-shell','shell','listPlugins'],capture_output=True,text=True,timeout=10,check=True)
        plugins=json.loads(listing.stdout)
        entry=next((plugin for plugin in plugins if plugin.get('id')==PLUGIN_ID),None)
        if entry is not None:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('La shell aún no reconoce Omadesk; ejecuta omarchy restart shell y repite el instalador')
    if not entry.get('enabled'):
        subprocess.run(['omarchy','plugin','enable',PLUGIN_ID],check=True)
    if (CONFIG/'omarchy/plugins'/LEGACY_ID).exists():
        if any(plugin.get('id')==LEGACY_ID and plugin.get('enabled') for plugin in plugins):
            subprocess.run(['omarchy','plugin','disable',LEGACY_ID],check=True)
        print('Identidad antigua deshabilitada; su carpeta se conserva para recuperación.')
    print('Omadesk instalado en ' + str(DEST))
    print('Respaldos: ' + str(backup))


if __name__ == '__main__':
    main()
