"""Aide contextuelle Ctrl+Shift : observation légère, uniquement pendant le geste."""
import time
import unicodedata
from PySide6.QtCore import QObject,QEvent,QTimer,Qt
from PySide6.QtGui import QCursor,QKeySequence,QShortcut
from PySide6.QtWidgets import (QApplication,QFrame,QVBoxLayout,QHBoxLayout,QTextBrowser,
                               QPushButton,QDialog,QLineEdit,QListWidget,QListWidgetItem)
from video.help_content import HELP,GLOSSARY,SOURCES,page


def annotate(widget,key):
    widget.setProperty('color_help_key',key)


def _fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.casefold()) if not unicodedata.combining(c))


class Glossary(QDialog):
    def __init__(self,parent=None,key=None):
        super().__init__(parent)
        self.setWindowTitle('Aide et glossaire colorimétrique')
        self.resize(920,660)
        layout = QVBoxLayout(self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('Rechercher une notion, un outil, une explication…')
        layout.addWidget(self.search)
        row = QHBoxLayout()
        self.list = QListWidget(self)
        self.list.setMaximumWidth(270)
        row.addWidget(self.list)
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        row.addWidget(self.browser,1)
        layout.addLayout(row)
        self.entries = [(k,HELP[k]['title']) for k in HELP]+[(k,k) for k in GLOSSARY]
        self.search.textChanged.connect(self._filter)
        self.list.currentItemChanged.connect(self._show)
        self._filter('')
        if key:
            self.select(key)

    def select(self,key):
        self.search.clear()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole)==key:
                self.list.setCurrentRow(i)
                return

    def _filter(self,text):
        previous = self.list.currentItem()
        selected = previous.data(Qt.UserRole) if previous else None
        self.list.clear()
        for key,label in self.entries:
            if _fold(text) in _fold(label+' '+page(key)):
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole,key)
                self.list.addItem(item)
                if key==selected:
                    self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        elif not self.list.count():
            self.browser.setPlainText('Aucune notion ne correspond à cette recherche.')

    def _show(self,item,*_):
        if item is not None:
            from html import escape
            sources = '<h3>Documentation de référence</h3>'+''.join(
                f'<p><a href="{escape(url,quote=True)}">{escape(label)}</a></p>' for label,url in SOURCES)
            self.browser.setHtml(page(item.data(Qt.UserRole))+sources)


