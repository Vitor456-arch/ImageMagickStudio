"""Build reproduzível: python scripts/build.py. Dependências em requirements-dev.txt."""
import os
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
arguments=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir',
           '--name','ImageMagickStudio','--paths',str(root),
           '--distpath',str(root.parent/'Aplicativo-2.0'),
           '--workpath',str(root.parent/'build-reconstrucao'),
           '--specpath',str(root.parent/'build-reconstrucao'),
           '--collect-all','pymupdf','--collect-all','pypdf',
           '--exclude-module','PySide6.QtWebEngineCore',
           '--exclude-module','PySide6.QtWebEngineWidgets',
           '--exclude-module','onnxruntime','--exclude-module','numpy',
           '--exclude-module','pytest', '--exclude-module','tkinter',
           '--exclude-module','pandas','--exclude-module','scipy',
           '--exclude-module','matplotlib','--exclude-module','IPython',
           '--exclude-module','torch','--exclude-module','sympy',
           str(root/'run.py')]
environment=os.environ.copy()
if '--incremental' in sys.argv:
    arguments.remove('--clean')
if (root/'vendor').exists():
    arguments[arguments.index('--distpath'):arguments.index('--distpath')]=['--paths',str(root/'vendor')]
    environment['PYTHONPATH']=str(root/'vendor')+os.pathsep+environment.get('PYTHONPATH','')
result=subprocess.run(arguments,cwd=root,env=environment,shell=False).returncode
if result==0 and os.name=='nt':
    # O Qt usa a ICU do Windows. Um ICU de Poppler no PATH pode ser coletado
    # indevidamente pelo PyInstaller com o mesmo nome e símbolos incompatíveis.
    import pefile
    icu=root.parent/'Aplicativo-2.0'/'ImageMagickStudio'/'_internal'/'icuuc.dll'
    if icu.exists():
        library=pefile.PE(str(icu))
        symbols={entry.name for entry in library.DIRECTORY_ENTRY_EXPORT.symbols}
        library.close()
        if b'ucnv_open' not in symbols:
            icu.unlink()
            print('ICU externa incompatível removida; o Qt utilizará a biblioteca do Windows.')
raise SystemExit(result)
