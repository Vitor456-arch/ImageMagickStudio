import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from studio.domain import Options, page_indices
from studio.infrastructure import Magick, OutputStore, safe_name
from studio.pipeline import command, operations
from studio.services import Processor, run_batch, export_report


@pytest.fixture(scope='session')
def magick():
    m = Magick()
    assert m.executable, m.details
    return m


@pytest.fixture
def pictures(tmp_path):
    paths = []
    for i, color in enumerate(['red', 'blue', 'green']):
        path = tmp_path / f'imagem com espaço e ação 漢字 {i}.png'
        im = Image.new('RGBA', (80, 40), color)
        im.putpixel((0,0),(0,0,0,0))
        im.save(path)
        paths.append(path)
    return paths


def execute(tmp_path, magick, sources, options):
    return run_batch(Processor(magick), sources, tmp_path/'saída', options, Event())


def test_command_arguments(pictures,tmp_path):
    args = command(pictures[0], tmp_path/'saída.png', Options(horizontal=True,vertical=True))
    assert args[0] == str(pictures[0].resolve())+'[0]'
    assert '-flop' in args and '-flip' in args
    assert args[-1] == str((tmp_path/'saída.png').resolve())
    assert operations(Options(auto_orient=False,strip=False)) == ['-filter','Lanczos','-background','#ffffff']


@pytest.mark.parametrize('mode,expected', [('nenhum',(80,40)),('largura',(40,20)),('altura',(60,30)),('percentual',(40,20)),('ajustar',(40,20)),('preencher',(40,30)),('forcar',(40,30)),('reduzir',(40,20))])
def test_resize(tmp_path,magick,pictures,mode,expected):
    result = execute(tmp_path,magick,pictures[:1],Options(resize=mode,width=40,height=30))[0]
    assert result.state == 'concluído',result.error
    with Image.open(result.outputs[0]) as im:
        assert im.size == expected


def test_only_reduce(tmp_path,magick,pictures):
    result = execute(tmp_path,magick,pictures[:1],Options(resize='reduzir',width=1000,height=1000))[0]
    assert Image.open(result.outputs[0]).size == (80,40)


@pytest.mark.parametrize('ratio,expected',[('livre',(20,10)),('1:1',(40,40)),('16:9',(71,40))])
def test_crop(tmp_path,magick,pictures,ratio,expected):
    result = execute(tmp_path,magick,pictures[:1],Options(crop=True,crop_width=20,crop_height=10,crop_ratio=ratio))[0]
    assert result.state == 'concluído',result.error
    assert Image.open(result.outputs[0]).size == expected


def test_orientation_mirror(tmp_path,magick,pictures):
    im = Image.new('RGB',(4,2),'blue')
    im.putpixel((0,0),(255,0,0))
    im.save(pictures[0])
    result = execute(tmp_path,magick,pictures[:1],Options(horizontal=True,vertical=True))[0]
    with Image.open(result.outputs[0]) as out:
        assert out.convert('RGB').getpixel((3,1)) == (255,0,0)
    result = execute(tmp_path,magick,pictures[:1],Options(angle=90))[0]
    assert Image.open(result.outputs[0]).size == (2,4)


def test_exif(tmp_path,magick,pictures):
    source = tmp_path/'orientação.jpg'
    im = Image.new('RGB',(20,10),'red')
    exif = Image.Exif()
    exif[274]=6
    exif[270]='segredo'
    im.save(source,exif=exif)
    result = execute(tmp_path,magick,[source],Options())[0]
    with Image.open(result.outputs[0]) as out:
        assert out.size == (10,20)
        assert 270 not in out.getexif()


def test_transparency(tmp_path,magick,pictures):
    result = execute(tmp_path,magick,pictures[:1],Options())[0]
    assert Image.open(result.outputs[0]).convert('RGBA').getpixel((0,0))[3] == 0
    result = execute(tmp_path,magick,pictures[:1],Options(format='jpg',background='#00ff00',quality=100))[0]
    with Image.open(result.outputs[0]) as out:
        assert out.convert('RGB').getpixel((0,0))[1] > 180
    result = execute(tmp_path,magick,pictures[:1],Options(remove_color=True,transparent_color='#ff0000'))[0]
    assert Image.open(result.outputs[0]).convert('RGBA').getpixel((10,10))[3] == 0


@pytest.mark.parametrize('effect',['desfoque','nitidez','unsharp','ruido','mediana','carvao','oleo','bordas','relevo','pixelizar','posterizar','limiar','vinheta'])
def test_effects(tmp_path,magick,pictures,effect):
    result=execute(tmp_path,magick,pictures[:1],Options(effect=effect,radius=4,strength=2))[0]
    assert result.state=='concluído',result.error
    assert Image.open(result.outputs[0]).size==(80,40)


def test_colors_watermark(tmp_path,magick,pictures):
    options=Options(brightness=5,contrast=5,saturation=30,hue=50,temperature=20,gamma=1.2,exposure=.5,auto_level=True,auto_contrast=True,normalize=True,sepia=30,negative=True,watermark='Teste',font_size=12,margin=2)
    result=execute(tmp_path,magick,pictures[:1],options)[0]
    assert result.state=='concluído',result.error


