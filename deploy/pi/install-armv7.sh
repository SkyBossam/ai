#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
test "$(uname -m)" = armv7l
python3 - <<'PY'
import sys
from pathlib import Path
assert sys.version_info[:2]==(3,9), 'This wheel profile targets Bullseye Python 3.9.'
assert 'VERSION_CODENAME=bullseye' in Path('/etc/os-release').read_text(), 'This wheel profile targets Bullseye.'
PY
test ! -e .venv || { echo '.venv exists; use this release or extract a fresh release.'; exit 1; }
sudo apt-get update
packages=$(python3 - <<'PY'
import json
from pathlib import Path
config=json.loads(Path('deploy/pi/config.json').read_text())
profile='armv7-wheel-plan-ncnn.json'
p=json.loads((Path('deploy/pi')/profile).read_text())
print(' '.join(sorted(set(['python3-venv','libgomp1']+[d for fs in p.values() for v in fs.values() for d in v['apt_dependencies']]))))
PY
)
sudo apt-get install -y --no-upgrade $packages
python3 -m venv .venv
.venv/bin/python - <<'PY'
from pathlib import Path
import json,hashlib,urllib.request
config=json.loads(Path('deploy/pi/config.json').read_text())
profile='armv7-wheel-plan-ncnn.json'
plan=json.loads((Path('deploy/pi')/profile).read_text())
out=Path('wheelhouse');out.mkdir(exist_ok=True)
for files in plan.values():
 for name,item in files.items():
  path=out/name
  if not path.exists():
   urllib.request.urlretrieve('https://www.piwheels.org'+item['file_url'],path)
  assert hashlib.sha256(path.read_bytes()).hexdigest()==item['filehash'],name
PY
.venv/bin/python -m pip install --only-binary=:all: --find-links wheelhouse -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m pip freeze > runtime-installed.txt
.venv/bin/python - <<'PY'
from pathlib import Path
import json
for path in Path('deploy/pi').glob('config*.json'):
    config=json.loads(path.read_text())
    if config.get('inference_backend')!='ncnn':
        config['inference_backend']='opencv'
    path.write_text(json.dumps(config,indent=2)+'\n')
PY
bash deploy/pi/edge.sh check
echo 'Installed ARMv7 USB camera profile.'
