"""crawldir seguro (contrato C2).

O checkpoint do upstream é pickle: carregar um crawldir de terceiros executa código. O raspador cria o
diretório com 0700, recusa um existente de outro dono ou com escrita para grupo/outros, e trava com um
lockfile para dois processos não corromperem o mesmo checkpoint.
"""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Iterator
from pathlib import Path


class UnsafeCrawldir(Exception):
    code = "RSP-F001"

    def __init__(self, path: Path, why: str) -> None:
        self.path = path
        super().__init__(f"{self.code}: crawldir inseguro {path}: {why}. Use um diretório seu com permissão 0700.")


class CrawldirLocked(Exception):
    code = "RSP-F002"

    def __init__(self, path: Path, pid: int) -> None:
        self.path, self.pid = path, pid
        super().__init__(f"{self.code}: {path} está em uso pelo processo {pid}. Espere ele terminar.")


def secure_crawldir(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        p.mkdir(parents=True, mode=0o700)
        p.chmod(0o700)  # mkdir respeita a umask; garante o modo exato
        return p
    st = p.stat()
    if not stat.S_ISDIR(st.st_mode):
        raise UnsafeCrawldir(p, "não é diretório")
    if st.st_uid != os.getuid():
        raise UnsafeCrawldir(p, "pertence a outro usuário")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise UnsafeCrawldir(p, "tem escrita para grupo ou outros")
    return p


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, só não é nosso
    return True


@contextlib.contextmanager
def crawl_lock(crawldir: Path) -> Iterator[None]:
    lock = crawldir / ".lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid != os.getpid() and _alive(pid):
                raise CrawldirLocked(crawldir, pid) from None
            lock.unlink(missing_ok=True)  # lock órfão
    else:  # pragma: no cover - corrida improvável entre unlink e open
        raise CrawldirLocked(crawldir, -1)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)
