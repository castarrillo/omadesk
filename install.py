#!/usr/bin/env python3
"""Install only Omadesk-owned files, with backups; never copy personal settings."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))
DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
DEST = CONFIG/'omarchy/plugins/local.tablet-usb'
FILES = ['Main.qml','manifest.json','backend.py','rfb_quality.py','setup_device.py',
         'install.sh','install.py','README.md','LICENSE','.gitignore']


def main():
    backups = DATA/'omadesk/backups'
    backups.mkdir(parents=True,exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='install-',dir=backups))
    DEST.mkdir(parents=True,exist_ok=True)
    for name in FILES:
        source, dest = SOURCE/name, DEST/name
        if source.resolve() == dest.resolve():
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
        dest.write_text('#!/usr/bin/env bash\nexec /usr/bin/python "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.tablet-usb/backend.py" "$@"\n')
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
    subprocess.run(['omarchy','plugin','enable','local.tablet-usb'],check=True)
    print('Omadesk instalado en ' + str(DEST))
    print('Respaldos: ' + str(backup))


if __name__ == '__main__':
    main()
