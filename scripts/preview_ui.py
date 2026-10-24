"""Gera uma captura da própria interface com dados sintéticos para revisão visual."""
import os
import sys
import tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'vendor')]
os.environ['QT_QPA_PLATFORM']='offscreen'
work=root/'.test-work'/'visual'
work.mkdir(parents=True,exist_ok=True)
tempfile.tempdir=str(work)
from PIL import Image, ImageDraw
from PySide6.QtCore import QTimer, QSettings
from PySide6.QtWidgets import QApplication
from studio.ui import MainWindow

app=QApplication([])
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(work))
window=MainWindow()
window.show()
paths=[]
for index,name in enumerate(['Serra ao entardecer','Estudo de cores','Horizonte']):
    image=Image.new('RGB',(1200,800))
    draw=ImageDraw.Draw(image)
    for y in range(800):
        t=y/800
        draw.line([(0,y),(1200,y)],fill=(int(48+95*t),int(59+50*t),int(101+15*t)))
    draw.ellipse((740,140,900,300),fill='#edc79d')
    draw.polygon([(0,620),(280,280),(580,640),(810,390),(1200,690),(1200,800),(0,800)],fill='#48445d')
    draw.polygon([(0,740),(360,510),(660,750),(960,480),(1200,730),(1200,800),(0,800)],fill='#262e43')
    path=work/(name+'.png')
    image.save(path)
    paths.append(path)
window.set_control('resize','ajustar')
window.set_control('width',1080)
window.set_control('height',1350)
window.set_control('saturation',115)
window.loaded_files([(p,'1200 × 800',p.stat().st_size,1,False) for p in paths])
window.table.selectRow(0)
window.navigation.setCurrentRow(1)
def finish():
    if window.preview_job and window.preview_job.isRunning():
        QTimer.singleShot(400,finish)
        return
    (root/'assets').mkdir(exist_ok=True)
    window.grab().save(str(root/'assets'/'interface.png'))
    window.close()
    app.quit()
QTimer.singleShot(4000,finish)
app.exec()
