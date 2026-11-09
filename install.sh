#!/usr/bin/env bash
set -euo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --help ]]; then
  echo 'Uso: ./install.sh [--serial SERIAL] [--apk APK] [--reset-image] [--skip-device] [--no-restart]'
  exit 0
fi
if (( EUID == 0 )); then
  echo 'Ejecuta el instalador como tu usuario de escritorio, no con sudo.' >&2
  exit 1
fi
skip=0
restart=1
setup_args=()
while (( $# )); do
  case "$1" in
    --skip-device) skip=1; shift ;;
    --no-restart) restart=0; shift ;;
    --reset-image) setup_args+=("$1"); shift ;;
    --serial|--apk) [[ $# -ge 2 ]] || { echo "Falta valor para $1" >&2; exit 2; }; setup_args+=("$1" "$2"); shift 2 ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done
command -v omarchy >/dev/null || { echo 'Se requiere Omarchy con Quickshell y Hyprland Lua (hl.monitor).' >&2; exit 1; }
packages=(android-tools android-udev wayvnc python jq iproute2)
missing=()
for package in "${packages[@]}"; do pacman -Q "$package" >/dev/null 2>&1 || missing+=("$package"); done
if (( ${#missing[@]} )); then
  echo "Instalando dependencias del PC: ${missing[*]}"
  if [[ -t 0 && -t 1 ]]; then
    omarchy pkg add "${missing[@]}"
  else
    pkexec /usr/bin/omarchy-pkg-add "${missing[@]}"
  fi
fi
/usr/bin/python "$SOURCE/install.py"
if (( restart )); then omarchy restart shell; fi
if (( ! skip )); then
  echo 'Preparando el Android conectado. Desbloquéalo y acepta la autorización USB si aparece.'
  /usr/bin/python "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.castarrillo.omadesk/setup_device.py" "${setup_args[@]}"
fi
echo 'Instalación finalizada. Abre Omadesk en la barra o ejecuta: omadesk start'
