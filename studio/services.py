import csv
import io
import json
import logging
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Callable

from PIL import Image, ImageOps, UnidentifiedImageError

from .domain import Options, Result, CancelledError, check_cancel, page_indices
from .infrastructure import Magick, OutputStore, safe_name
from .pipeline import command

LOG = logging.getLogger('studio')
MAX_PIXELS = 100_000_000
MAX_ITEMS = 10000
GROUPED = {'imagens_pdf', 'mesclar_pdf', 'criar_gif', 'horizontal', 'vertical', 'grade', 'sobrepor'}


def image_info(path: Path) -> dict:
    if path.suffix.lower() == '.pdf':
        import pymupdf
        with pymupdf.open(path) as doc:
            return {'format': 'PDF', 'width': round(doc[0].rect.width), 'height': round(doc[0].rect.height), 'frames': len(doc), 'mode': 'páginas', 'gps': False}
    with Image.open(path) as im:
        return {'format': im.format, 'width': im.width, 'height': im.height, 'frames': getattr(im, 'n_frames', 1), 'mode': im.mode, 'gps': bool(im.getexif().get(34853)), 'alpha': 'A' in im.mode or 'transparency' in im.info}


def validate_source(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f'Arquivo não encontrado: {path}')
    if path.stat().st_size == 0:
        raise ValueError(f'Arquivo vazio: {path.name}')


def validate_image(magick: Magick, path: Path, cancel: Event, options: Options | None = None):
    result = magick.run(['identify', '-ping', '-format', '%w %h %[orientation]', str(path) + '[0]'], cancel)
    parts = result.strip().split()
    width, height = map(int, parts[:2])
    if width * height > MAX_PIXELS:
        raise ValueError('Imagem acima do limite de 100 megapixels.')
    if options is None:
        return
    o=options
    if o.auto_orient and len(parts)>2 and parts[2] in {'LeftTop','RightTop','RightBottom','LeftBottom'}:
        width,height=height,width
    if o.crop:
        if o.crop_ratio!='livre':
            x,y=map(int,o.crop_ratio.split(':'))
            width,height=min(width,height*x/y),min(height,width*y/x)
        else:
            width,height=min(width,o.crop_width),min(height,o.crop_height)
    if o.resize=='largura':
        width,height=o.width,height*o.width/width
    elif o.resize=='altura':
        width,height=width*o.height/height,o.height
    elif o.resize=='percentual':
        width,height=width*o.percent/100,height*o.percent/100
    elif o.resize in {'forcar','preencher'}:
        width,height=o.width,o.height
    elif o.resize in {'ajustar','reduzir'}:
        scale=min(o.width/width,o.height/height,1 if o.resize=='reduzir' else float('inf'))
        width,height=width*scale,height*scale
    if o.angle:
        angle=math.radians(o.angle)
        width,height=abs(width*math.cos(angle))+abs(height*math.sin(angle)),abs(width*math.sin(angle))+abs(height*math.cos(angle))
    if math.ceil(width)*math.ceil(height)>MAX_PIXELS:
        raise ValueError('A transformação solicitada excede o limite de 100 megapixels.')


def output_basename(path: Path, o: Options, index: int) -> str:
    return safe_name(f'{o.prefix}{index + 1:04d}_' + path.stem + o.suffix) if o.numbered else safe_name(o.prefix + path.stem + o.suffix)


def output_one(store: OutputStore, name: str, event: Event, producer: Callable[[Path], None], validator=None) -> str | None:
    target = store.reserve(name)
    if target is None:
        return None
    with store.atomic(target, event) as temporary:
        producer(temporary)
        if validator:
            validator(temporary)
    return str(target)


