"""Stage an offline Windows owner installation from a tested Git commit."""

import argparse
from contextlib import closing, contextmanager
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import tempfile


@contextmanager
def offline_source(source, port):
    import msvcrt

    lock_path = source / ".admin.lock"
    # Legacy installs normally have this lock. A missing lock still requires
    # the caller to verify that all previous workers have been stopped.
    with socket.socket() as port_check:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            port_check.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        port_check.bind(("127.0.0.1", port))
        if not lock_path.exists():
            yield
            return
        with lock_path.open("r+b") as lock:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def backup_state(source, backup):
    original = source / "server/gold_ai_server.db"
    if not original.is_file() or not (source / ".env").is_file():
        raise ValueError("Select the existing owner home containing its database and .env.")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source / ".env", backup / ".env")
    saved_state = backup / "server"
    saved_state.mkdir()
    for name in ("personal_account.json", "workspace_settings.json", "credential_vault.key"):
        file = source / "server" / name
        if file.is_file():
            shutil.copy2(file, saved_state / name)
    for name in ("hosted_mt5", "hosted_logs"):
        directory = source / "server" / name
        if directory.is_dir():
            shutil.copytree(directory, saved_state / name)
    with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as legacy:
        with closing(sqlite3.connect(backup / "server/gold_ai_server.db")) as snapshot:
            legacy.backup(snapshot)
            if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("SQLite backup failed its integrity check.")
    if (source / "logs").is_dir():
        shutil.copytree(source / "logs", backup / "logs")


def install_files(staged, target):
    files = [path.relative_to(staged) for path in staged.rglob("*") if path.is_file()]
    for relative in files:
        destination = target / relative
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Installation would overwrite {relative}.")
        for parent in relative.parents:
            directory = target / parent
            if directory.is_symlink() or directory.is_junction() or (directory.exists() and not directory.is_dir()):
                raise ValueError(f"Invalid installation directory: {parent}")
    created = []
    try:
        for relative in files:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with (staged / relative).open("rb") as source, destination.open("xb") as output:
                created.append(destination)
                shutil.copyfileobj(source, output)
    except Exception:
        for destination in reversed(created):
            destination.unlink(missing_ok=True)
        raise


def prepare(repo, revision, source, target, backup, executable, port):
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Owner source and target must be separate directories.")
    if any(backup.is_relative_to(root) for root in (source, target, repo)):
        raise ValueError("Choose a backup directory outside the source, checkout and target.")
    if not executable.is_file() or executable.name.lower() != "azt_admin.exe":
        raise ValueError("Select the tested AZT_Admin.exe.")
    with tempfile.TemporaryDirectory(prefix="azt-install-") as folder:
        folder = Path(folder)
        archive = folder / "owner.tar"
        staged = folder / "installation"
        subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), revision],
                       cwd=repo, check=True)
        with tarfile.open(archive) as code:
            code.extractall(staged, filter="data")
        with offline_source(source, port):
            backup_state(source, backup)
            shutil.copy2(backup / ".env", staged / ".env")
            shutil.copytree(backup / "server", staged / "server", dirs_exist_ok=True)
            shutil.copy2(executable, staged / "AZT_Admin.exe")
            install_files(staged, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--revision", default="HEAD")
    for name in ("source", "target", "backup", "exe"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    prepare(args.repo.resolve(), args.revision, args.source.resolve(), args.target.resolve(),
            args.backup.resolve(), args.exe.resolve(), args.port)
    print(f"Prepared {args.target}. Verified SQLite backup: {args.backup}")


if __name__ == "__main__":
    main()
