import sys
import os
import platform
import time
from copy import copy
from math import log, tan, pi, atan, exp, floor
from threading import Event, Thread
from PyQt5.QtWidgets import QApplication, QWidget, QMainWindow, QLabel, \
    QToolBar, QAction, QStatusBar, QCheckBox, QDockWidget, QPlainTextEdit, \
    QTabWidget, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, \
    QGraphicsRectItem, QGraphicsTextItem, QLineEdit, QFileDialog, QComboBox, \
    QProgressBar, QVBoxLayout, QPushButton, QSpacerItem, QSizePolicy, \
    QFormLayout, QHBoxLayout
from PyQt5.QtCore import Qt, QSize, QRunnable, pyqtSignal, pyqtSlot, QThreadPool, \
    QObject, QSettings, QTimer
from PyQt5.QtGui import QIcon, QFont, QColor, QPalette, QPixmap, QTextCursor, \
    QBrush, QPen
import O4_Version
import O4_Imagery_Utils as IMG
import O4_File_Names as FNAMES
import O4_Geo_Utils as GEO
import O4_Vector_Utils as VECT
import O4_Vector_Map as VMAP
import O4_Mesh_Utils as MESH
import O4_Mask_Utils as MASK
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI
import O4_DEM_Utils as DEM
import O4_Config_Utils as CFG


list_del_ckbtn = ['OSM data','Mask data','Jpeg imagery','Tile (whole)','Tile (textures)']
list_do_ckbtn  = ['Assemble vector data','Triangulate 3D mesh','Draw water masks','Build imagery/DSF','Extract overlays','Read per tile cfg']

class Ortho4XP_GUI:
    def __init__(self):
        UI.gui = self

        self.app = QApplication([])
        settings = QSettings('Ortho4XP', 'Ortho4XP')
        self.window = MainWindow(settings)
        self.model = Model(settings)
        self.buildDelegate = BuildDelegate()

        self.model.removeAllTiles.connect(self.window.tileCanvas.removeAllTiles)
        self.model.newTileState.connect(self.window.tileCanvas.setTileState)
        self.window.bug.triggered.connect(self.model.refreshTiles)
        self.window.workDir.textChanged.connect(self.model.setWorkingDir)
        self.model.workingDirChanged.connect(self.window.workDir.setText)
        self.window.closing.connect(self.model.finalize)
        self.window.tileCanvas.linkRequested.connect(self.model.toggleLink)
        self.window.tileCanvas.tileSelected.connect(self.buildDelegate.addRemoveTile)
        self.model.linkStateChanged.connect(self.window.tileCanvas.setTileIsLinked)
        self.model.progressChanged.connect(self.window.setProgress)
        self.window.configWindow.customDemCb.currentTextChanged.connect(self.model.setCustomDem)
        self.window.defaultWebsite.currentTextChanged.connect(self.model.setDefaultWebsite)
        self.model.defaultWebsiteChanged.connect(self.window.defaultWebsite.setCurrentText)
        self.window.defaultZl.currentTextChanged.connect(self.model.setDefaultZl)
        self.model.defaultZlChanged.connect(self.window.defaultZl.setCurrentText)

        for cbname, cbw in self.window.batchToolbox.checkboxes:
            cbw.stateChanged.connect(lambda st, cbn = cbname: self.buildDelegate.setCheckBoxState(cbn, st != Qt.Unchecked))

        self.window.batchToolbox.deleteButton.clicked.connect(self.buildDelegate.deleteData)
        self.window.batchToolbox.buildButton.clicked.connect(self.buildDelegate.build)
        self.buildDelegate.buildRequest.connect(self.model.buildTiles)
        self.buildDelegate.deleteRequest.connect(self.model.deleteData)
        self.model.tilesQueued.connect(self.window.tileCanvas.queueTiles)

    def mainloop(self):
        self.window.show()
        self.model.start()
        self.app.exec_()

    def setProgress(self, nbr, value):
        self.model.setProgressAsync(nbr, value)

    def notifyTileCompleted(self, id):
        self.model.notifyTileCompletedAsync(id)

