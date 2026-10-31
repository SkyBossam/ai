#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
test -x .venv/bin/python
mkdir -p "$HOME/.config/systemd/user"
python3 - "$PWD" "$HOME/.config/systemd/user/sky-eye.service" <<'PY'
import sys
from pathlib import Path
root=sys.argv[1]
def escape(s):
    return s.replace('\\','\\\\').replace('"','\\"').replace('%','%%')
unit='''[Unit]
Description=Sky Eye infant ONNX camera monitor

[Service]
Type=simple
WorkingDirectory=ROOT
ExecStart=/bin/bash "ROOT/deploy/pi/edge.sh" run
Restart=on-failure
RestartSec=5
TimeoutStopSec=10
UMask=0077

[Install]
WantedBy=default.target
'''.replace('ROOT',escape(root))
Path(sys.argv[2]).write_text(unit)
PY
systemctl --user daemon-reload
echo 'Service installed but not started. Start after camera/calibration checks:'
echo 'systemctl --user enable --now sky-eye'
echo 'journalctl --user -u sky-eye -f'
echo 'To run after SSH logout/reboot: sudo loginctl enable-linger "$USER"'
