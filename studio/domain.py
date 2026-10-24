from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Event


class CancelledError(RuntimeError):
    pass


@dataclass
class Options:
    operation: str = 'converter'
    format: str = 'png'
    quality: int = 90
    preserve_frames: bool = False
    background: str = '#ffffff'
    flatten: bool = False
    auto_orient: bool = True
    strip: bool = True
    keep_icc: bool = True
    resize: str = 'nenhum'
    width: int = 1920
    height: int = 1080
    percent: float = 50
    interpolation: str = 'Lanczos'
    crop: bool = False
    crop_x: int = 0
    crop_y: int = 0
    crop_width: int = 500
    crop_height: int = 500
    crop_center: bool = False
    crop_ratio: str = 'livre'
    angle: float = 0
    horizontal: bool = False
    vertical: bool = False
    brightness: float = 0
    contrast: float = 0
    saturation: float = 100
    hue: float = 0
    temperature: float = 0
    gamma: float = 1
    exposure: float = 0
    auto_level: bool = False
    auto_contrast: bool = False
    normalize: bool = False
    grayscale: bool = False
    sepia: float = 0
    negative: bool = False
    effect: str = 'nenhum'
    radius: float = 1
    strength: float = 1
    threshold: float = 0.05
    remove_color: bool = False
    transparent_color: str = '#ffffff'
    tolerance: float = 5
    trim: bool = False
    watermark: str = ''
    watermark_image: str = ''
    font: str = 'Arial'
    font_size: int = 32
    watermark_color: str = '#ffffff'
    opacity: float = 50
    gravity: str = 'SouthEast'
    margin: int = 20
    overlay_x: int = 0
    overlay_y: int = 0
    watermark_scale: int = 25
    ico_sizes: str = '16,24,32,48,64,128,256'
    conflict: str = 'renomear'
    prefix: str = ''
    suffix: str = ''
    numbered: bool = False
    parallelism: int = 2
    dpi: int = 144
    pages: str = ''
    page_size: str = 'A4'
    landscape: bool = False
    page_margin: float = 10
    page_fit: str = 'ajustar'
    delay: int = 100
    frame_delays: str = ''
    loops: int = 0
    gif_fit: str = 'ajustar'
    optimize: bool = True
    columns: int = 3
    spacing: int = 16
    canvas: str = '#20232b'
    output_name: str = 'composicao'


@dataclass
class Result:
    source: str
    state: str
    outputs: list[str] = field(default_factory=list)
    error: str = ''

    def dictionary(self):
        return asdict(self)


def check_cancel(event: Event):
    if event.is_set():
        raise CancelledError('Processamento cancelado.')


def page_indices(text: str, count: int) -> list[int]:
    if not text.strip():
        return list(range(count))
    result = []
    for token in text.split(','):
        parts = token.strip().split('-')
        if len(parts) == 1:
            values = [int(parts[0])]
        elif len(parts) == 2:
            start, end = map(int, parts)
            values = range(start, end + (1 if start <= end else -1), 1 if start <= end else -1)
        else:
            raise ValueError('Use páginas como 1,3-5 ou 5-1.')
        for value in values:
            if not 1 <= value <= count:
                raise ValueError(f'Página {value} fora do intervalo 1–{count}.')
            result.append(value - 1)
    return result