class HelpController(QObject):
    """Aide Ctrl+Maj au survol, F1 = glossaire. AUCUN filtre sur toute l'application : il faisait passer
    CHAQUE evenement de l'appli par du Python, une fois par fenetre qui en a un (fenetre de reglages prechargee
    comprise : ~6 us par evenement ; dans les tests, les fenetres s'accumulaient et chaque test ralentissait le
    suivant jusqu'a 90 s). A la place : filtre sur la SEULE fenetre `root` (affichage / masquage), releve des
    touches Ctrl+Maj toutes les `WATCH_MS` tant qu'elle est visible, raccourci F1 propre a la fenetre."""

    WATCH_MS = 100

    def __init__(self,root,settings=None):
        super().__init__(root)
        self.root = root
        self.settings = settings or {}
        self.anchor = None
        self.key = None
        self.since = 0
        self.popup = QFrame(root.window(),Qt.ToolTip)
        self.popup.setAttribute(Qt.WA_ShowWithoutActivating)
        layout = QVBoxLayout(self.popup)
        self.browser = QTextBrowser(self.popup)
        self.browser.setOpenExternalLinks(True)
        layout.addWidget(self.browser)
        button = QPushButton('Explication complète / glossaire',self.popup)
        button.clicked.connect(lambda:self.open_glossary(self.key))
        layout.addWidget(button)
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)
        self.watch = QTimer(self)
        self.watch.setInterval(self.WATCH_MS)
        self.watch.timeout.connect(self._watch)
        root.installEventFilter(self)
        if root.isVisible():
            self.watch.start()
        QApplication.instance().applicationStateChanged.connect(self._app_state)
        self.f1 = QShortcut(QKeySequence(Qt.Key_F1),root,context=Qt.WidgetWithChildrenShortcut)
        self.f1.activated.connect(self._f1)
        root.destroyed.connect(self.popup.deleteLater)

    def _watch(self):
        """Ctrl+Maj tenus pendant que la fenetre est active : le geste commence (`_tick` prend la suite)."""
        required = Qt.ControlModifier|Qt.ShiftModifier
        if QApplication.keyboardModifiers()&required==required and not self.timer.isActive():
            self.timer.start()

    def _app_state(self,state):
        if state!=Qt.ApplicationActive:
            self.dismiss()

    def _f1(self):
        _target,key = self.resolve(QApplication.focusWidget())
        self.open_glossary(key)

    def open_glossary(self,key=None):
        self.dismiss()
        window = getattr(self,'glossary',None)
        if window is None:
            self.glossary = Glossary(self.root,key)
            window = self.glossary
        elif key:
            window.select(key)
        window.show()
        window.raise_()
        window.activateWindow()

    def dismiss(self):
        self.popup.hide()
        self.timer.stop()
        self.anchor = self.key = None

    def eventFilter(self,watched,event):
        kind = event.type()
        if kind in (QEvent.ApplicationDeactivate,QEvent.ApplicationStateChange):
            if QApplication.applicationState()!=Qt.ApplicationActive:
                self.dismiss()
        elif kind==QEvent.Hide and watched is self.root:
            self.watch.stop()
            self.dismiss()
        elif kind==QEvent.Show and watched is self.root:
            self.watch.start()
        elif kind==QEvent.Enter:
            required = Qt.ControlModifier|Qt.ShiftModifier
            if QApplication.keyboardModifiers()&required==required and not self.timer.isActive():
                self.timer.start()
        elif kind in (QEvent.KeyPress,QEvent.KeyRelease):
            if kind==QEvent.KeyPress and event.key()==Qt.Key_F1:
                target,key = self.resolve(QApplication.focusWidget())
                if key:
                    self.open_glossary(key)
                    return True
            # Ne jamais avaler Ctrl/Shift : les raccourcis de l'application restent actifs.
            if event.key() in (Qt.Key_Control,Qt.Key_Shift):
                self.timer.start()
        return False

    def resolve(self,widget):
        if widget is None:
            return None,None
        if self.popup.isAncestorOf(widget) or widget is self.popup:
            return self.anchor,self.key
        candidate = widget
        while candidate is not None:
            key = candidate.property('color_help_key')
            if key and (self.root is candidate or self.root.isAncestorOf(candidate)):
                return candidate,str(key)
            candidate = candidate.parentWidget()
        return None,None

    def _tick(self):
        modifiers = QApplication.keyboardModifiers()
        required = Qt.ControlModifier|Qt.ShiftModifier
        active = QApplication.activeWindow()
        if (not self.settings.get('video_help_enabled',True) or modifiers&required != required
                or not self.root.isVisible() or active is None
                or (active is not self.root.window() and not self.root.isAncestorOf(active))):
            self.dismiss()
            return
        widget,key = self.resolve(QApplication.widgetAt(QCursor.pos()))
        now = time.monotonic()
        if widget is not self.anchor or key!=self.key:
            self.popup.hide()
            self.anchor,self.key,self.since = widget,key,now
        if not key or now-self.since < max(0,int(self.settings.get('video_help_delay',350)))/1000:
            return
        if self.popup.isVisible():
            return
        width = max(280,min(800,int(self.settings.get('video_help_width',500))))
        self.browser.setHtml(page(key))
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.popup.resize(min(width,area.width()),min(480,area.height()))
        point = QCursor.pos()
        self.popup.move(max(area.left(),min(point.x()+18,area.right()-self.popup.width()+1)),
                        max(area.top(),min(point.y()+20,area.bottom()-self.popup.height()+1)))
        self.popup.show()
        # Le cadre natif n'a sa taille définitive qu'après show (quelques
        # pixels sous Windows). Le borner lui aussi, pas seulement le contenu.
        frame = self.popup.frameGeometry()
        self.popup.move(max(area.left(),min(frame.x(),area.right()-frame.width()+1)),
                        max(area.top(),min(frame.y(),area.bottom()-frame.height()+1)))
