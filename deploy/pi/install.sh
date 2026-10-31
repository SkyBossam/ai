#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
mode="${1:-usb}"
test "$mode" = usb || test "$mode" = csi || { echo 'Usage: bash deploy/pi/install.sh [usb|csi]'; exit 2; }
if test "$(uname -m)" = armv7l; then
  test "$mode" = usb || { echo 'ARMv7 profile currently supports USB cameras.'; exit 1; }
  exec bash deploy/pi/install-armv7.sh
fi
test "$(uname -m)" = aarch64 || { echo 'Requires Raspberry Pi OS 64-bit (aarch64).'; exit 1; }
python3 - <<'PY'
import sys
assert (3,11) <= sys.version_info[:2] <= (3,13), 'Use Python 3.11, 3.12 or 3.13 on 64-bit Raspberry Pi OS.'
PY
if test -e .venv; then
  echo '.venv already exists. Reuse it, or extract a fresh release into a new folder.'
  exit 1
fi
sudo apt-get update
sudo apt-get install -y python3-venv libgomp1
if test "$mode" = csi; then
  sudo apt-get install -y python3-picamera2 python3-opencv python3-numpy
  python3 -m venv --system-site-packages .venv
else
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --only-binary=:all: -r "deploy/pi/requirements-$mode.txt"
.venv/bin/python -m pip check
.venv/bin/python - "$mode" <<'PY'
import json,sys
from pathlib import Path
p=Path('deploy/pi/config.json')
c=json.loads(p.read_text())
c['camera_backend']='picamera2' if sys.argv[1]=='csi' else 'opencv'
p.write_text(json.dumps(c,indent=2)+'\n')
PY
.venv/bin/python -m pip freeze > runtime-installed.txt
bash deploy/pi/edge.sh check
echo 'Installed. Run: bash deploy/pi/edge.sh snapshot --output snapshot.jpg'