class Processor:
    def __init__(self, magick: Magick):
        self.magick = magick

    def one(self, source: Path, index: int, o: Options, store: OutputStore, event: Event, progress=None) -> Result:
        outputs: list[str] = []
        try:
            check_cancel(event)
            validate_source(source)
            base = output_basename(source, o, index)
            if o.operation in {'pdf_imagens', 'dividir_pdf', 'reordenar_pdf'}:
                outputs = self.pdf_task(source, base, o, store, event, outputs)
            elif o.operation == 'extrair_gif':
                with Image.open(source) as gif:
                    if gif.n_frames > MAX_ITEMS:
                        raise ValueError('Animação excede o limite de quadros.')
                    for frame in range(gif.n_frames):
                        check_cancel(event)
                        gif.seek(frame)
                        image = gif.convert('RGBA')
                        result = output_one(store, f'{base}_{frame + 1:04d}.png', event, lambda p, im=image: im.save(p))
                        if result:
                            outputs.append(result)
            elif o.format == 'pdf':
                outputs = self.images_pdf([source], base, o, store, event)
            else:
                validate_image(self.magick, source, event, o)
                if progress:
                    progress(1)
                def produce(path):
                    self.magick.run(command(source, path, o), event)
                    if progress:
                        progress(2)
                def verify(path):
                    validate_image(self.magick, path, event)
                    if progress:
                        progress(3)
                result = output_one(store, base + '.' + o.format, event,
                                    produce, verify)
                if result:
                    outputs.append(result)
            if progress:
                progress(100)
            return Result(str(source), 'concluído' if outputs else 'ignorado', outputs)
        except CancelledError as exc:
            return Result(str(source), 'cancelado', outputs, str(exc))
        except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as exc:
            LOG.exception('falha arquivo=%s', source)
            return Result(str(source), 'falhou', outputs, str(exc))

    def pdf_task(self, source: Path, base: str, o: Options, store: OutputStore, event: Event, outputs: list[str] | None = None) -> list[str]:
        from pypdf import PdfReader, PdfWriter
        from pypdf.errors import PyPdfError
        import pymupdf
        outputs = [] if outputs is None else outputs
        try:
            reader = PdfReader(source)
            if reader.is_encrypted:
                raise ValueError('PDF protegido por senha não é suportado nesta versão.')
            indices = page_indices(o.pages, len(reader.pages))
            if o.operation == 'reordenar_pdf':
                writer = PdfWriter()
                for i in indices:
                    check_cancel(event)
                    writer.add_page(reader.pages[i])
                result = output_one(store, base + '.pdf', event, lambda p: writer.write(p), self.validate_pdf)
                return [result] if result else []
            if o.operation == 'dividir_pdf':
                for i, page in enumerate(indices):
                    check_cancel(event)
                    writer = PdfWriter()
                    writer.add_page(reader.pages[page])
                    result = output_one(store, f'{base}_{i + 1:04d}.pdf', event, lambda p, w=writer: w.write(p), self.validate_pdf)
                    if result:
                        outputs.append(result)
            else:
                with pymupdf.open(source) as doc:
                    for i, page in enumerate(indices):
                        check_cancel(event)
                        rect = doc[page].rect
                        if rect.width * rect.height * (o.dpi / 72) ** 2 > MAX_PIXELS:
                            raise ValueError('DPI solicitado ultrapassa o limite de pixels por página.')
                        pix = doc[page].get_pixmap(dpi=o.dpi, alpha=True)
                        with tempfile.TemporaryDirectory() as folder:
                            intermediate = Path(folder) / 'pagina.png'
                            pix.save(intermediate)
                            result = output_one(store, f'{base}_{i + 1:04d}.{o.format}', event,
                                                lambda p: self.magick.run(command(intermediate, p, o), event),
                                                lambda p: validate_image(self.magick, p, event))
                            if result:
                                outputs.append(result)
        except PyPdfError as exc:
            raise ValueError(f'PDF inválido: {exc}') from exc
        return outputs

    @staticmethod
    def validate_pdf(path: Path):
        from pypdf import PdfReader
        if not len(PdfReader(path).pages):
            raise ValueError('O PDF gerado não possui páginas.')

    def transformed(self, source: Path, temporary: Path, o: Options, event: Event):
        validate_source(source)
        validate_image(self.magick, source, event, o)
        self.magick.run(command(source, temporary, replace(o, format='png')), event)

    def images_pdf(self, sources: list[Path], base: str, o: Options, store: OutputStore, event: Event) -> list[str]:
        import pymupdf
        document = pymupdf.open()
        try:
            with tempfile.TemporaryDirectory() as folder:
                for i, source in enumerate(sources):
                    check_cancel(event)
                    transformed = Path(folder) / f'{i}.png'
                    self.transformed(source, transformed, o, event)
                    with Image.open(transformed) as im:
                        image_width, image_height = im.size
                    sizes = {'A4': (595.276, 841.89), 'A3': (841.89, 1190.55), 'Carta': (612, 792)}
                    width, height = sizes.get(o.page_size, (image_width * 72 / o.dpi, image_height * 72 / o.dpi))
                    if o.landscape and width < height:
                        width, height = height, width
                    margin = o.page_margin * 72 / 25.4
                    if o.page_size == 'Original':
                        width += 2 * margin
                        height += 2 * margin
                    if 2 * margin >= min(width, height):
                        raise ValueError('Margens maiores do que a página.')
                    page = document.new_page(width=width, height=height)
                    available = pymupdf.Rect(margin, margin, width - margin, height - margin)
                    if o.page_fit == 'original':
                        w, h = image_width * 72 / o.dpi, image_height * 72 / o.dpi
                        available = pymupdf.Rect((width-w)/2, (height-h)/2, (width+w)/2, (height+h)/2)
                    if o.page_fit == 'preencher':
                        with Image.open(transformed) as im:
                            ratio = available.width / available.height
                            crop_w, crop_h = min(im.width, round(im.height * ratio)), min(im.height, round(im.width / ratio))
                            im = im.crop(((im.width-crop_w)//2, (im.height-crop_h)//2, (im.width+crop_w)//2, (im.height+crop_h)//2))
                            im.save(transformed)
                    page.insert_image(available, filename=str(transformed), keep_proportion=o.page_fit != 'preencher')
                result = output_one(store, base + '.pdf', event, lambda p: document.save(str(p), garbage=4, deflate=True), self.validate_pdf)
            return [result] if result else []
        finally:
            document.close()

    def group(self, sources: list[Path], o: Options, store: OutputStore, event: Event) -> Result:
        outputs = []
        try:
            for source in sources:
                validate_source(source)
            check_cancel(event)
            base = safe_name(o.prefix + o.output_name + o.suffix)
            if o.operation == 'mesclar_pdf':
                from pypdf import PdfWriter
                from pypdf.errors import PyPdfError
                writer = PdfWriter()
                try:
                    for source in sources:
                        check_cancel(event)
                        writer.append(source)
                    result = output_one(store, base + '.pdf', event, lambda p: writer.write(p), self.validate_pdf)
                except PyPdfError as exc:
                    raise ValueError(f'Falha ao mesclar PDF: {exc}') from exc
                finally:
                    writer.close()
                outputs = [result] if result else []
            elif o.operation == 'imagens_pdf':
                outputs = self.images_pdf(sources, base, o, store, event)
            else:
                with tempfile.TemporaryDirectory() as folder:
                    processed = []
                    for index, source in enumerate(sources):
                        check_cancel(event)
                        path = Path(folder) / f'{index}.png'
                        self.transformed(source, path, o, event)
                        processed.append(path)
                    if o.operation == 'criar_gif':
                        frames = []
                        durations = [int(v.strip()) for v in o.frame_delays.split(',')] if o.frame_delays.strip() else [o.delay] * len(processed)
                        if len(durations) != len(processed) or any(d < 10 for d in durations):
                            raise ValueError('Informe uma duração em ms (mínimo 10) para cada quadro.')
                        if o.width * o.height * len(processed) > MAX_PIXELS:
                            raise ValueError('GIF excede o limite total de 100 milhões de pixels.')
                        for path in processed:
                            with Image.open(path) as im:
                                im = im.convert('RGBA')
                                size = (o.width, o.height)
                                if o.gif_fit == 'preencher':
                                    frame = ImageOps.fit(im, size, method=Image.Resampling.LANCZOS)
                                else:
                                    im.thumbnail(size, Image.Resampling.LANCZOS)
                                    frame = Image.new('RGBA', size, o.background)
                                    frame.alpha_composite(im, ((size[0]-im.width)//2, (size[1]-im.height)//2))
                                frames.append(frame)
                        def save_gif(p):
                            frames[0].save(p, save_all=True, append_images=frames[1:], duration=durations, loop=o.loops, optimize=o.optimize, disposal=2)
                        result = output_one(store, base + '.gif', event, save_gif, lambda p: validate_image(self.magick, p, event))
                    else:
                        result = self.compose(processed, base, o, store, event)
                    outputs = [result] if result else []
            return Result('Conjunto de arquivos', 'concluído' if outputs else 'ignorado', outputs)
        except CancelledError as exc:
            return Result('Conjunto de arquivos', 'cancelado', outputs, str(exc))
        except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as exc:
            LOG.exception('falha na operação conjunta')
            return Result('Conjunto de arquivos', 'falhou', outputs, str(exc))

    def compose(self, files: list[Path], base: str, o: Options, store: OutputStore, event: Event) -> str | None:
        images = []
        try:
            for p in files:
                check_cancel(event)
                with Image.open(p) as im:
                    images.append(im.convert('RGBA'))
            if o.operation == 'sobrepor':
                width, height = images[0].size
            elif o.operation == 'horizontal':
                width = sum(im.width for im in images) + o.spacing * (len(images)-1)
                height = max(im.height for im in images)
            elif o.operation == 'vertical':
                width = max(im.width for im in images)
                height = sum(im.height for im in images) + o.spacing * (len(images)-1)
            else:
                cell_width, cell_height = max(im.width for im in images), max(im.height for im in images)
                cols = min(o.columns, len(images))
                rows = math.ceil(len(images) / cols)
                width, height = cols * cell_width + (cols-1) * o.spacing, rows * cell_height + (rows-1) * o.spacing
            if width * height > MAX_PIXELS:
                raise ValueError('Composição excede o limite de 100 megapixels.')
            canvas = Image.new('RGBA', (width, height), o.canvas)
            x = y = 0
            for index, im in enumerate(images):
                check_cancel(event)
                if o.operation == 'sobrepor':
                    if index:
                        im.putalpha(im.getchannel('A').point(lambda a: int(a * o.opacity / 100)))
                    canvas.alpha_composite(im, (0, 0) if index == 0 else (o.overlay_x, o.overlay_y))
                elif o.operation == 'grade':
                    canvas.alpha_composite(im, ((index % cols)*(cell_width+o.spacing) + (cell_width-im.width)//2, (index//cols)*(cell_height+o.spacing) + (cell_height-im.height)//2))
                else:
                    canvas.alpha_composite(im, (x, y))
                    if o.operation == 'horizontal':
                        x += im.width + o.spacing
                    else:
                        y += im.height + o.spacing
            with tempfile.TemporaryDirectory() as folder:
                temporary = Path(folder) / 'canvas.png'
                canvas.save(temporary)
                # A pipeline já foi aplicada a cada imagem; apenas codifica o canvas.
                final = Options(format=o.format, quality=o.quality, background=o.background, strip=o.strip, keep_icc=o.keep_icc)
                return output_one(store, base + '.' + o.format, event, lambda p: self.magick.run(command(temporary, p, final), event), lambda p: validate_image(self.magick, p, event))
        finally:
            for im in images:
                im.close()


def run_batch(processor: Processor, sources: list[Path], output: Path, o: Options, event: Event, update=None, file_progress=None) -> list[Result]:
    if len(sources) > MAX_ITEMS:
        raise ValueError('O lote excede o limite de 10.000 arquivos.')
    store = OutputStore(output, sources, o.conflict)
    if o.operation in GROUPED:
        if update:
            for i in range(len(sources)):
                update(i, 'processando', None)
        result = processor.group(sources, o, store, event)
        if update:
            for i in range(len(sources)):
                update(i, result.state, result)
        return [result]
    results: list[Result | None] = [None] * len(sources)
    with ThreadPoolExecutor(max_workers=max(1, min(8, o.parallelism))) as pool:
        def work(index: int, path: Path):
            if update:
                update(index, 'processando' if not event.is_set() else 'cancelado', None)
            return processor.one(path, index, o, store, event, lambda value: file_progress(index, value) if file_progress else None)
        futures = {pool.submit(work, i, path): i for i, path in enumerate(sources)}
        for future in as_completed(futures):
            index = futures[future]
            result = future.result()
            results[index] = result
            if update:
                update(index, result.state, result)
    return [r for r in results if r is not None]


def export_report(path: Path, results: list[Result]):
    if path.suffix.lower() == '.csv':
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['source', 'state', 'outputs', 'error'])
            writer.writeheader()
            writer.writerows(r.dictionary() for r in results)
    else:
        path.write_text(json.dumps([r.dictionary() for r in results], ensure_ascii=False, indent=2), encoding='utf-8')
