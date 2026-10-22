"""Create a portable source/evidence archive without runtime data or secrets."""
import hashlib
import argparse
import json
import os
import tomllib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
version = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf8'))['project']['version']
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root/'dist'/f'fusewall-local-v{version}.zip')
target = parser.parse_args().output.resolve()
target.parent.mkdir(parents=True,exist_ok=True)
excluded = {'.fusewall','.venv','test-results','__pycache__','.git','dist'}
manifest = []
payload = []
for folder, directories, files in os.walk(root):
    directories[:] = sorted(d for d in directories if d not in excluded and not d.endswith('.egg-info'))
    for name in sorted(files):
        path = Path(folder)/name
        relative = path.relative_to(root)
        if (path.resolve() == target or path.is_symlink() or name.startswith('.env')
                or name.endswith(('.pyc','.db','.db-wal','.db-shm','.zip'))
                or name in ('RELEASE-MANIFEST.json','admin-token.txt','fingerprint.key','test-results-unittest.log')):
            continue
        data = path.read_bytes()
        payload.append((relative.as_posix(),data))
        manifest.append({'file':relative.as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
manifest_bytes = json.dumps(manifest,indent=2).encode('utf8')
(root/'RELEASE-MANIFEST.json').write_bytes(manifest_bytes)
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for relative,data in payload:
        archive.writestr('fusewall/'+relative,data)
    archive.writestr('fusewall/RELEASE-MANIFEST.json',manifest_bytes)
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert not any('/.fusewall/' in n or n.endswith('.db') or '/test-results/' in n for n in archive.namelist())
    assert len(archive.namelist()) == len(set(archive.namelist())) == len(manifest)+1
    for item in manifest:
        assert hashlib.sha256(archive.read('fusewall/'+item['file'])).hexdigest() == item['sha256']
print(json.dumps({'archive':str(target),'files':len(manifest),'bytes':target.stat().st_size,
                  'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'runtime_data_included':False},indent=2))
