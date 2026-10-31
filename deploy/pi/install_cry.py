from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
MARKER='# Managed by sky-eye cry test installer\n'

def write(path,text):
    if path.exists() and not path.read_text().startswith(MARKER):
        raise FileExistsError('Existing unmanaged file: '+str(path))
    path.write_text(MARKER+text)

def main():
    unit=Path.home()/'.config/systemd/user/sky-eye-cry.service'
    unit.parent.mkdir(parents=True,exist_ok=True)
    root=str(ROOT).replace('%','%%')
    write(unit,f'''[Unit]
Description=Sky Eye microphone cry-presence test

[Service]
Type=simple
WorkingDirectory={root}
ExecStart=/bin/bash "{root}/deploy/pi/cry-edge.sh" live
Restart=on-failure
RestartSec=5
TimeoutStopSec=10
UMask=0077

[Install]
WantedBy=default.target
''')
    write(ROOT/'cry-start.sh','''set -euo pipefail
systemctl --user daemon-reload
systemctl --user start sky-eye-cry
systemctl --user --no-pager status sky-eye-cry
''')
    write(ROOT/'cry-stop.sh','''set -euo pipefail
systemctl --user daemon-reload
if test "$(systemctl --user show sky-eye-cry -p LoadState --value)" = loaded; then
  systemctl --user stop sky-eye-cry
fi
''')
    write(ROOT/'cry-watch.sh','''set -euo pipefail
cd "$(dirname "$0")"
exec bash deploy/pi/cry-edge.sh watch
''')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    print('Cry-presence test installed; boot auto-start is not enabled')

if __name__=='__main__':main()
