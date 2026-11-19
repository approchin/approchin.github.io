"""Recover the versioned, public page media from the repo's split asset archives."""
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import hashlib
import json

seen = set()
for item in json.loads(Path("assets-index.json").read_text()):
    path = Path(item["file"])
    assert path.name == str(path) and path.suffix == ".zip"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], path
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        entries = archive.infolist()
        assert len(entries) == item["entries"]
        for entry in entries:
            target = PurePosixPath(entry.filename)
            assert target.parts[0] == "assets" and ".." not in target.parts
            assert target not in seen and not entry.is_dir()
            assert (entry.external_attr >> 16) & 0o170000 != 0o120000
            seen.add(target)
            out = Path(*target.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(entry))
