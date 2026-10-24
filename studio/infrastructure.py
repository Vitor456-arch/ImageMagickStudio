import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from .domain import CancelledError, check_cancel

LOG = logging.getLogger('studio')
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


class Magick:
    def __init__(self, executable: str = ''):
        candidates = [executable, shutil.which('magick')]
        candidates += [str(p) for p in Path(os.environ.get('ProgramFiles', 'C:/Program Files')).glob('ImageMagick*/magick.exe')]
        self.executable = next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), '')
        self.version = 'ImageMagick não encontrado'
        self.formats: set[str] = set()
        self.details = ''
        if self.executable:
            try:
                self.version = self.run(['-version']).splitlines()[0]
                self.details = self.run(['-list', 'format'])
                for line in self.details.splitlines():
                    match = re.match(r'\s*(\w+)\*?\s+\S+\s+([r-][w-][+-])', line)
                    if match and match[2][1] == 'w':
                        self.formats.add(match[1].lower())
                self.details += '\n' + self.run(['-list', 'delegate'])
            except (OSError, RuntimeError) as exc:
                self.details = str(exc)
                self.executable = ''

    def run(self, args: list[str], cancel: Event | None = None, timeout: int = 180, progress=None) -> str:
        if not self.executable:
            raise RuntimeError('ImageMagick 7 ausente. Indique magick.exe em Diagnóstico.')
        event = cancel or Event()
        check_cancel(event)
        limits = ['-limit', 'thread', '2', '-limit', 'memory', '512MiB', '-limit', 'map', '1GiB']
        if args[0] in {'-version', '-list'}:
            command = [self.executable, *map(str, args)]
        elif args[0] == 'identify':
            command = [self.executable, 'identify', *limits, *map(str, args[1:])]
        else:
            command = [self.executable, *limits, *map(str, args)]
        LOG.info('comando %s', json.dumps(command, ensure_ascii=False))
        # Arquivos temporários evitam deadlock quando stderr do ImageMagick fica cheio.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            with subprocess.Popen(command, shell=False, stdout=stdout, stderr=stderr, creationflags=FLAGS) as process:
                start = time.monotonic()
                while process.poll() is None:
                    if event.wait(.05) or time.monotonic() - start > timeout:
                        # taskkill encerra também delegates (Ghostscript etc.) no Windows.
                        if os.name == 'nt':
                            try:
                                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=FLAGS, timeout=5)
                            except (OSError, subprocess.TimeoutExpired):
                                LOG.warning('Não foi possível encerrar delegates pelo taskkill.', exc_info=True)
                        if process.poll() is None:
                            process.kill()
                        process.wait()
                        check_cancel(event)
                        raise RuntimeError(f'Tempo limite de {timeout}s excedido.')
                stdout.seek(0)
                stderr.seek(0)
                out = stdout.read().decode('utf-8', errors='replace')
                error = stderr.read().decode('utf-8', errors='replace')
                check_cancel(event)
                if process.returncode:
                    raise RuntimeError(error.strip() or f'ImageMagick terminou com código {process.returncode}.')
                return out


def safe_name(value: str) -> str:
    result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip().rstrip('. ')[:160] or 'imagem'
    if result.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        result = '_' + result
    return result


class OutputStore:
    def __init__(self, folder: Path, originals: list[Path], policy: str):
        self.folder = folder.resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.originals = {p.resolve() for p in originals}
        self.policy = policy
        self.reserved: set[Path] = set()
        from threading import Lock
        self.lock = Lock()

    def reserve(self, name: str) -> Path | None:
        with self.lock:
            extension = re.sub(r'[^.a-zA-Z0-9]', '_', Path(name).suffix)
            target = self.folder / (safe_name(Path(name).stem) + extension if extension else safe_name(name))
            if target.resolve() in self.originals:
                raise ValueError('A saída coincide com um arquivo original. Escolha outra pasta ou sufixo.')
            if target.exists() or target in self.reserved:
                if self.policy == 'ignorar':
                    return None
                if self.policy == 'perguntar':
                    raise FileExistsError(f'Conflito precisa de confirmação: {target.name}')
                if self.policy == 'renomear' or target in self.reserved:
                    base, index = target, 2
                    while target.exists() or target in self.reserved:
                        target = base.with_name(f'{base.stem} ({index}){base.suffix}')
                        index += 1
            self.reserved.add(target)
            return target

    @contextmanager
    def atomic(self, target: Path, cancel: Event):
        handle, filename = tempfile.mkstemp(prefix='.studio-', suffix=target.suffix, dir=self.folder)
        os.close(handle)
        temporary = Path(filename)
        try:
            check_cancel(cancel)
            yield temporary
            check_cancel(cancel)
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError('O processamento não produziu um arquivo válido.')
            if self.policy == 'substituir':
                os.replace(temporary, target)
            else:
                # rename no Windows não substitui um arquivo surgido durante o lote.
                if os.name == 'nt':
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
                    temporary.unlink()
        finally:
            temporary.unlink(missing_ok=True)


def config_dir() -> Path:
    folder = Path(os.environ.get('APPDATA', str(Path.home()))) / 'ImageMagickStudio'
    folder.mkdir(parents=True, exist_ok=True)
    return folder