class Console(QPlainTextEdit):
    writeSignal = pyqtSignal(str)
    def __init__(self, parent = None):
        super(Console, self).__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New"))
        self.writeSignal.connect(self.doWrite)

# Write can be called from any thread so do it through a signal
    def write(self, line):
        self.writeSignal.emit(line)

    @pyqtSlot(str)
    def doWrite(self, line):
        cursor = self.textCursor()
        cursorOrig = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.insertPlainText(line)
        self.setTextCursor(cursorOrig)
        verticalBar = self.verticalScrollBar()
        verticalBar.setValue(verticalBar.maximum())

    def flush(self):
        pass

class Color(QWidget):
    def __init__(self, color, *args, **kwargs):
        super(Color, self).__init__(*args, **kwargs)
        self.setAutoFillBackground(True)

        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(color))
        self.setPalette(palette)

class MainWindow(QMainWindow):
    zl_list         = ['12','13','14','15','16','17','18']
    closing = pyqtSignal()
    def __init__(self, settings, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        self.settings = settings

        self.scrollBarsRestored = False
        self.setWindowTitle("Ortho4XP (New Look)")

        toolbar = PersistentToolBar("Main toolbar")
        toolbar.setObjectName("MainToolbar")
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        self.tileCanvas = TileCanvas(self)
        self.tileView = QGraphicsView(self.tileCanvas)
        self.setCentralWidget(self.tileView)

        self.dockedTileView = QGraphicsView(self.tileCanvas)
        tileDocker = self.dock('Overview', Qt.RightDockWidgetArea, self.dockedTileView)
        tileDocker.setObjectName("TileViewDock")

        self.batchToolbox = BuildToolbox()
        batchDocker = self.dock('Batch Build', Qt.LeftDockWidgetArea, self.batchToolbox)
        batchDocker.setObjectName('BatchBuild')

        self.configWindow = ConfigWindow()
        configDocker = self.dock('Configuration', Qt.TopDockWidgetArea, self.configWindow)
        configDocker.setObjectName('ConfigWindow')

        statusbar = QStatusBar()

        self.progress = [QProgressBar(), QProgressBar(), QProgressBar()]
        for pb in self.progress:
            pb.setMinimum(0)
            pb.setMaximum(100)
            pb.setValue(0)
            statusbar.addWidget(pb)

        self.setStatusBar(statusbar)

        console = Console(self)
        consoleDocker = self.dock('Console', Qt.BottomDockWidgetArea, console)
        consoleDocker.setObjectName("ConsoleDock")

        self.stdout_orig = sys.stdout
        sys.stdout = console

        toolbar.addSeparator()

        showConsole = QAction(QIcon(os.path.join('icons', 'application-text.png')), \
            'Show console', self)
        showConsole.setStatusTip('Show console window')
        showConsole.setCheckable(True)
        showConsole.toggled.connect(consoleDocker.setVisible)
        consoleDocker.visibilityChanged.connect(showConsole.setChecked)
        toolbar.addAction(showConsole)

        showTiles = QAction(QIcon(os.path.join('icons', 'globe.png')), \
            'Show tiles', self)
        showTiles.setStatusTip('Show tile view')
        showTiles.setCheckable(True)
        showTiles.toggled.connect(tileDocker.setVisible)
        tileDocker.visibilityChanged.connect(showTiles.setChecked)
        toolbar.addAction(showTiles)

        build = QAction(QIcon(os.path.join('icons', 'hammer.png')), \
            'Batch build', self)
        build.setStatusTip('Show batch build options')
        build.setCheckable(True)
        build.toggled.connect(batchDocker.setVisible)
        batchDocker.visibilityChanged.connect(build.setChecked)
        toolbar.addAction(build)

        configAction = QAction(QIcon(os.path.join('icons', 'wrench-screwdriver.png')), \
            'Configuration', self)
        configAction.setStatusTip('Show configuration window')
        configAction.setCheckable(True)
        configAction.toggled.connect(configDocker.setVisible)
        configDocker.visibilityChanged.connect(configAction.setChecked)
        toolbar.addAction(configAction)

        toolbar.addSeparator()

        self.bug = QAction(QIcon(os.path.join('icons', 'bug.png')), \
            'Any random action', self)
        self.bug.setStatusTip('Any random action')
        toolbar.addAction(self.bug)

        stop = QAction(QIcon(os.path.join('icons', 'cross-circle.png')), \
            'Abort operation', self)
        stop.setStatusTip('Abort ongoing operation')
        toolbar.addAction(stop)
        stop.triggered.connect(lambda _: abortOperation())

        workDirToolbar = QToolBar('Working folder')
        workDirToolbar.setObjectName('WorkDirToolbar')
        workDirToolbar.setIconSize(QSize(16, 16))
        self.addToolBar(workDirToolbar)

        workDirToolbar.addWidget(QLabel("Custom build folder:"))
        self.workDir = QLineEdit(self)
        self.workDir.setMaximumWidth(500)
        workDirToolbar.addWidget(self.workDir)

        workDirButton = QAction(QIcon(os.path.join('icons', 'folder-horizontal.png')), \
            'Choose folder', self)
        workDirButton.setStatusTip('Choose folder')
        workDirButton.triggered.connect(lambda _: self.chooseWorkFolder())
        workDirToolbar.addAction(workDirButton)

        workDirToolbar.addSeparator()

        map_list = sorted([provider_code for provider_code in set(IMG.providers_dict) if IMG.providers_dict[provider_code]['in_GUI']]+sorted(set(IMG.combined_providers_dict)))
        map_list = [provider_code for provider_code in map_list if provider_code!='SEA']

        self.defaultWebsite = QComboBox()
        self.defaultWebsite.setEditable(False)
        self.defaultWebsite.addItems(map_list)
        workDirToolbar.addWidget(self.defaultWebsite)

        self.defaultZl = QComboBox()
        self.defaultZl.setEditable(False)
        self.defaultZl.addItems(self.zl_list)
        workDirToolbar.addWidget(self.defaultZl)

        safeRestore(self.settings, 'mainWindow/geometry', self.restoreGeometry)
        safeRestore(self.settings, 'mainWindow/state', self.restoreState)

    def chooseWorkFolder(self):
        dialog = QFileDialog(caption = 'Choose Custom Build Folder')
        dialog.setFileMode(QFileDialog.Directory)
        if (dialog.exec()):
            self.workDir.setText(dialog.selectedFiles()[0] + '/')

    def dock(self, title, area, widget):
        dockWidget = QDockWidget(title)
        dockWidget.setFeatures(\
            QDockWidget.DockWidgetClosable | \
            QDockWidget.DockWidgetMovable | \
            QDockWidget.DockWidgetFloatable)
        dockWidget.setWidget(widget)
        dockWidget.setVisible(False)
        self.addDockWidget(area, dockWidget)
        return dockWidget

    def closeEvent(self, evt):
        sys.stdout = self.stdout_orig
        self.settings.setValue('mainWindow/geometry', self.saveGeometry())
        self.settings.setValue('mainWindow/state', self.saveState())
        self.settings.setValue('tileView/vertical', self.tileView.verticalScrollBar().value())
        self.settings.setValue('tileView/horizontal', self.tileView.horizontalScrollBar().value())
        self.settings.setValue('dockedTileView/vertical', self.dockedTileView.verticalScrollBar().value())
        self.settings.setValue('dockedTileView/horizontal', self.dockedTileView.horizontalScrollBar().value())
        self.closing.emit()
#        self.settings.setValue('config/workDir', self.workDir.text())
        super(MainWindow, self).closeEvent(evt)

    def showEvent(self, evt):
        super(MainWindow, self).showEvent(evt)
        if not self.scrollBarsRestored:
            safeRestore(self.settings, 'tileView/vertical', self.tileView.verticalScrollBar().setValue)
            safeRestore(self.settings, 'tileView/horizontal', self.tileView.horizontalScrollBar().setValue)
            safeRestore(self.settings, 'dockedTileView/vertical', self.dockedTileView.verticalScrollBar().setValue)
            safeRestore(self.settings, 'dockedTileView/horizontal', self.dockedTileView.horizontalScrollBar().setValue)
            self.scrollBarsRestored = True

    @pyqtSlot(int, int)
    def setProgress(self, nbr, value):
        self.progress[nbr].setValue(value)

class BuildToolbox(QWidget):

    def __init__(self, parent = None):
        super(BuildToolbox, self).__init__(parent)
        self.checkboxes = []
        layout = QVBoxLayout()
        layout.addWidget(QLabel('<h1><i>Delete</i></h1>'))
        for cb in list_del_ckbtn:
            widget = QCheckBox(cb)
            self.checkboxes.append((cb, widget))
            layout.addWidget(widget)
        self.deleteButton = QPushButton('Delete')
        layout.addWidget(self.deleteButton)
        layout.addSpacing(20)
        layout.addWidget(QLabel('<h1><i>Batch build</i></h1>'))
        for cb in list_do_ckbtn:
            widget = QCheckBox(cb)
            self.checkboxes.append((cb, widget))
            layout.addWidget(widget)
        self.buildButton = QPushButton('Batch build')
        layout.addWidget(self.buildButton)
        layout.addSpacing(20)
        layout.addStretch()

        self.setLayout(layout)

        self.setMaximumWidth(layout.minimumSize().width())

class ConfigWindow(QWidget):
    def __init__(self, parent = None):
        super(ConfigWindow, self).__init__(parent)

        layout = QFormLayout()
        innerLayout = QHBoxLayout()
        innerLayout.setSpacing(0)
        self.customDemCb = QComboBox()
        self.customDemCb.setEditable(True)
        self.customDemCb.addItems([''] + list(DEM.available_sources[1::2]))
        innerLayout.addWidget(self.customDemCb)
        chooseButton = QPushButton(QIcon(os.path.join('icons', 'folder-horizontal.png')), '')
        chooseButton.setFlat(True)
        chooseButton.setStyleSheet('padding: 1px;')
        chooseButton.clicked.connect(self.chooseFile)
        innerLayout.addWidget(chooseButton)
        layout.addRow('custom_dem', innerLayout)
        self.setLayout(layout)

    @pyqtSlot()
    def chooseFile(self):
        dialog = QFileDialog(caption = 'Choose DEM file')
        if dialog.exec():
            text = self.customDemCb.lineEdit().text()
            newText = dialog.selectedFiles()[0]
            if text:
                newText = text + ';' + newText
            self.customDemCb.setEditText(newText)

class PersistentToolBar(QToolBar):
    def hideEvent(self, evt):
        QTimer.singleShot(100, self.show)

class TileInfo(object):
    def __init__(self, provider, zoomlevel):
        self.provider = provider
        self.zoomlevel = zoomlevel
        self.isLinked = False

class TileCanvas(QGraphicsScene):
    linkRequested = pyqtSignal(object)
    tileSelected = pyqtSignal(object, bool)
    def __init__(self, parent = None):
        super(TileCanvas, self).__init__(0, 0, 16384, 16384, parent)
        self.tileIndex = {}
        self.selectedTiles = set()
        self.queuedTiles = set()
        for x in range(8):
            for y in range(8):
                fname = os.path.join('Utils', 'Earth', 'Earth2_ZL6_{x}_{y}.jpg'.format(x=x, y=y))
                item = QGraphicsPixmapItem(QPixmap(fname))
                item.setPos(x * 2048, y * 2048)
                self.addItem(item)

    @pyqtSlot(object, object)
    def setTileState(self, id, info):
        tile = None
        if id in self.tileIndex:
            tile = self.tileIndex[id]
        else:
            tile = TileItem(id)
            self.tileIndex[id] = tile
            self.addItem(tile)
        tile.info = info
        return tile

    @pyqtSlot(object, bool)
    def setTileIsLinked(self, id, isLinked):
        if id in self.tileIndex:
            self.tileIndex[id].isLinked = isLinked

    @pyqtSlot(object)
    def queueTiles(self, ids):
        for id in ids:
            tile = self.tileIndex[id]
            tile.isQueued = True
            self.tileSelected.emit(id, False)

    @pyqtSlot(object)
    def removeTile(self, id):
        if id in self.tileIndex:
            self.removeItem(self.tileIndex[id])
            del self.tileIndex[id]

    @pyqtSlot()
    def removeAllTiles(self):
        for item in self.items():
            if isinstance(item, TileItem):
                self.removeItem(item)
        self.tileIndex = {}

    def findTile(self, pos):
        tiles = [item for item in self.items(pos) if isinstance(item, TileItem)]
        return tiles[0] if tiles else None

    def mousePressEvent(self, evt):
        if evt.modifiers() == Qt.MetaModifier if platform.system() == 'Darwin' else Qt.ControlModifier:
            tile = self.findTile(evt.scenePos())
            if tile:
                self.linkRequested.emit(tile.id)
        elif evt.modifiers() == Qt.NoModifier and evt.buttons() == Qt.LeftButton:
            pos = evt.scenePos()
            tile = self.findTile(pos)
            if tile:
                tile.isSelected = not tile.isSelected
            else:
                lat = int(floor(pixelYToLat(pos.y())))
                lon = int(floor(pixelXToLon(pos.x())))
                if lat <= 84 and lat >= -85:
                    tile = self.setTileState((lat, lon), None)
                    tile.isSelected = True
            if tile:
                self.tileSelected.emit(tile.id, tile.isSelected)

class TileItem(QGraphicsRectItem):
    normalFont = QFont("Courier New", pointSize = 10)
    linkFont = QFont("Courier New", pointSize = 10, weight = QFont.Black)
    noBrush = QBrush(Qt.transparent, Qt.NoBrush)
    noPen = QPen(noBrush, 0)
    infoPenBrush = QBrush(Qt.black)
    infoPen = QPen(infoPenBrush, 1)
    selectBrush = QBrush(QColor(0xFF, 0x00, 0x00, 0x20))
    queuedBrush = QBrush(QColor(0xFF, 0x00, 0xFF, 0x20))

    def __init__(self, id):
        super(TileItem, self).__init__()
        self._id = id
        self._info = None
        self._selected = False
        self._queued = False
        self._provider = None # QGraphicsTextItem('', self)
        self._zl = None # QGraphicsTextItem('', self)

        (lat, lon) = id
        [y0, y1] = map(latToPixelY, [lat, lat + 1])
        [x0, x1] = map(lonToPixelX, [lon, lon + 1])
        self.w = x1 - x0
        self.h = y0 - y1
        self.setRect(0, -self.h, self.w, self.h)
        self.setPos(x0, y0)

    def updateView(self):
        if self._info:
            self.setPen(self.infoPen)
            if not self._provider:
                self._provider = QGraphicsTextItem(self._info.provider, self)
            else:
                self._provider.setPlainText(self._info.provider)
                self._provider.setVisible(True)
            if not self._zl:
                self._zl = QGraphicsTextItem(self._info.zoomlevel, self)
            else:
                self._zl.setPlainText(self._info.zoomlevel)
                self._zl.setVisible(True)

            font = self.linkFont if self._info.isLinked else self.normalFont
            font.setUnderline(self._info.isLinked)
            self._provider.setFont(font)
            self._zl.setFont(font)
            pbr = self._provider.boundingRect()
            self._provider.setPos((self.w - pbr.width()) / 2, -self.h / 2 - pbr.height())
            self._zl.setPos((self.w - self._zl.boundingRect().width()) / 2, -self.h / 2)
        else:
            self.setPen(self.noPen)
            if self._provider:
                self._provider.setVisible(False)
            if self._zl:
                self._zl.setVisible(False)

        self.setBrush(self.selectBrush if self._selected \
            else self.queuedBrush if self._queued else self.noBrush)

    @property
    def id(self):
        return self._id

    @property
    def info(self):
        return None if not self._info else copy(self._info)

    @info.setter
    def info(self, info):
        self._info = None if not info else copy(info)
        self._queued = False
        self.updateView()

    @property
    def isSelected(self):
        return self._selected

    @isSelected.setter
    def isSelected(self, s):
        self._selected = s
        self.updateView()

    @property
    def isQueued(self):
        return self._queued

    @isQueued.setter
    def isQueued(self, q):
        self._queued = q
        if q:
            self._selected = False
        self.updateView()

    @property
    def isLinked(self):
        return self._info and self._info.isLinked

    @isLinked.setter
    def isLinked(self, ln):
        if self._info:
            self._info.isLinked = ln
        self.updateView()

class Worker(Thread):
    def __init__(self, *args, **kwargs):
        super(Worker, self).__init__(*args, **kwargs)
        self._cancel = Event()

    def cancel(self):
        self._cancel.set()

    def is_canceled(self):
        return self._cancel.is_set()

class TileTask():
    def __init__(self):
        self.tiles = set()
        self.toDo = {}

class BuildDelegate(QObject):
    buildRequest = pyqtSignal(object)
    deleteRequest = pyqtSignal(object)
    def __init__(self, parent = None):
        super(BuildDelegate, self).__init__(parent)
        self.states = dict([(name, False) for name in list_del_ckbtn + list_do_ckbtn])
        self.tiles = set()

    @pyqtSlot(str, bool)
    def setCheckBoxState(self, name, state):
        self.states[name] = state

    @pyqtSlot()
    def build(self):
        task = TileTask()
        task.tiles = self.tiles.copy()
        task.toDo = self.states.copy()
        self.buildRequest.emit(task)

    @pyqtSlot()
    def deleteData(self):
        task = TileTask()
        task.tiles = self.tiles.copy()
        task.toDo = self.states.copy()
        self.deleteRequest.emit(task)

    @pyqtSlot(object, bool)
    def addRemoveTile(self, id, sel):
        if sel:
            self.tiles.add(id)
        else:
            self.tiles.discard(id)

class Model(QObject):
    removeAllTiles = pyqtSignal()
    newTileState = pyqtSignal(object, object)
    workingDirChanged = pyqtSignal(str)
    defaultWebsiteChanged = pyqtSignal(str)
    defaultZlChanged = pyqtSignal(str)
    linkStateChanged = pyqtSignal(object, bool)
    tilesFinished = pyqtSignal()
    buildFinished = pyqtSignal()
    progressChanged = pyqtSignal(int, int)
    tilesQueued = pyqtSignal(object)
    def __init__(self, settings, parent = None):
        super(Model, self).__init__(parent)
        self.settings = settings
        self.tileReader = None
        self.tileBuilder = None
        self.tileRefreshPending = False
        self.workingDir = ''
        self.tilesFinished.connect(self.tileReadDone)
        self.buildFinished.connect(self.tileBuildDone)
        self.grouped = False
        self.custom_build_dir = ''

    def start(self):
        print('Model: start')
        print('Custom scenery dir', CFG.custom_scenery_dir)
        print('Custom DEM', CFG.custom_dem)
        print('Default website', CFG.default_website)
        print('Zone list', CFG.zone_list)
        print('DEM sources:', DEM.available_sources[1::2])
        map_list = sorted([provider_code for provider_code in set(IMG.providers_dict) if IMG.providers_dict[provider_code]['in_GUI']]+sorted(set(IMG.combined_providers_dict)))
        map_list = [provider_code for provider_code in map_list if provider_code!='SEA']
        print('Providers:', map_list)
        safeRestore(self.settings, 'config/workDir', self.setWorkingDir)
        safeRestore(self.settings, 'config/defaultWebsite', self.setDefaultWebsite)
#        safeRestore(self.settings, 'config/defaultZl', lambda zl: self.setDefaultZl(str(zl)))
        self.defaultZlChanged.emit(str(CFG.default_zl))

    @pyqtSlot()
    def refreshTiles(self):
        print("Model: refreshing tiles")
        if (self.tileReader):
            self.tileReader.cancel()
            self.tileRefreshPending = True
            return
        self.removeAllTiles.emit()
        self.tileReader = Worker(target = self.tileReadWorker, name = 'Tile Reader')
        self.tileReader.workDir = self.workingDir
        self.tileReader.targetDir = CFG.custom_scenery_dir
        self.tileReader.grouped = self.grouped
        self.tileReader.start()

    @pyqtSlot()
    def tileReadDone(self):
        print('Model: tiles finished')
        self.tileReader = None
        if self.tileRefreshPending:
            self.tileRefreshPending = False
            self.refreshTiles()

    @pyqtSlot()
    def tileBuildDone(self):
        print('Model: build finished')
        self.tileBuilder = None

    @pyqtSlot(str)
    def setWorkingDir(self, dir):
#        newDir = FNAMES.Tile_dir if not dir else dir
        if dir != self.custom_build_dir:
            self.custom_build_dir = dir
            self.grouped = dir and dir[-1] != '/'
            self.workingDir = dir if dir else FNAMES.Tile_dir
            self.workingDirChanged.emit(dir)
            self.refreshTiles()

    @pyqtSlot(object)
    def toggleLink(self, id):
        subdir = None if self.grouped else makeDirName(id)
        toggleLink(self.workingDir, CFG.custom_scenery_dir, subdir)
        if not self.grouped:
            self.linkStateChanged.emit(id, linkExists(self.workingDir,
                CFG.custom_scenery_dir, subdir))
        else:
            self.refreshTiles()

    @pyqtSlot()
    def finalize(self):
        UI.red_flag = True
        self.settings.setValue('config/workDir', self.custom_build_dir)
        self.settings.setValue('config/defaultWebsite', CFG.default_website)
#        self.settings.setValue('config/defaultZl', CFG.default_zl)
        if self.tileReader:
            self.tileReader.cancel()

    @pyqtSlot(str)
    def setCustomDem(self, dem):
        CFG.custom_dem = dem

    @pyqtSlot(str)
    def setDefaultWebsite(self, website):
        if website != CFG.default_website:
            CFG.default_website = website
            self.defaultWebsiteChanged.emit(website)

    @pyqtSlot(str)
    def setDefaultZl(self, zls):
        print('setDefaultZl', zls, type(zls))
        zl = int(zls)
        if zl != CFG.default_zl:
            CFG.default_zl = zl
            print('defaultZl changed', zls, type(zls))
            self.defaultZlChanged.emit(str(zls))

    @pyqtSlot(object)
    def buildTiles(self, task):
        if self.tileBuilder: return
        if not task.tiles: return
        todo = [task.toDo[name] for name in list_do_ckbtn]
        if not any(todo): return
        self.tilesQueued.emit(task.tiles)
        tiles = sorted(task.tiles)
        lat, lon = tiles[0]
        tileCfg = CFG.Tile(lat, lon, self.custom_build_dir)
        args = [tileCfg, tiles] + todo

        self.tileBuilder = Worker(target = self.tileBuildWorker, args = args)
        self.tileBuilder.start()
#        print('Build tiles', list(todo), tiles)
#        t = 2000
#        for tile in tiles:
#            QTimer.singleShot(t, lambda id = tile: self.notifyTileCompletedAsync(id))
#            t += 2000

    @pyqtSlot(object)
    def deleteData(self, task):
        todo = map(lambda name: task.toDo[name], list_del_ckbtn)
        print('Delete data', list(todo), sorted(task.tiles))

    def tileReadWorker(self):
        try:
            subdirs = os.listdir(self.tileReader.workDir)
        except:
            self.tilesFinished.emit()
            return

        if not self.tileReader.grouped:
            for dir in subdirs:
                if self.tileReader.is_canceled(): break
                if not dir.startswith('zOrtho4XP_'): continue
                lat = int(dir[10:13])
                lon = int(dir[13:17])
                id = (lat, lon)
                info = readTile(self.tileReader.workDir, self.tileReader.targetDir, \
                    os.path.join(dir, 'Ortho4XP_' + dir[10:17] + '.cfg'), dir)
                self.newTileState.emit(id, info)
        else:
            for file in subdirs:
                print(file[:10], file[-4:])
                if self.tileReader.is_canceled(): break
                if not (file[:9] == 'Ortho4XP_' and file[-4:] == '.cfg'): continue
                lat = int(file[9:12])
                lon = int(file[12:16])
                id = (lat, lon)
                info = readTile(self.tileReader.workDir, self.tileReader.targetDir, file)
                self.newTileState.emit(id, info)

        self.tilesFinished.emit()

    def tileBuildWorker(self, *args):
        try:
            TILE.build_tile_list(*args)
        except: pass
        self.buildFinished.emit()

    def setProgressAsync(self, nbr, value):
        self.progressChanged.emit(nbr, value)

    def notifyTileCompletedAsync(self, id):
        info = readTile(self.workingDir, CFG.custom_scenery_dir, cfgFile(self.grouped, id), \
            None if self.grouped else makeDirName(id))
        self.newTileState.emit(id, info)

def cfgFile(grouped, id):
    dirname = makeDirName(id, '')
    cfg = dirname + '.cfg'
    return cfg if grouped else os.path.join('z' + dirname, cfg)

def readTile(workDir, targetDir, cfg_in_workDir, link_subdir = None):
    path = os.path.join(workDir, cfg_in_workDir)
    provider = None
    zl = None
    isLinked = False
    info = None
    try:
        with open(path) as f:
            for line in f:
                if not provider and line.startswith('default_website'):
                    provider = line.split('=')[1].strip()
                if not zl and line.startswith('default_zl'):
                    zl = line.split('=')[1].strip()
                if provider and zl: break
        info = TileInfo(provider, zl)
        info.isLinked = linkExists(workDir, targetDir, link_subdir)
    except:
        pass
    return info

def latToPixelY(lat):
    return 2**13 * (1.0 - log(tan(pi / 4 + lat * pi / 360)) / pi)

def lonToPixelX(lon):
    return 2**13 * (lon / 180 + 1.0)

def pixelYToLat(y):
    return (atan(exp(pi - y * pi / 2**13)) / pi - 0.25) * 360

def pixelXToLon(x):
    return (x / 2**13 - 1.0) * 180

def makeDirName(id, prefix = 'z'):
    lat, lon = id
    return prefix + 'Ortho4XP_{:+03d}{:+04d}'.format(lat, lon)

def linkDirs(workDir, targetDir, subdir = None):
    working = os.path.join(workDir, subdir) if subdir else workDir
    link = os.path.join(targetDir, subdir if subdir else os.path.basename(workDir))
    return (working, link)

def linkExists(workDir, targetDir, subdir = None):
    (working, link) = linkDirs(workDir, targetDir, subdir)
    return os.path.isdir(link) and os.path.samefile(working, os.path.realpath(link))

def toggleLink(workDir, targetDir, subdir = None):
    (working, link) = linkDirs(workDir, targetDir, subdir)
    if linkExists(workDir, targetDir, subdir):
        os.remove(link)
    elif not os.path.exists(link):
        os.symlink(working, link)

def safeRestore(settings, name, action):
    val = settings.value(name)
    if val:
        action(val)

def abortOperation():
    UI.red_flag = True
