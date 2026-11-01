"""Keep financial records, account hashes and platform credentials owner-readable."""
import os
import errno
import stat
import threading


_creation_lock = threading.Lock()


def _restrict_existing_file(path):
    """Change permissions without opening an existing SQLite file descriptor.

    On POSIX, closing even an unrelated descriptor for an open database inode
    releases the process's SQLite advisory locks. SQLite owns those descriptors.
    """
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(errno.EINVAL, 'SQLite storage must be a regular file', path)
    os.chmod(path, 0o600, follow_symlinks=False)


def private_sqlite_file(path):
    if str(path) == ':memory:':
        return
    path = os.fspath(path)
    # Only a brand-new file may be opened here. Serialize helper callers so no
    # SQLite connection can open it before this initial descriptor is closed.
    with _creation_lock:
        try:
            _restrict_existing_file(path)
        except FileNotFoundError:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                _restrict_existing_file(path)
            else:
                os.close(fd)
    for suffix in ('-wal', '-shm'):
        try:
            _restrict_existing_file(path + suffix)
        except FileNotFoundError:
            continue
