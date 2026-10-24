"""Empacota somente fontes, testes e documentação, sem ambientes ou caches."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root=Path(__file__).resolve().parents[1]
target=root.parent/'ImageMagickStudio-codigo-fonte.zip'
with ZipFile(target,'w',ZIP_DEFLATED) as archive:
    paths=[p for p in root.iterdir() if p.is_file()]
    for folder in ['studio','tests','scripts','assets','validacao']:
        paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'})
    for path in sorted(paths):
        archive.write(path,Path('ImageMagickStudio')/path.relative_to(root))
print(target)
