import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict, fields, replace
from pathlib import Path
from threading import Event

from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QUrl, QRectF, QSize
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPixmap, QPainter, QPen, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QStackedWidget, QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QLineEdit, QScrollArea, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QSplitter, QGraphicsView,
    QGraphicsScene, QColorDialog, QDialog, QPlainTextEdit, QAbstractItemView,
)

from .domain import Options, Result, CancelledError, page_indices
from .infrastructure import Magick
from .services import Processor, run_batch, image_info, export_report, GROUPED, validate_image
from .pipeline import command

EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.ico', '.pdf', '.avif', '.heic', '.heif', '.svg', '.eps', '.psd'}
OPERATIONS = [('Converter imagens', 'converter'), ('Imagens para PDF', 'imagens_pdf'), ('PDF para imagens', 'pdf_imagens'), ('Mesclar PDFs', 'mesclar_pdf'), ('Dividir PDF por página', 'dividir_pdf'), ('Reordenar / extrair páginas PDF', 'reordenar_pdf'), ('Criar GIF animado', 'criar_gif'), ('Extrair quadros de GIF', 'extrair_gif'), ('Combinar horizontalmente', 'horizontal'), ('Combinar verticalmente', 'vertical'), ('Montar grade', 'grade'), ('Sobrepor imagens', 'sobrepor')]


class Job(QThread):
    update = Signal(int, str, object)
    progress = Signal(int, int)
    done = Signal(object)
    error = Signal(str)

    def __init__(self, processor, sources, output, options):
        super().__init__()
        self.processor, self.sources, self.output, self.options = processor, sources, output, options
        self.cancel = Event()

    def run(self):
        try:
            result = run_batch(self.processor, self.sources, self.output, self.options, self.cancel,
                               lambda i, state, r: self.update.emit(i, state, r),
                               lambda i, value: self.progress.emit(i, value))
            self.done.emit(result)
        except (OSError, ValueError, RuntimeError) as exc:
            self.error.emit(str(exc))


class PreviewJob(QThread):
    ready = Signal(str, str, str)
    failed = Signal(str)

    def __init__(self, magick, source, options, folder):
        super().__init__()
        self.magick, self.source, self.options, self.folder = magick, source, options, folder
        self.cancel = Event()

    def run(self):
        try:
            before, after = Path(self.folder) / 'before.png', Path(self.folder) / 'after.png'
            if self.source.suffix.lower() == '.pdf':
                import pymupdf
                with pymupdf.open(self.source) as doc:
                    doc[0].get_pixmap(dpi=80).save(before)
                source = before
            else:
                source = self.source
                validate_image(self.magick, source, self.cancel, self.options)
                self.magick.run([str(source) + '[0]', '-auto-orient', '-thumbnail', '1100x1100>', str(before)], self.cancel)
            preview = replace(self.options, format='png')
            self.magick.run(command(source, after, preview, preview=True), self.cancel)
            try:
                info = image_info(self.source)
                description = f"{info['width']} × {info['height']}  ·  {info['mode']}  ·  {info['frames']} quadro(s)/página(s)"
            except (OSError, ValueError, RuntimeError):
                description = 'Prévia do primeiro quadro'
            self.ready.emit(str(before), str(after), description)
        except CancelledError:
            pass
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))


class ImportJob(QThread):
    loaded = Signal(object)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        entries = []
        for source in self.paths:
            candidates = sorted(source.rglob('*')) if source.is_dir() else [source]
            for path in candidates:
                if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                    continue
                try:
                    info = image_info(path)
                    dimensions = f"{info['width']} × {info['height']}"
                    frames = info['frames']
                    gps = info['gps']
                except (OSError, ValueError, RuntimeError):
                    dimensions, frames, gps = 'A verificar', 1, False
                entries.append((path.resolve(), dimensions, path.stat().st_size, frames, gps))
                if len(entries) >= 10000:
                    break
        self.loaded.emit(entries)


