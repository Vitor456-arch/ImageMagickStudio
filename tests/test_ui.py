import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings, QEventLoop, QTimer
from studio.ui import MainWindow


def test_ui_starts(tmp_path):
    app=QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path))
    window=MainWindow()
    window.show()
    app.processEvents()
    assert window.stack.count()==13
    assert len(window.controls)==len(__import__('dataclasses').fields(__import__('studio.domain',fromlist=['Options']).Options))-1
    window.grab().save(str(tmp_path/'interface.png'))
    window.timer.stop()
    window.close()
    app.processEvents()


def test_ui_processes_without_blocking(tmp_path):
    from PIL import Image
    source=tmp_path/'origem.png'
    Image.new('RGB',(64,32),'red').save(source)
    app=QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path))
    window=MainWindow()
    window.loaded_files([(source,'64 × 32',source.stat().st_size,1,False)])
    window.timer.stop()
    window.output.setText(str(tmp_path/'out'))
    loop=QEventLoop()
    ticks=[]
    heartbeat=QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start()
    QTimer.singleShot(15000,loop.quit)
    window.start()
    window.job.finished.connect(loop.quit)
    loop.exec()
    heartbeat.stop()
    assert not window.is_busy()
    assert window.results[0].state=='concluído'
    assert len(ticks)>0
    assert window.execute.isEnabled()
    window.close()
    app.processEvents()
