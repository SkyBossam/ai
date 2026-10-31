"""Install local launch commands and two mutually exclusive user services."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
MARKER='# Managed by sky-eye install_device_launchers.py\n'

def managed(path,text):
    if path.exists() and not path.read_text().startswith(MARKER):
        raise FileExistsError('Existing unmanaged file: '+str(path))
    path.write_text(MARKER+text)

def main():
    alias=Path.home()/'sky-eye'
    if alias.exists() or alias.is_symlink():
        assert alias.resolve()==ROOT, 'Existing ~/sky-eye points elsewhere'
    else:
        alias.symlink_to(ROOT,target_is_directory=True)
    folder=Path.home()/'.config/systemd/user'
    folder.mkdir(parents=True,exist_ok=True)
    def quoted(text):
        return '"'+str(text).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    for name,other,extra in [('sky-eye','sky-eye-objects',''),
                            ('sky-eye-objects','sky-eye',' --config deploy/pi/config.objects.json')]:
        unit='''[Unit]
Description=Sky Eye infant camera monitor
Conflicts=OTHER.service

[Service]
Type=simple
WorkingDirectory=ROOT
ExecStart=/bin/bash EDGE runEXTRA
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
UMask=0077

[Install]
WantedBy=default.target
'''.replace('OTHER',other).replace('ROOT',str(ROOT).replace('%','%%')).replace('EDGE',quoted(ROOT/'deploy/pi/edge.sh')).replace('EXTRA',extra)
        managed(folder/(name+'.service'),unit)
    managed(ROOT/'start.sh','''set -euo pipefail
case "${1:-baseline}" in
  baseline) unit=sky-eye;;
  objects) unit=sky-eye-objects;;
  *) echo 'Usage: bash start.sh [baseline|objects]'; exit 2;;
esac
systemctl --user daemon-reload
for previous in sky-eye sky-eye-objects; do
  if test "$(systemctl --user show "$previous" -p LoadState --value)" = loaded; then
    systemctl --user stop "$previous"
  fi
done
systemctl --user start "$unit"
systemctl --user --no-pager status "$unit"
''')
    managed(ROOT/'stop.sh','''set -euo pipefail
systemctl --user daemon-reload
for previous in sky-eye sky-eye-objects; do
  if test "$(systemctl --user show "$previous" -p LoadState --value)" = loaded; then
    systemctl --user stop "$previous"
  fi
done
''')
    managed(ROOT/'status.sh','''set -euo pipefail
systemctl --user --no-pager status sky-eye sky-eye-objects || true
''')
    managed(ROOT/'run.sh','''set -euo pipefail
cd "$(dirname "$0")"
if systemctl --user is-active --quiet sky-eye || systemctl --user is-active --quiet sky-eye-objects; then
  echo 'Stop background service first: bash ~/sky-eye/stop.sh'; exit 1
fi
exec bash deploy/pi/edge.sh run "$@"
''')
    managed(ROOT/'run-objects.sh','''set -euo pipefail
cd "$(dirname "$0")"
exec bash run.sh --config deploy/pi/config.objects.json "$@"
''')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    print('Installed ~/sky-eye launch commands and user services; services not started by installer')

if __name__=='__main__':
    main()