class PageThumbnailJob(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.cancel = Event()

    def run(self):
        import pymupdf
        try:
            items=[]
            with pymupdf.open(self.source) as doc:
                if len(doc)>500:
                    raise ValueError('O editor visual suporta até 500 páginas. Use a sequência numérica para documentos maiores.')
                for i,page in enumerate(doc):
                    if self.cancel.is_set():
                        return
                    scale=150/max(page.rect.width,page.rect.height)
                    pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                    items.append((i,pix.tobytes('png')))
            self.loaded.emit(items)
        except (OSError,ValueError,RuntimeError) as exc:
            self.failed.emit(str(exc))


class ImageView(QGraphicsView):
    cropped = Signal(int, int, int, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumHeight(200)
        self.setStyleSheet('QGraphicsView { background: #101218; border: 1px solid #303541; border-radius: 8px; }')
        self.pixmap = None
        self.select_crop = False
        self.start = None
        self.selection = None
        self.source_size = None

    def show_image(self, path):
        self.scene().clear()
        self.selection = None
        self.pixmap = QPixmap(path)
        self.scene().addPixmap(self.pixmap)
        self.scene().setSceneRect(QRectF(self.pixmap.rect()))
        self.fit()

    def fit(self):
        if self.pixmap:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        if .01 < self.transform().m11() * factor < 50:
            self.scale(factor, factor)

    def mousePressEvent(self, event):
        if self.select_crop and self.pixmap and event.button() == Qt.MouseButton.LeftButton:
            self.start = self.mapToScene(event.pos())
            if self.selection:
                self.scene().removeItem(self.selection)
            self.selection = self.scene().addRect(QRectF(self.start, self.start), QPen(QColor('#8f9bff'), 2))
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start is not None and self.selection:
            rect = QRectF(self.start, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self.selection.setRect(rect)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.start is not None and self.selection:
            r = self.selection.rect()
            sx, sy = self.source_size or (self.pixmap.width(), self.pixmap.height())
            sx, sy = sx/self.pixmap.width(), sy/self.pixmap.height()
            if r.width() >= 1 and r.height() >= 1:
                self.cropped.emit(round(r.x()*sx), round(r.y()*sy), max(1, round(r.width()*sx)), max(1, round(r.height()*sy)))
            self.start = None
        else:
            super().mouseReleaseEvent(event)


STYLE = '''
QWidget { background: #181b23; color: #e5e7ef; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow { background: #181b23; }
QLabel#title { font-size: 23px; font-weight: 650; }
QLabel#muted { color: #959eb1; }
QLabel#section { font-size: 16px; font-weight: 650; padding: 8px 0; }
QPushButton { background: #2b303e; border: 1px solid #3a4152; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover { background: #383f53; }
QPushButton:disabled { color: #6e7689; border-color: #2b303e; }
QPushButton#primary { background: #737de8; color: white; border: 0; font-weight: 650; padding: 11px 24px; }
QPushButton#primary:hover { background: #8790fa; }
QPushButton#primary:disabled { background: #41465f; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #222733; border: 1px solid #3a4152; border-radius: 5px; padding: 6px; min-height: 18px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPushButton:focus { border: 1px solid #a4acff; }
QComboBox QAbstractItemView { selection-background-color: #4a527e; }
QCheckBox { spacing: 8px; padding: 5px 0; }
QListWidget { background: #14171e; border: 0; padding: 8px; outline: 0; }
QListWidget::item { padding: 12px 8px; border-radius: 5px; color: #a7afc0; }
QListWidget::item:selected { background: #2c324b; color: #bcc2ff; }
QTableWidget { background: #1d212b; alternate-background-color: #202530; gridline-color: #2d3341; border: 1px solid #303644; border-radius: 6px; selection-background-color: #363e60; }
QHeaderView::section { background: #252a36; color: #a9b2c4; border: 0; padding: 10px; }
QProgressBar { border: 0; border-radius: 4px; background: #2b303e; text-align: center; min-height: 17px; }
QProgressBar::chunk { background: #737de8; border-radius: 4px; }
QScrollArea { border: 0; }
QSplitter::handle { background: #303644; width: 2px; height: 2px; }
QPlainTextEdit { background: #11141b; border: 1px solid #3a4152; }
'''


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ImageMagick Studio 2.0')
        if not QFontDatabase.families():
            font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'
            if font_path.exists():
                QFontDatabase.addApplicationFont(str(font_path))
        self.resize(1510, 980)
        self.setMinimumSize(1120, 760)
        self.setAcceptDrops(True)
        self.settings = QSettings('ImageMagickStudio', 'Studio2')
        self.magick = Magick(self.settings.value('magick', ''))
        self.sources: list[Path] = []
        self.metadata = {}
        self.controls = {}
        self.results = []
        self.row_results = {}
        self.completed = set()
        self.job = None
        self.imports = []
        self.thumbnail_jobs = []
        self.preview_job = None
        self.preview_folder = tempfile.TemporaryDirectory(prefix='studio-preview-')
        self.preview_pending = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self.refresh_preview)
        self.build_ui()
        self.restore_preferences()
        self.restoreGeometry(self.settings.value('geometry', b''))
        self.setStyleSheet(STYLE)
        self.status.setText('Pronto para começar. Adicione arquivos ou arraste uma pasta para a janela.' if self.magick.executable else 'ImageMagick não encontrado. Abra Diagnóstico para indicar magick.exe.')

    def button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel('ImageMagick Studio')
        title.setObjectName('title')
        header.addWidget(title)
        subtitle = QLabel('2.0   /   SEU ESTÚDIO DE IMAGENS')
        subtitle.setObjectName('muted')
        header.addWidget(subtitle)
        header.addStretch()
        self.button('Diagnóstico', self.diagnostics, header)
        layout.addLayout(header)
        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(162)
        categories = ['Conversão', 'Redimensionar', 'Recorte', 'Orientação', 'Cor e luz', 'Filtros e efeitos', 'Fundo', 'Marca-d’água', 'Metadados', 'PDF', 'GIF animado', 'Composição', 'Saída e lote']
        self.navigation.addItems(categories)
        body.addWidget(self.navigation)
        center = QVBoxLayout()
        toolbar = QHBoxLayout()
        self.add_file = self.button('Adicionar arquivos', self.choose_files, toolbar)
        self.add_folder = self.button('Adicionar pasta', self.choose_folder, toolbar)
        toolbar.addStretch()
        self.count_label = QLabel('0 arquivos')
        self.count_label.setObjectName('muted')
        toolbar.addWidget(self.count_label)
        center.addLayout(toolbar)
        self.operation = QComboBox()
        for label, value in OPERATIONS:
            self.operation.addItem(label, value)
        self.operation.currentIndexChanged.connect(self.operation_changed)
        center.addWidget(self.operation)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Arquivo', 'Tipo', 'Dimensões', 'Tamanho', 'Estado'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.schedule_preview)
        self.table.itemDoubleClicked.connect(self.show_details)
        center.addWidget(self.table, 2)
        file_actions = QHBoxLayout()
        self.up = self.button('Subir', lambda: self.move(-1), file_actions)
        self.down = self.button('Descer', lambda: self.move(1), file_actions)
        self.remove = self.button('Remover', self.remove_selected, file_actions)
        self.clear_button = self.button('Limpar', self.clear, file_actions)
        file_actions.addStretch()
        self.button('Detalhes', self.show_details, file_actions)
        center.addLayout(file_actions)
        preview_toolbar = QHBoxLayout()
        label = QLabel('PRÉ-VISUALIZAÇÃO')
        label.setObjectName('muted')
        preview_toolbar.addWidget(label)
        preview_toolbar.addStretch()
        self.button('Ajustar', self.fit_preview, preview_toolbar)
        self.button('100%', self.actual_size, preview_toolbar)
        self.crop_selection = QCheckBox('Selecionar recorte')
        self.crop_selection.toggled.connect(self.toggle_crop)
        preview_toolbar.addWidget(self.crop_selection)
        center.addLayout(preview_toolbar)
        previews = QHBoxLayout()
        self.before, self.after = ImageView(), ImageView()
        self.before.cropped.connect(self.visual_crop)
        for title, view in [('ORIGINAL', self.before), ('RESULTADO', self.after)]:
            column = QVBoxLayout()
            label = QLabel(title)
            label.setObjectName('muted')
            column.addWidget(label)
            column.addWidget(view)
            previews.addLayout(column)
        center.addLayout(previews, 3)
        self.preview_info = QLabel('Selecione um arquivo para comparar. Use a roda do mouse para ampliar.')
        self.preview_info.setWordWrap(True)
        self.preview_info.setObjectName('muted')
        center.addWidget(self.preview_info)
        body.addLayout(center, 1)
        self.stack = QStackedWidget()
        self.stack.setFixedWidth(330)
        body.addWidget(self.stack)
        layout.addLayout(body, 1)
        self.build_forms(categories)
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel('Pasta de saída'))
        self.output = QLineEdit(self.settings.value('output', str(Path.home() / 'Pictures' / 'Studio-saida')))
        output_row.addWidget(self.output, 1)
        self.button('Escolher pasta', self.choose_output, output_row)
        self.button('Abrir pasta', self.open_output, output_row)
        layout.addLayout(output_row)
        footer = QHBoxLayout()
        progress_column = QVBoxLayout()
        self.status = QLabel('Pronto')
        self.status.setWordWrap(True)
        progress_column.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        progress_column.addWidget(self.progress)
        footer.addLayout(progress_column, 1)
        self.report_button = self.button('Exportar relatório', self.save_report, footer)
        self.report_button.setEnabled(False)
        self.retry_button = self.button('Repetir falhas', self.retry, footer)
        self.retry_button.setEnabled(False)
        self.cancel_button = self.button('Cancelar', self.cancel, footer)
        self.cancel_button.setEnabled(False)
        self.execute = self.button('Executar processamento', self.start, footer)
        self.execute.setObjectName('primary')
        layout.addLayout(footer)
        for shortcut, callback in [('Ctrl+O', self.choose_files), ('Delete', self.remove_selected), ('Ctrl+Return', self.start), ('Escape', self.cancel)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    def form(self, title, description=''):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        outer = QVBoxLayout(widget)
        label = QLabel(title)
        label.setObjectName('section')
        outer.addWidget(label)
        if description:
            label = QLabel(description)
            label.setWordWrap(True)
            label.setObjectName('muted')
            outer.addWidget(label)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setSpacing(8)
        outer.addLayout(form)
        outer.addStretch()
        reset = QPushButton('Restaurar esta categoria')
        reset.clicked.connect(lambda: self.reset_form(form))
        outer.addWidget(reset)
        scroll.setWidget(widget)
        self.stack.addWidget(scroll)
        return form

    def control(self, form, name, label, kind='number', limits=None, choices=None):
        default = getattr(Options(), name)
        if kind == 'bool':
            widget = QCheckBox(label)
            widget.setChecked(default)
            widget.toggled.connect(self.schedule_preview)
            form.addRow(widget)
        elif kind == 'choice':
            widget = QComboBox()
            for choice in choices:
                text, value = choice if isinstance(choice, tuple) else (choice, choice)
                widget.addItem(text, value)
            widget.setCurrentIndex(max(0, widget.findData(default)))
            widget.currentIndexChanged.connect(self.schedule_preview)
            form.addRow(label, widget)
        elif kind in {'text', 'color'}:
            widget = QLineEdit(str(default))
            widget.textChanged.connect(self.schedule_preview)
            if kind == 'color':
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(widget)
                b = QPushButton('Cor')
                b.clicked.connect(lambda: self.pick_color(widget))
                h.addWidget(b)
                form.addRow(label, row)
            else:
                form.addRow(label, widget)
        else:
            widget = QDoubleSpinBox() if isinstance(default, float) else QSpinBox()
            widget.setRange(*(limits or (0, 10000)))
            if isinstance(widget, QDoubleSpinBox):
                widget.setDecimals(2)
                widget.setSingleStep(.1)
            widget.setValue(default)
            widget.valueChanged.connect(self.schedule_preview)
            form.addRow(label, widget)
        widget.setObjectName(name)
        widget.setAccessibleName(label)
        self.controls[name] = widget
        return widget

    def build_forms(self, categories):
        c = self.control
        f = self.form(categories[0], 'As configurações das categorias são combinadas na mesma operação. Conversão simples usa o primeiro quadro; para animações, use GIF animado.')
        formats = ['png','jpg','jpeg','webp','gif','bmp','tiff','ico','pdf','avif','heic','heif','svg','eps','psd']
        format_widget = c(f, 'format', 'Formato de saída', 'choice', choices=[(s.upper(), s) for s in formats])
        for i, fmt in enumerate(formats):
            if fmt != 'pdf' and fmt not in self.magick.formats:
                item = format_widget.model().item(i)
                item.setEnabled(False)
                item.setToolTip('Sem codificador disponível no ImageMagick detectado.')
        c(f, 'quality', 'Qualidade (1–100)', limits=(1,100))
        c(f, 'preserve_frames', 'Preservar quadros / páginas (GIF, WEBP, TIFF)', 'bool')
        c(f, 'ico_sizes', 'Resoluções ICO, separadas por vírgula', 'text')
        note = QLabel('SVG/EPS encapsulam pixels, sem vetorização. PSD não recria camadas. TIFF usa o primeiro quadro na conversão simples.')
        note.setWordWrap(True)
        f.addRow(note)
        f = self.form(categories[1], 'Dimensões em pixels. “Somente reduzir” preserva imagens menores.')
        c(f, 'resize', 'Modo', 'choice', choices=[('Não redimensionar','nenhum'),('Por largura','largura'),('Por altura','altura'),('Percentual','percentual'),('Ajustar dentro','ajustar'),('Preencher e recortar','preencher'),('Forçar dimensões','forcar'),('Somente reduzir','reduzir')])
        preset = QComboBox()
        preset.addItems(['Personalizado','Full HD · 1920 × 1080','4K · 3840 × 2160','Instagram · 1080 × 1350','Story · 1080 × 1920','Ícone · 256 × 256'])
        preset.currentIndexChanged.connect(lambda i: self.apply_preset(i))
        f.addRow('Ponto de partida (editável)', preset)
        c(f, 'width', 'Largura', limits=(1,30000))
        c(f, 'height', 'Altura', limits=(1,30000))
        c(f, 'percent', 'Percentual (%)', limits=(.1,1000))
        c(f, 'interpolation', 'Interpolação', 'choice', choices=[('Lanczos · fotografias','Lanczos'),('Nearest neighbor · pixel art','Point'),('Bicúbica','Cubic'),('Bilinear','Triangle')])
        f = self.form(categories[2], 'Ative “Selecionar recorte” e arraste sobre a imagem original. Coordenadas após orientação EXIF.')
        c(f, 'crop', 'Aplicar recorte', 'bool')
        c(f, 'crop_center', 'Centralizar', 'bool')
        c(f, 'crop_ratio', 'Proporção central', 'choice', choices=['livre','1:1','4:3','3:2','16:9','9:16'])
        for name, label in [('crop_x','Posição X'),('crop_y','Posição Y'),('crop_width','Largura do recorte'),('crop_height','Altura do recorte')]:
            c(f, name, label, limits=(1 if 'width' in name or 'height' in name else 0,30000))
        f = self.form(categories[3])
        c(f,'auto_orient','Orientar automaticamente pelo EXIF','bool')
        c(f,'angle','Rotação em graus (90, 180, 270 ou livre)',limits=(-360,360))
        c(f,'horizontal','Espelhar da esquerda para a direita','bool')
        c(f,'vertical','Espelhar de cima para baixo','bool')
        f = self.form(categories[4], 'Temperatura é um ajuste criativo dos canais vermelho e azul; não representa Kelvin.')
        for name, label, limits in [('brightness','Brilho',(-100,100)),('contrast','Contraste',(-100,100)),('saturation','Saturação (%)',(0,300)),('hue','Matiz (graus)',(-180,180)),('temperature','Temperatura',(-100,100)),('gamma','Gama',(.1,5)),('exposure','Exposição (EV)',(-5,5)),('sepia','Sépia (%)',(0,100))]:
            c(f,name,label,limits=limits)
        for name,label in [('auto_level','Níveis automáticos'),('auto_contrast','Contraste automático'),('normalize','Normalização'),('grayscale','Escala de cinza'),('negative','Inverter cores')]:
            c(f,name,label,'bool')
        f = self.form(categories[5], 'Um filtro por processamento. Raio define pixels/blocos/níveis; intensidade define sigma (desfoque/nitidez) ou percentual do limiar.')
        c(f,'effect','Efeito','choice',choices=[('Nenhum','nenhum'),('Desfoque gaussiano','desfoque'),('Nitidez','nitidez'),('Unsharp mask','unsharp'),('Redução de ruído','ruido'),('Mediana','mediana'),('Carvão','carvao'),('Pintura a óleo','oleo'),('Detecção de bordas','bordas'),('Relevo','relevo'),('Pixelização','pixelizar'),('Posterização','posterizar'),('Limiar','limiar'),('Vinheta','vinheta')])
        c(f,'radius','Raio / bloco / níveis',limits=(.1,100))
        c(f,'strength','Intensidade / sigma / limiar (%)',limits=(.1,100))
        c(f,'threshold','Limiar do unsharp (0–1)',limits=(0,1))
        f = self.form(categories[6])
        c(f,'background','Cor de fundo','color')
        c(f,'flatten','Remover transparência','bool')
        c(f,'remove_color','Remover fundo por cor','bool')
        c(f,'transparent_color','Cor a remover','color')
        c(f,'tolerance','Tolerância (%)',limits=(0,100))
        c(f,'trim','Aparar bordas uniformes / transparentes','bool')
        f = self.form(categories[7], 'A marca de imagem é dimensionada em relação ao seu próprio tamanho. Os deslocamentos seguem a âncora selecionada.')
        c(f,'watermark','Texto','text')
        image_field = c(f,'watermark_image','Arquivo de imagem (opcional)','text')
        b = QPushButton('Escolher imagem da marca')
        b.clicked.connect(lambda: self.choose_watermark(image_field))
        f.addRow(b)
        c(f,'font','Nome da fonte','text')
        c(f,'font_size','Tamanho da fonte',limits=(6,500))
        c(f,'watermark_color','Cor do texto','color')
        c(f,'opacity','Opacidade (%)',limits=(0,100))
        c(f,'gravity','Âncora','choice',choices=[('Inferior direita','SouthEast'),('Inferior esquerda','SouthWest'),('Superior direita','NorthEast'),('Superior esquerda','NorthWest'),('Centro','Center')])
        c(f,'margin','Margem do texto',limits=(0,10000))
        c(f,'watermark_scale','Escala da imagem (%)',limits=(1,500))
        c(f,'overlay_x','Deslocamento X da imagem',limits=(0,30000))
        c(f,'overlay_y','Deslocamento Y da imagem',limits=(0,30000))
        f = self.form(categories[8], 'Ao remover metadados, o perfil de cor pode ser mantido. Originais permanecem intactos. Dados GPS são sinalizados antes da preservação.')
        c(f,'strip','Remover metadados pessoais','bool')
        c(f,'keep_icc','Preservar perfil ICC ao remover metadados','bool')
        f = self.form(categories[9], 'Escolha a operação acima da lista. A ordem da lista define a mesclagem. Páginas: 1,3-5 ou 5-1; vazio inclui todas. Reordenar exporta a sequência informada sem rasterizar.')
        c(f,'dpi','DPI de renderização / tamanho original',limits=(36,600))
        c(f,'pages','Páginas / ordem','text')
        page_editor = QPushButton('Organizar páginas visualmente')
        page_editor.clicked.connect(self.edit_pages)
        f.addRow(page_editor)
        c(f,'page_size','Tamanho da página','choice',choices=['A4','A3','Carta','Original'])
        c(f,'landscape','Paisagem','bool')
        c(f,'page_margin','Margens (mm)',limits=(0,100))
        c(f,'page_fit','Posicionamento','choice',choices=[('Ajustar','ajustar'),('Preencher','preencher'),('Tamanho original','original')])
        f = self.form(categories[10], 'Selecione “Criar GIF animado” na operação. Largura e altura vêm de Redimensionar. Use Subir/Descer para ordenar. GIF tem paleta de até 256 cores.')
        c(f,'delay','Duração global (ms)',limits=(10,60000))
        c(f,'frame_delays','Durações individuais em ms (vírgulas)','text')
        c(f,'loops','Repetições (0 = infinito)',limits=(0,65535))
        c(f,'gif_fit','Normalizar quadros','choice',choices=[('Encaixar com fundo','ajustar'),('Preencher e recortar','preencher')])
        c(f,'optimize','Otimizar paleta / quadros','bool')
        b = QPushButton('Visualizar GIF selecionado')
        b.clicked.connect(self.play_gif)
        f.addRow(b)
        f = self.form(categories[11], 'Escolha a composição na operação. Sobreposição usa a primeira imagem como base; as demais usam os deslocamentos e a opacidade de Marca-d’água.')
        c(f,'columns','Colunas da grade',limits=(1,50))
        c(f,'spacing','Espaçamento (px)',limits=(0,2000))
        c(f,'canvas','Cor do canvas (ou transparent)','text')
        f = self.form(categories[12], '“Substituir” exige confirmação antes do lote. Mesmo assim, nenhum arquivo original pode ser substituído. Nomes duplicados dentro do lote são renomeados.')
        c(f,'conflict','Arquivos existentes','choice',choices=[('Renomear automaticamente','renomear'),('Ignorar','ignorar'),('Perguntar antes de iniciar','perguntar'),('Substituir com confirmação','substituir')])
        c(f,'prefix','Prefixo','text')
        c(f,'suffix','Sufixo','text')
        c(f,'numbered','Adicionar numeração','bool')
        c(f,'output_name','Nome para PDF / GIF / composição','text')
        c(f,'parallelism','Arquivos simultâneos',limits=(1,8))

    def options(self):
        values = {}
        for name, widget in self.controls.items():
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QLineEdit):
                value = widget.text()
            else:
                value = widget.value()
            values[name] = value
        values['operation'] = self.operation.currentData()
        return Options(**values)

    def set_control(self, name, value):
        widget = self.controls.get(name)
        if widget is None:
            return
        if isinstance(widget,QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget,QComboBox):
            i = widget.findData(value)
            if i >= 0:
                widget.setCurrentIndex(i)
        elif isinstance(widget,QLineEdit):
            widget.setText(str(value))
        else:
            widget.setValue(value)

    def restore_preferences(self):
        try:
            values = json.loads(self.settings.value('options', '{}'))
            for name, value in values.items():
                self.set_control(name,value)
        except (ValueError, TypeError):
            self.status.setText('Preferências inválidas; usando os padrões.')

    def reset_form(self, form):
        default = Options()
        names = [name for name, widget in self.controls.items() if form.parentWidget().isAncestorOf(widget)]
        for name in names:
            self.set_control(name,getattr(default,name))

    def pick_color(self, widget):
        color = QColorDialog.getColor(QColor(widget.text()), self, 'Escolher cor')
        if color.isValid():
            widget.setText(color.name())

    def apply_preset(self, index):
        sizes = [(1920,1080),(1920,1080),(3840,2160),(1080,1350),(1080,1920),(256,256)]
        if index:
            self.set_control('width', sizes[index][0])
            self.set_control('height', sizes[index][1])
            self.set_control('resize','ajustar')

    def choose_watermark(self, field):
        path,_ = QFileDialog.getOpenFileName(self,'Imagem da marca-d’água')
        if path:
            field.setText(path)

    def operation_changed(self):
        value = self.operation.currentData()
        if value and ('pdf' in value):
            self.navigation.setCurrentRow(9)
        elif value and 'gif' in value:
            self.navigation.setCurrentRow(10)
        elif value in {'horizontal','vertical','grade','sobrepor'}:
            self.navigation.setCurrentRow(11)
        self.schedule_preview()

    def choose_files(self):
        if self.is_busy():
            return
        files,_ = QFileDialog.getOpenFileNames(self,'Adicionar imagens e PDFs','', 'Imagens e PDFs ('+' '.join('*'+ext for ext in sorted(EXTENSIONS))+');;Todos os arquivos (*)')
        self.add_paths([Path(p) for p in files])

    def choose_folder(self):
        if self.is_busy():
            return
        folder = QFileDialog.getExistingDirectory(self,'Adicionar pasta e subpastas')
        if folder:
            self.add_paths([Path(folder)])

    def add_paths(self, paths):
        if not paths or self.is_busy():
            return
        importer = ImportJob(paths)
        self.imports.append(importer)
        self.status.setText('Lendo informações dos arquivos…')
        self.execute.setEnabled(False)
        importer.loaded.connect(self.loaded_files)
        importer.finished.connect(lambda: self.import_finished(importer))
        importer.start()

    def import_finished(self, importer):
        self.imports.remove(importer)
        self.execute.setEnabled(not self.imports and not self.is_busy())
        importer.deleteLater()

    def loaded_files(self, entries):
        for path, dimensions, size, frames, gps in entries:
            if path not in self.sources:
                self.sources.append(path)
                self.metadata[path] = (dimensions, size, frames, gps)
        self.rebuild_table()
        self.status.setText(f'{len(self.sources)} arquivo(s) na lista. Arraste para adicionar mais.')
        if self.sources and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def rebuild_table(self):
        self.table.setRowCount(len(self.sources))
        for row, path in enumerate(self.sources):
            dimensions, size, frames, gps = self.metadata.get(path, ('A verificar', path.stat().st_size if path.exists() else 0, 1, False))
            for col, value in enumerate([path.name, path.suffix.upper().lstrip('.'), dimensions, f'{size/1024:.1f} KB' if size < 1024**2 else f'{size/1024**2:.1f} MB', 'aguardando']):
                item = QTableWidgetItem(value)
                item.setToolTip(str(path) + (f'\n{frames} quadros/páginas. GPS: sim' if gps else f'\n{frames} quadros/páginas.'))
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 34)
        self.count_label.setText(f'{len(self.sources)} arquivos')
        self.row_results.clear()

    def move(self, delta):
        if self.is_busy():
            return
        row = self.table.currentRow()
        target = row + delta
        if row >= 0 and 0 <= target < len(self.sources):
            self.sources[row], self.sources[target] = self.sources[target], self.sources[row]
            self.rebuild_table()
            self.table.selectRow(target)

    def remove_selected(self):
        if self.is_busy():
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()},reverse=True)
        for row in rows:
            del self.sources[row]
        self.rebuild_table()

    def clear(self):
        if not self.is_busy():
            self.sources.clear()
            self.rebuild_table()
            self.before.scene().clear()
            self.after.scene().clear()
            self.before.pixmap = self.after.pixmap = None

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self,'Pasta de saída', self.output.text())
        if folder:
            self.output.setText(folder)

    def open_output(self):
        folder = Path(self.output.text()).expanduser()
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))
        else:
            QMessageBox.information(self,'Pasta de saída','A pasta será criada ao processar o primeiro lote.')

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not self.is_busy():
            event.acceptProposedAction()

    def dropEvent(self,event):
        self.add_paths([Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()])

    def schedule_preview(self, *_):
        self.timer.start()

    def refresh_preview(self):
        if self.is_busy():
            return
        if self.preview_job and self.preview_job.isRunning():
            self.preview_pending = True
            self.preview_job.cancel.set()
            return
        row = self.table.currentRow()
        if row < 0 or row >= len(self.sources) or not self.magick.executable:
            return
        self.preview_pending = False
        options = self.options()
        self.preview_info.setText('Preparando prévia…')
        self.preview_job = PreviewJob(self.magick, self.sources[row], options, self.preview_folder.name)
        self.preview_job.ready.connect(self.preview_ready)
        self.preview_job.failed.connect(lambda error: self.preview_info.setText('Prévia indisponível: ' + error[:240]))
        self.preview_job.finished.connect(self.preview_finished)
        self.preview_job.start()

    def preview_finished(self):
        if self.preview_pending:
            self.timer.start(50)

    def preview_ready(self, before, after, description):
        if self.preview_pending:
            return
        self.before.show_image(before)
        self.after.show_image(after)
        row = self.table.currentRow()
        if 0 <= row < len(self.sources):
            try:
                with Image.open(self.sources[row]) as im:
                    oriented = ImageOps.exif_transpose(im)
                    self.before.source_size = oriented.size
            except (OSError, ValueError):
                self.before.source_size = None
        note = ' · Prévia individual; o conjunto é gerado ao executar.' if self.options().operation in GROUPED else ' · Primeiro quadro/página; saída final usa o original.'
        self.preview_info.setText(description + note)

    def fit_preview(self):
        self.before.fit()
        self.after.fit()

    def actual_size(self):
        for view in [self.before, self.after]:
            view.resetTransform()

    def toggle_crop(self, checked):
        self.before.select_crop = checked
        self.before.setDragMode(QGraphicsView.DragMode.NoDrag if checked else QGraphicsView.DragMode.ScrollHandDrag)

    def visual_crop(self,x,y,w,h):
        for name,value in [('crop',True),('crop_center',False),('crop_ratio','livre'),('crop_x',x),('crop_y',y),('crop_width',w),('crop_height',h)]:
            self.set_control(name,value)
        self.navigation.setCurrentRow(2)

    def is_busy(self):
        return bool(self.job and self.job.isRunning())

    def start(self, *_):
        if self.is_busy() or self.imports:
            return
        if not self.sources:
            QMessageBox.information(self,'Adicionar arquivos','Adicione pelo menos um arquivo antes de executar.')
            return
        options = self.options()
        if not self.output.text().strip():
            QMessageBox.warning(self,'Pasta de saída','Escolha uma pasta de saída.')
            return
        from PIL import ImageColor
        try:
            for color in [options.background, options.transparent_color, options.watermark_color]:
                ImageColor.getrgb(color)
            if options.canvas != 'transparent':
                ImageColor.getrgb(options.canvas)
        except ValueError as exc:
            QMessageBox.warning(self,'Cor inválida',str(exc))
            return
        if options.conflict in {'substituir','perguntar'}:
            answer = QMessageBox.question(self,'Confirmar política de saída', 'Permitir substituir arquivos que já existam na pasta de saída? Os originais serão protegidos. Escolha Não para renomear automaticamente.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            options.conflict = 'substituir' if answer == QMessageBox.StandardButton.Yes else 'renomear'
        if not options.strip and any(self.metadata.get(p,('',0,1,False))[3] for p in self.sources):
            if QMessageBox.question(self,'Localização nos metadados','Há imagens com dados GPS. Preservar esses metadados na saída?') != QMessageBox.StandardButton.Yes:
                return
        self.settings.setValue('options',json.dumps(asdict(options),ensure_ascii=False))
        self.settings.setValue('output',self.output.text())
        self.results = []
        self.completed.clear()
        self.row_results.clear()
        self.progress.setValue(0)
        for row in range(len(self.sources)):
            self.table.item(row,4).setText('aguardando')
        self.job = Job(Processor(self.magick), list(self.sources), Path(self.output.text()), options)
        self.job.update.connect(self.task_update)
        self.job.progress.connect(self.file_progress)
        self.job.done.connect(self.batch_done)
        self.job.error.connect(self.batch_error)
        self.job.finished.connect(self.unbusy)
        self.set_busy(True)
        self.status.setText('Processando… Os originais permanecem intactos.')
        self.job.start()

    def set_busy(self, busy):
        for widget in [self.execute,self.add_file,self.add_folder,self.up,self.down,self.remove,self.clear_button,self.operation,self.stack,self.output]:
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.retry_button.setEnabled(not busy and any(r.state == 'falhou' for r in self.results))

    def unbusy(self):
        self.set_busy(False)

    def task_update(self,row,state,result):
        if row >= self.table.rowCount():
            return
        self.table.item(row,4).setText(state)
        color = '#82cfb0' if state == 'concluído' else '#ff9b9b' if state == 'falhou' else '#c1c7e0'
        self.table.item(row,4).setForeground(QColor(color))
        if result:
            self.row_results[row] = result
            self.completed.add(row)
            self.progress.setValue(round(len(self.completed)*100 / max(1,len(self.sources))))

    def file_progress(self,row,value):
        if row < self.table.rowCount() and row not in self.completed:
            phases = {1:'validado',2:'codificado',3:'verificado'}
            if value in phases:
                self.table.item(row,4).setText(f'processando · {phases[value]}')

    def batch_done(self,results):
        self.results = results
        count = Counter(r.state for r in results)
        self.progress.setValue(100)
        self.status.setText(f"Lote finalizado · {count['concluído']} concluído(s) · {count['falhou']} falha(s) · {count['ignorado']} ignorado(s) · {count['cancelado']} cancelado(s)." + (' Operação conjunta: contagem por conjunto.' if self.options().operation in GROUPED else ''))
        self.report_button.setEnabled(True)
        self.retry_button.setEnabled(bool(count['falhou']))
        if count['falhou']:
            self.show_text('Resumo do processamento','\n\n'.join(f'{r.source}\n{r.error}' for r in results if r.state == 'falhou'))

    def batch_error(self,message):
        self.status.setText('O lote não pôde ser iniciado.')
        self.show_text('Falha no lote',message)

    def cancel(self):
        if self.is_busy():
            self.job.cancel.set()
            self.status.setText('Cancelando processos e removendo saídas temporárias…')
            self.cancel_button.setEnabled(False)

    def retry(self):
        failed = {r.source for r in self.results if r.state == 'falhou'}
        if 'Conjunto de arquivos' not in failed:
            self.sources = [p for p in self.sources if str(p) in failed]
            self.rebuild_table()
        self.start()

    def save_report(self):
        filename,_ = QFileDialog.getSaveFileName(self,'Exportar relatório','relatorio.json','JSON (*.json);;CSV (*.csv)')
        if filename:
            try:
                export_report(Path(filename),self.results)
            except OSError as exc:
                QMessageBox.warning(self,'Falha ao exportar',str(exc))

    def show_details(self, *_):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.sources):
            return
        result = self.row_results.get(row)
        text = str(self.sources[row]) + '\n'
        if result:
            text += json.dumps(result.dictionary(),ensure_ascii=False,indent=2)
        else:
            text += str(self.metadata.get(self.sources[row], 'Informações ainda não disponíveis.'))
        self.show_text('Detalhes do arquivo',text)

    def show_text(self,title,text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(780,480)
        layout = QVBoxLayout(dialog)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        layout.addWidget(box)
        self.button('Fechar',dialog.accept,layout)
        dialog.exec()

    def diagnostics(self):
        import shutil
        dialog = QDialog(self)
        dialog.setWindowTitle('Diagnóstico e dependências')
        dialog.resize(840,560)
        layout = QVBoxLayout(dialog)
        description = QLabel('ImageMagick processa imagens; pypdf preserva a estrutura de PDFs. Ghostscript é usado apenas quando exigido por um delegate.')
        description.setWordWrap(True)
        layout.addWidget(description)
        field = QLineEdit(self.magick.executable)
        layout.addWidget(field)
        b = QPushButton('Localizar magick.exe')
        def locate():
            path,_ = QFileDialog.getOpenFileName(dialog,'Localizar ImageMagick 7','','Executável (magick.exe)')
            if path:
                field.setText(path)
        b.clicked.connect(locate)
        layout.addWidget(b)
        text = QPlainTextEdit(self.magick.version + '\n\nGhostscript: ' + str(shutil.which('gswin64c') or 'não encontrado no PATH') + '\n\n' + self.magick.details)
        text.setReadOnly(True)
        layout.addWidget(text)
        def apply():
            self.settings.setValue('magick',field.text())
            QMessageBox.information(dialog,'Configuração salva','Reabra o aplicativo para atualizar os formatos disponíveis.')
            dialog.accept()
        self.button('Salvar e fechar',apply,layout)
        dialog.exec()

    def play_gif(self):
        from PySide6.QtGui import QMovie
        row = self.table.currentRow()
        path = None
        if row in self.row_results:
            path = next((p for p in self.row_results[row].outputs if p.lower().endswith('.gif')),None)
        if path is None and row >= 0 and self.sources[row].suffix.lower() == '.gif':
            path = str(self.sources[row])
        if path is None:
            QMessageBox.information(self,'Prévia animada','Selecione um GIF existente ou execute a criação e selecione um item do conjunto.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Prévia da animação')
        layout = QVBoxLayout(dialog)
        label = QLabel()
        movie = QMovie(path)
        label.setMovie(movie)
        layout.addWidget(label)
        movie.start()
        self.button('Fechar',dialog.accept,layout)
        dialog.exec()
        movie.stop()

    def edit_pages(self):
        row=self.table.currentRow()
        if row<0 or self.sources[row].suffix.lower()!='.pdf':
            QMessageBox.information(self,'Organizar páginas','Selecione um PDF na lista de arquivos.')
            return
        dialog=QDialog(self)
        dialog.setWindowTitle('Organizar páginas do PDF')
        dialog.resize(820,620)
        layout=QVBoxLayout(dialog)
        status=QLabel('Preparando miniaturas… Arraste para reordenar; Delete remove a página da seleção.')
        status.setWordWrap(True)
        layout.addWidget(status)
        pages=QListWidget()
        pages.setViewMode(QListWidget.ViewMode.IconMode)
        pages.setIconSize(QSize(150,150))
        pages.setGridSize(QSize(175,185))
        pages.setMovement(QListWidget.Movement.Snap)
        pages.setResizeMode(QListWidget.ResizeMode.Adjust)
        pages.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        pages.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(pages)
        remove_action=QAction(pages)
        remove_action.setShortcut(QKeySequence('Delete'))
        def remove():
            for item in pages.selectedItems():
                pages.takeItem(pages.row(item))
        remove_action.triggered.connect(remove)
        pages.addAction(remove_action)
        remove_button=QPushButton('Remover páginas selecionadas')
        remove_button.clicked.connect(remove)
        layout.addWidget(remove_button)
        apply=QPushButton('Usar esta ordem')
        apply.setEnabled(False)
        layout.addWidget(apply)
        def use_order():
            if not pages.count():
                status.setText('Mantenha pelo menos uma página.')
                return
            sequence=','.join(str(pages.item(i).data(Qt.ItemDataRole.UserRole)+1) for i in range(pages.count()))
            self.set_control('pages',sequence)
            self.operation.setCurrentIndex(self.operation.findData('reordenar_pdf'))
            dialog.accept()
        apply.clicked.connect(use_order)
        job=PageThumbnailJob(self.sources[row])
        self.thumbnail_jobs.append(job)
        def loaded(items):
            if not dialog.isVisible():
                return
            try:
                order=page_indices(self.controls['pages'].text(),len(items))
            except ValueError:
                order=list(range(len(items)))
            for i in order:
                pix=QPixmap()
                pix.loadFromData(items[i][1])
                item=QListWidgetItem(QIcon(pix),f'Página {i+1}')
                item.setData(Qt.ItemDataRole.UserRole,i)
                pages.addItem(item)
            status.setText('Arraste as miniaturas para mudar a ordem. Delete remove páginas da seleção; o original permanece intacto.')
            apply.setEnabled(True)
        job.loaded.connect(loaded)
        job.failed.connect(status.setText)
        job.finished.connect(lambda: self.thumbnail_jobs.remove(job))
        dialog.finished.connect(lambda _: job.cancel.set())
        job.start()
        dialog.exec()

    def closeEvent(self,event):
        if self.is_busy() or self.imports or self.thumbnail_jobs:
            if self.is_busy():
                self.cancel()
            self.status.setText('Aguarde o encerramento das operações antes de fechar.')
            event.ignore()
            return
        if self.preview_job and self.preview_job.isRunning():
            self.preview_job.cancel.set()
            self.preview_job.wait(5000)
            if self.preview_job.isRunning():
                event.ignore()
                return
        self.settings.setValue('geometry',self.saveGeometry())
        self.settings.setValue('options',json.dumps(asdict(self.options()),ensure_ascii=False))
        self.settings.setValue('output',self.output.text())
        self.preview_folder.cleanup()
        super().closeEvent(event)
