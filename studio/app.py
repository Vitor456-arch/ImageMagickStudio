import logging
import sys
from logging.handlers import RotatingFileHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from .infrastructure import config_dir
from .ui import MainWindow


def main():
    log = RotatingFileHandler(config_dir() / 'studio.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8')
    log.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.getLogger('studio').addHandler(log)
    logging.getLogger('studio').setLevel(logging.INFO)
    app = QApplication(sys.argv)
    app.setApplicationName('ImageMagick Studio')
    app.setFont(QFont('Segoe UI',10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
