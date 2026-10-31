"""Install the exporter and optional unified launch commands without starting services."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
MARKER='# Managed by sky-eye integrated installer\n'

def managed(path,text):
    if path.exists() and not path.read_text().startswith(MARKER):raise FileExistsError(path)
    path.write_text(MARKER+text)

def main():
    folder=Path.home()/'.config/systemd/user'
    folder.mkdir(parents=True,exist_ok=True)
    root=str(ROOT).replace('%','%%')
    managed(folder/'sky-eye-export.service',f'''[Unit]
Description=Sky Eye stable model output files

[Service]
Type=simple
WorkingDirectory={root}
Environment=PYTHONPATH={root}/src
Environment=OPENBLAS_NUM_THREADS=1
ExecStart="{root}/.venv/bin/python" -m sky_edge.export
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
''')
    managed(ROOT/'start-all.sh','''set -euo pipefail
cd "$(dirname "$0")"
bash start.sh "${1:-baseline}"
bash cry-start.sh
systemctl --user start sky-eye-export
''')
    managed(ROOT/'stop-all.sh','''set -euo pipefail
cd "$(dirname "$0")"
bash stop.sh
bash cry-stop.sh
# Exporter stays up to mark stopped inputs unavailable.
''')
    managed(ROOT/'cry-cause-demo.sh','''set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" OPENBLAS_NUM_THREADS=1
exec .venv/bin/python -m sky_edge.personalization demo "$@"
''')
    managed(ROOT/'cry-feedback.sh','''set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" OPENBLAS_NUM_THREADS=1
exec .venv/bin/python -m sky_edge.personalization "$@"
''')
    if not (ROOT/'watch.sh').exists():
        managed(ROOT/'watch.sh','''set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m sky_edge.watch "$@"
''')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    print('Installed integrated launchers. No services started or enabled by installer.')

if __name__=='__main__':main()
