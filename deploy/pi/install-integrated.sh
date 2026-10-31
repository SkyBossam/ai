#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
sha256sum -c SHA256SUMS
if ! test -d .venv; then bash deploy/pi/install-armv7.sh; fi
sudo apt-get install -y --no-upgrade alsa-utils
.venv/bin/python -m pip install --only-binary=:all: tflite-runtime==2.13.0
.venv/bin/python -m pip check
python3 deploy/pi/install_device_launchers.py
python3 deploy/pi/install_cry.py
python3 deploy/pi/install_integrated.py
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 .venv/bin/python -m sky_edge.personalization demo --output assets/cause-demo.json
echo 'Run: bash ~/sky-eye/start-all.sh'
