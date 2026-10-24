from pathlib import Path
from threading import Event
import pytest
from PIL import Image, ImageCms
from studio.domain import Options
from studio.services import Processor, run_batch
from studio.infrastructure import Magick


@pytest.mark.parametrize('format',['gif','webp','tiff'])
def test_preserve_frames(tmp_path,format):
    source=tmp_path/'animado.gif'
    first=Image.new('RGB',(30,20),'red')
    second=Image.new('RGB',(30,20),'blue')
    first.save(source,save_all=True,append_images=[second],duration=100,loop=0)
    result=run_batch(Processor(Magick()),[source],tmp_path/'out',Options(format=format,preserve_frames=True),Event())[0]
    assert result.state=='concluído',result.error
    with Image.open(result.outputs[0]) as im:
        assert im.n_frames==2


def test_metadata_icc(tmp_path):
    source=tmp_path/'perfil.jpg'
    im=Image.new('RGB',(20,20),'red')
    exif=Image.Exif()
    exif[270]='informação pessoal'
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    im.save(source,exif=exif,icc_profile=profile)
    for index,options in enumerate([Options(format='jpg',strip=False),Options(format='jpg',strip=True,keep_icc=True),Options(format='jpg',strip=True,keep_icc=False)]):
        result=run_batch(Processor(Magick()),[source],tmp_path/str(index),options,Event())[0]
        assert result.state=='concluído',result.error
        with Image.open(result.outputs[0]) as out:
            assert bool(out.info.get('icc_profile')) == (index!=2)
            assert bool(out.getexif().get(270)) == (index==0)


def test_comments_removed(tmp_path):
    from studio.pipeline import command
    source=tmp_path/'comment.png'
    annotated=tmp_path/'annotated.png'
    output=tmp_path/'output.png'
    Image.new('RGB',(10,10),'red').save(source)
    magick=Magick()
    magick.run([str(source),'-set','comment','dado pessoal',str(annotated)])
    magick.run(command(annotated,output,Options()))
    assert magick.run(['identify','-format','%c',str(output)]).strip()==''


def test_huge_transform_rejected_before_encoding(tmp_path):
    source=tmp_path/'imagem.png'
    Image.new('RGB',(1100,1100),'red').save(source)
    result=run_batch(Processor(Magick()),[source],tmp_path/'out',Options(resize='percentual',percent=1000),Event())[0]
    assert result.state=='falhou'
    assert '100 megapixels' in result.error
    assert not result.outputs
