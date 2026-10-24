"""Autoteste do programa distribuído, somente em uma nova pasta."""
import json
from pathlib import Path
from threading import Event
from PIL import Image
from .domain import Options
from .infrastructure import Magick
from .services import Processor, run_batch


def smoke_test(folder: Path) -> int:
    folder.mkdir(parents=True,exist_ok=False)
    magick=Magick()
    sources=[]
    for index,color in enumerate(['red','blue']):
        path=folder/f'teste com acentuação {index}.png'
        Image.new('RGB',(48,24),color).save(path)
        sources.append(path)
    processor=Processor(magick)
    results=[]
    for option in [Options(format='webp',resize='largura',width=24),Options(operation='imagens_pdf'),Options(operation='criar_gif',width=48,height=24),Options(operation='grade',columns=2)]:
        results.extend(run_batch(processor,sources,folder/'saida',option,Event()))
    summary={'magick':magick.version,'results':[r.dictionary() for r in results], 'ok':all(r.state=='concluído' for r in results)}
    (folder/'smoke-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if summary['ok'] else 1


def ui_smoke_test(folder: Path) -> int:
    from PySide6.QtCore import QTimer, QSettings
    from PySide6.QtWidgets import QApplication
    from .ui import MainWindow
    folder.mkdir(parents=True,exist_ok=False)
    app=QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(folder))
    window=MainWindow()
    window.show()
    def finish():
        window.grab().save(str(folder/'interface.png'))
        (folder/'ui-result.json').write_text(json.dumps({'ok':window.isVisible(),'categories':window.stack.count(),'controls':len(window.controls)}),encoding='utf-8')
        window.close()
        app.quit()
    QTimer.singleShot(1200,finish)
    return app.exec()
