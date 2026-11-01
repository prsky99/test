"""Build outside the served tree and publish only completed files."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import tempfile


@contextmanager
def staged_publication(root):
    """Serialize publishers; a failed render never changes the served tree.

    File replacement is atomic, not a transaction across the complete bundle.
    Existing clients may briefly read different completed asset generations.
    """
    root = Path(root)
    # A stable inode is required: deleting this lock allows concurrent writers.
    descriptor = os.open(root / '.publication.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='.publication-', dir=root) as temporary:
            output = Path(temporary) / 'en'
            yield output
            files = sorted(p for p in output.rglob('*') if p.is_file())
            if any(p.is_symlink() for p in output.rglob('*')):
                raise ValueError('Publication must contain regular files.')
            index = output / 'index.html'
            if not index.is_file() or 'data-pearl-entry="overview"' not in index.read_text():
                raise ValueError('Completed operating entry is required.')
            manifest = output.parent / 'en-manifest.json'
            if not manifest.is_file():
                raise ValueError('Completed publication manifest is required.')
            # Publish completed assets before documents, and the entry last.
            files.sort(key=lambda p: (p == index, p.suffix == '.html', str(p)))
            for source in files:
                target = root / 'en' / source.relative_to(output)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
            os.replace(manifest, root / 'en-manifest.json')
