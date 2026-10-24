from pathlib import Path
from .domain import Options


def operations(o: Options) -> list[str]:
    a: list[str] = []
    if o.auto_orient:
        a += ['-auto-orient']
    if o.crop:
        if o.crop_center:
            a += ['-gravity', 'center']
        if o.crop_ratio != 'livre':
            x, y = map(int, o.crop_ratio.split(':'))
            # Percentual calculado pelo próprio ImageMagick nas dimensões originais.
            a += ['-set', 'option:cropw', f'%[fx:min(w,h*{x}/{y})]', '-set', 'option:croph', f'%[fx:min(h,w*{y}/{x})]', '-gravity', 'center', '-crop', '%[cropw]x%[croph]+0+0', '+repage']
        else:
            a += ['-crop', f'{o.crop_width}x{o.crop_height}+{0 if o.crop_center else o.crop_x}+{0 if o.crop_center else o.crop_y}', '+repage']
        a += ['-gravity', 'NorthWest']
    a += ['-filter', o.interpolation]
    geometry = f'{o.width}x{o.height}'
    modes = {'largura': f'{o.width}x', 'altura': f'x{o.height}', 'percentual': f'{o.percent}%', 'ajustar': geometry, 'forcar': geometry + '!', 'reduzir': geometry + '>'}
    if o.resize in modes:
        a += ['-resize', modes[o.resize]]
    elif o.resize == 'preencher':
        a += ['-resize', geometry + '^', '-gravity', 'center', '-extent', geometry, '-gravity', 'NorthWest']
    a += ['-background', o.background]
    if o.angle:
        a += ['-rotate', str(o.angle)]
    if o.horizontal:
        a += ['-flop']
    if o.vertical:
        a += ['-flip']
    if o.brightness or o.contrast:
        a += ['-brightness-contrast', f'{o.brightness}x{o.contrast}']
    if o.saturation != 100 or o.hue:
        a += ['-modulate', f'100,{o.saturation},{100 + o.hue / 1.8}']
    if o.temperature:
        t = o.temperature / 100
        a += ['-channel', 'R', '-evaluate', 'Multiply', str(1 + t * .25), '-channel', 'B', '-evaluate', 'Multiply', str(1 - t * .25), '+channel']
    if o.gamma != 1:
        a += ['-gamma', str(o.gamma)]
    if o.exposure:
        a += ['-channel', 'RGB', '-evaluate', 'Multiply', str(2 ** o.exposure), '+channel']
    for flag, command in [(o.auto_level, '-auto-level'), (o.auto_contrast, '-contrast-stretch'), (o.normalize, '-normalize'), (o.grayscale, '-colorspace')]:
        if flag:
            a += [command] + (['0.5%'] if command == '-contrast-stretch' else ['Gray'] if command == '-colorspace' else [])
    if o.sepia:
        a += ['(', '+clone', '-sepia-tone', '80%', ')', '-define', f'compose:args={o.sepia}', '-compose', 'blend', '-composite']
    if o.negative:
        a += ['-negate']
    r, s = str(o.radius), str(o.strength)
    effects = {
        'desfoque': ['-gaussian-blur', f'{r}x{s}'], 'nitidez': ['-sharpen', f'{r}x{s}'],
        'unsharp': ['-unsharp', f'{r}x{s}+{s}+{o.threshold}'], 'ruido': ['-despeckle'],
        'mediana': ['-statistic', 'Median', f'{max(1, int(o.radius))}x{max(1, int(o.radius))}'],
        'carvao': ['-charcoal', r], 'oleo': ['-paint', r], 'bordas': ['-edge', r], 'relevo': ['-emboss', r],
        'posterizar': ['-posterize', str(max(2, int(o.radius)))], 'limiar': ['-threshold', f'{o.strength}%'],
        'vinheta': ['-vignette', f'0x{max(1, o.radius)}'],
        'pixelizar': ['-set', 'option:original', '%wx%h', '-sample', f'{100 / max(1, o.radius)}%', '-sample', '%[original]!'],
    }
    a += effects.get(o.effect, [])
    if o.remove_color:
        a += ['-alpha', 'set', '-fuzz', f'{o.tolerance}%', '-transparent', o.transparent_color]
    if o.trim:
        a += ['-trim', '+repage']
    if o.watermark_image:
        p = Path(o.watermark_image).resolve()
        if not p.is_file():
            raise FileNotFoundError(f'Marca-d’água não encontrada: {p}')
        a += ['(', str(p) + '[0]', '-resize', f'{o.watermark_scale}%', '-alpha', 'set', '-channel', 'A', '-evaluate', 'Multiply', str(o.opacity / 100), '+channel', ')', '-gravity', o.gravity, '-geometry', f'+{o.overlay_x}+{o.overlay_y}', '-compose', 'Over', '-composite']
    if o.watermark:
        # annotate interpreta @ como arquivo; impede leitura indireta.
        if o.watermark.startswith('@'):
            raise ValueError('O texto da marca-d’água não pode começar com @.')
        from PIL import ImageColor
        red, green, blue = ImageColor.getrgb(o.watermark_color)
        a += ['-font', o.font, '-pointsize', str(o.font_size), '-gravity', o.gravity, '-fill', f'rgba({red},{green},{blue},{o.opacity / 100})', '-annotate', f'+{o.margin}+{o.margin}', o.watermark]
    if o.flatten or o.format in {'jpg', 'jpeg', 'bmp'}:
        a += ['-background', o.background, '-alpha', 'remove', '-alpha', 'off']
    if o.strip:
        if o.keep_icc:
            a += ['+profile', '!icc,*', '+set', 'comment', '+set', 'label', '+set', 'date:create', '+set', 'date:modify', '-define', 'png:exclude-chunks=date']
        else:
            a += ['-strip']
    return a


def command(source: Path, destination: Path, o: Options, preview: bool = False) -> list[str]:
    if o.resize in {'ajustar','preencher','forcar','reduzir'} and o.width * o.height > 100_000_000:
        raise ValueError('As dimensões solicitadas excedem o limite de 100 megapixels.')
    if o.crop and o.crop_width * o.crop_height > 100_000_000:
        raise ValueError('O recorte solicitado excede o limite de 100 megapixels.')
    # Leitura de quadros é explícita: conversão raster usa somente o primeiro.
    preserve = o.preserve_frames and not preview
    if preserve and o.format not in {'gif','webp','tiff'}:
        raise ValueError('Preservação de quadros/páginas requer GIF, WEBP ou TIFF como saída.')
    a = [str(source.resolve()) + ('' if preserve else '[0]')]
    if preserve and o.format in {'gif','webp'}:
        a += ['-coalesce']
    a += operations(o)
    if preview:
        a += ['-thumbnail', '1100x1100>']
    if o.format == 'ico' and not preview:
        sizes = [int(s) for s in o.ico_sizes.split(',')]
        if any(s not in range(1, 257) for s in sizes):
            raise ValueError('Resoluções ICO devem estar entre 1 e 256.')
        a += ['-define', 'icon:auto-resize=' + ','.join(map(str, sizes))]
    a += ['-quality', str(o.quality), str(destination.resolve())]
    return a
