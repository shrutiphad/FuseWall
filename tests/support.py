"""Workspace-scoped disposable directories; no platform temp ACL assumptions."""
import shutil
import uuid
from pathlib import Path


class WorkspaceDirectory:
    def __init__(self, dir=None):
        self.root = Path(dir or Path(__file__).resolve().parent.parent / 'test-results' / 'scratch').resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / ('case-' + uuid.uuid4().hex)
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self):
        if self.path.resolve().parent != self.root or not self.path.name.startswith('case-'):
            raise RuntimeError('Refusing to delete an unexpected test directory')
        if self.path.exists():
            shutil.rmtree(self.path)

    def __enter__(self): return self.name
    def __exit__(self, *args): self.cleanup()