def test_collisions_and_original(tmp_path,magick,pictures):
    first=execute(tmp_path,magick,pictures[:1],Options())[0]
    second=execute(tmp_path,magick,pictures[:1],Options())[0]
    assert first.outputs != second.outputs
    assert execute(tmp_path,magick,pictures[:1],Options(conflict='ignorar'))[0].state=='ignorado'
    store=OutputStore(tmp_path,pictures,'substituir')
    with pytest.raises(ValueError):
        store.reserve(pictures[0].name)
    assert safe_name('CON')=='_CON'
    assert ':' not in safe_name('a:b')


def test_batch_summary_and_report(tmp_path,magick,pictures):
    broken=tmp_path/'inválida.png'
    broken.write_bytes(b'invalida')
    missing=tmp_path/'ausente.png'
    result=execute(tmp_path,magick,[pictures[0],broken,missing],Options())
    assert [r.state for r in result]==['concluído','falhou','falhou']
    export_report(tmp_path/'report.json',result)
    export_report(tmp_path/'report.csv',result)
    assert len(json.loads((tmp_path/'report.json').read_text(encoding='utf-8')))==3
    assert not list((tmp_path/'saída').glob('.studio-*'))


def test_cancel(tmp_path,magick,pictures):
    event=Event()
    event.set()
    result=run_batch(Processor(magick),pictures,tmp_path/'saída',Options(),event)
    assert all(r.state=='cancelado' for r in result)
    assert not list((tmp_path/'saída').glob('*'))


def test_cancel_running(magick):
    from threading import Timer
    from studio.domain import CancelledError
    event=Event()
    timer=Timer(.2,event.set)
    timer.start()
    try:
        with pytest.raises(CancelledError):
            magick.run(['-size','6000x6000','plasma:fractal','-blur','0x30','null:'],event)
    finally:
        timer.cancel()


def test_atomic_failure(tmp_path,pictures):
    store=OutputStore(tmp_path/'out',pictures,'renomear')
    target=store.reserve('x.png')
    with pytest.raises(RuntimeError):
        with store.atomic(target,Event()) as p:
            p.write_bytes(b'incompleto')
            raise RuntimeError('falha')
    assert list((tmp_path/'out').iterdir())==[]


def test_no_magick(tmp_path,pictures,monkeypatch):
    m=Magick()
    m.executable=''
    result=execute(tmp_path,m,pictures[:1],Options())[0]
    assert result.state=='falhou'
    assert 'ausente' in result.error


@pytest.mark.parametrize('fmt',['png','jpg','jpeg','webp','gif','bmp','tiff','ico','avif','heic','heif','svg','eps','psd'])
def test_formats(tmp_path,magick,pictures,fmt):
    if fmt not in magick.formats:
        pytest.skip('Codec indisponível')
    result=execute(tmp_path,magick,pictures[:1],Options(format=fmt))[0]
    assert result.state=='concluído',result.error


def test_pdf(tmp_path,magick,pictures):
    results=execute(tmp_path,magick,pictures,Options(operation='imagens_pdf',output_name='album'))
    assert results[0].state=='concluído',results[0].error
    pdf=Path(results[0].outputs[0])
    assert len(PdfReader(pdf).pages)==3
    reordered=execute(tmp_path,magick,[pdf],Options(operation='reordenar_pdf',pages='3,1',suffix='_reordenado'))[0]
    assert reordered.state=='concluído',reordered.error
    assert len(PdfReader(reordered.outputs[0]).pages)==2
    split=execute(tmp_path,magick,[pdf],Options(operation='dividir_pdf',pages='2-3'))[0]
    assert len(split.outputs)==2,split.error
    merge=execute(tmp_path,magick,[Path(p) for p in split.outputs],Options(operation='mesclar_pdf'))[0]
    assert len(PdfReader(merge.outputs[0]).pages)==2,merge.error
    render=execute(tmp_path,magick,[pdf],Options(operation='pdf_imagens',pages='1',dpi=72))[0]
    assert render.state=='concluído',render.error
    assert Image.open(render.outputs[0]).width==596


def test_pdf_text_preserved(tmp_path,magick):
    import pymupdf
    source=tmp_path/'texto.pdf'
    with pymupdf.open() as doc:
        page=doc.new_page()
        page.insert_text((72,72),'Texto preservado')
        doc.save(source)
    merge=execute(tmp_path,magick,[source,source],Options(operation='mesclar_pdf'))[0]
    assert merge.state=='concluído',merge.error
    reader=PdfReader(merge.outputs[0])
    assert len(reader.pages)==2
    assert 'Texto preservado' in reader.pages[0].extract_text()


def test_gif(tmp_path,magick,pictures):
    result=execute(tmp_path,magick,pictures,Options(operation='criar_gif',width=80,height=40,frame_delays='100,200,300'))[0]
    assert result.state=='concluído',result.error
    gif=Path(result.outputs[0])
    with Image.open(gif) as im:
        assert im.n_frames==3
        im.seek(1)
        assert im.info['duration']==200
        assert im.info['loop']==0
    extracted=execute(tmp_path,magick,[gif],Options(operation='extrair_gif'))[0]
    assert len(extracted.outputs)==3


@pytest.mark.parametrize('operation,expected',[('horizontal',(272,40)),('vertical',(80,152)),('grade',(176,96)),('sobrepor',(80,40))])
def test_composition(tmp_path,magick,pictures,operation,expected):
    result=execute(tmp_path,magick,pictures,Options(operation=operation,columns=2))[0]
    assert result.state=='concluído',result.error
    assert Image.open(result.outputs[0]).size==expected


def test_pages():
    assert page_indices('3-1,2',3)==[2,1,0,1]
    with pytest.raises(ValueError):
        page_indices('0',3)
