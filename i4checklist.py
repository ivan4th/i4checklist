#!/usr/bin/env python
from __future__ import with_statement
import logging
import re
import sys
import os.path
#from PySide import QtCore, QtGui #, QtMaemo5
from PyQt4.QtCore import Qt, QRect, QSize, QTimer, QRegExp, QSettings, SIGNAL
from PyQt4.QtGui import QApplication, QStyledItemDelegate, QPalette, \
    QStyle, QStyleOptionButton, QPen, QWidget, QStandardItemModel, \
    QStandardItem, QTableView, QAbstractItemView, QPushButton, \
    QVBoxLayout, QHBoxLayout, QRadioButton, QSortFilterProxyModel, \
    QFont, QHeaderView, QMessageBox, QComboBox, QLabel, QInputDialog, \
    QMainWindow, QAction

log = logging.getLogger(__name__)

SAMPLE_DATA = """* ALL
  - [ ] item one
  - [ ] item two
  - [ ] item three
  - [ ] item four
** NEED
   - [ ] item five
   - [X] item six
   - [X] item seven
"""

class ParseError(Exception):
    pass

def parse_check_line(line):
    m = re.match(r"\s*-\s*\[(.)\]\s*(.*?)\s*$", line)
    if not m:
        raise ParseError("expected check line, got %r" % line)
    return bool(m.group(1).strip()), m.group(2).decode("utf-8")

FRESH = 0
NOT_NEEDED = 1
NEED = 2
CHECKED = 3

CHECK_FIELD_WIDTH = 60
ITEM_HEIGHT = 60
BULLET_SIZE = 12
SAVE_INTERVAL_MS = 3000

def parse_data(s):
    state = "notstarted"
    for line in s.readlines():
        if not line.strip():
            continue
        if state == "notstarted":
            if not re.match(r"\*\s*ALL", line):
                raise ParseError("expected * ALL, got %r" % line)
            state = "not_needed"
        elif state == "not_needed":
            if re.match(r"\*\*\s*NEED", line):
                state = "need"
                continue
            checked, title = parse_check_line(line)
            yield NOT_NEEDED, title
        elif state == "need":
            checked, title = parse_check_line(line)
            if checked:
                yield CHECKED, title
            else:
                yield NEED, title

def serialize_data(data, out):
    print >>out, "* ALL"
    for state, title in data:
        if state == NOT_NEEDED:
            print >>out, "  - [ ] %s" % title.encode("utf-8")
    print >>out, "** NEED"
    for state, title in data:
        if state == NOT_NEEDED:
            continue
        print >>out, "   - [%s] %s" % \
            ("X" if state == CHECKED else " ", title.encode("utf-8"))

def test_it():
    from cStringIO import StringIO
    parsed = list(parse_data(StringIO(SAMPLE_DATA)))
    print "PARSED:\n%r\n" % parsed
    out = StringIO()
    serialize_data(parsed, out)
    serialized = out.getvalue()
    print "SERIALIZED:\n%s---" % serialized
    assert SAMPLE_DATA == serialized

class CheckBoxDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() > 0:
            editor = super(CheckBoxDelegate, self). \
                createEditor(parent, option, index)
            if editor is not None:
                editor.setInputMethodHints(Qt.ImhNoAutoUppercase)
            return editor
        return None

    def sizeHint(self, option, index):
        size = QSize(super(CheckBoxDelegate, self).sizeHint(option, index))
        if index.column() == 0:
            size.setWidth(CHECK_FIELD_WIDTH)
        size.setHeight(ITEM_HEIGHT)
        return size

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        if index.column() > 0:
            self.paint_text(painter, option, index)
        else:
            self.paint_checkbox(painter, option, index)

    def paint_text(self, painter, option, index):
        if int(index.model().index(index.row(), 0).data().toPyObject()) == \
                CHECKED:
            option.font = QFont(option.font)
            option.font.setStrikeOut(True)
        QApplication.style().drawControl(
            QStyle.CE_ItemViewItem, option, painter,
            getattr(option, "widget", None))

    def paint_checkbox(self, painter, option, index):
        style = QApplication.style()
        option.text = ""
        style.drawControl(
            QStyle.CE_ItemViewItem, option, painter,
            getattr(option, "widget", None))
        data = int(index.data().toPyObject())
        if data == FRESH:
            return
        opts = QStyleOptionButton() # QtGui.QStyleOptionViewItem()
        opts.rect = option.rect
        se_rect = style.subElementRect(QStyle.SE_CheckBoxIndicator, opts)
        if data == NOT_NEEDED:
            bullet_rect = QRect(se_rect)
            if bullet_rect.width() > BULLET_SIZE:
                bullet_rect.setLeft(
                    bullet_rect.left() +
                    (bullet_rect.width() - BULLET_SIZE) / 2)
                bullet_rect.setWidth(BULLET_SIZE)
            if bullet_rect.height() > BULLET_SIZE:
                bullet_rect.setTop(
                    bullet_rect.top() +
                    (bullet_rect.height() - BULLET_SIZE) / 2)
                bullet_rect.setHeight(BULLET_SIZE)
            painter.save()
            painter.setPen(QPen(option.palette.color(QPalette.Text)))
            painter.setBrush(option.palette.brush(QPalette.Text))
            painter.drawEllipse(bullet_rect)
            painter.restore()
            return
        if data == CHECKED:
            opts.state |= QStyle.State_On | QStyle.State_Enabled
        else:
            opts.state |= QStyle.State_Off | QStyle.State_Enabled
        opts.rect = se_rect
        style.drawPrimitive(QStyle.PE_IndicatorCheckBox, opts, painter)

class CheckListModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super(CheckListModel, self).__init__(parent)
        self.settings = QSettings("fionbio", "i4checklist")
        self._updatePending = False
        model = QStandardItemModel(0, 2, self)
        self.setSourceModel(model)
        self.setDynamicSortFilter(True)
        self.set_show_all(False)
        self.load_db_list()
        self.load()
        self.connect(model, SIGNAL("dataChanged(QModelIndex, QModelIndex)"),
                    self._dataChanged)
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(SAVE_INTERVAL_MS)
        self.connect(self.save_timer, SIGNAL("timeout()"), self.save)

    @property
    def model(self):
        return self.sourceModel()

    def db_dir(self):
        return os.path.expanduser("~/MyDocs/.i4checklist")

    def load_db_list(self, ignore_current=False):
        self.databases = []
        for filename in sorted(os.listdir(self.db_dir())):
            path = os.path.join(self.db_dir(), filename)
            if os.path.isfile(path):
                self.databases.append(filename)
        if not self.databases:
            self.databases = ["default"]
        self.current_db = self.databases[0]
        if ignore_current:
            return
        self.settings.beginGroup("database")
        try:
            if self.settings.contains("current"):
                cur = str(self.settings.value("current").toPyObject())
                if cur in self.databases:
                    self.current_db = cur
        finally:
            self.settings.endGroup()

    def load(self, db_name=None):
        if db_name is not None:
            if not db_name in self.databases:
                self.databases.append(db_name)
                self.databases.sort()
            self.current_db = db_name
            self.settings.beginGroup("database")
            try:
                self.settings.setValue("current", self.current_db)
            finally:
                self.settings.endGroup()
        path = os.path.join(self.db_dir(), self.current_db)
        log.debug("load(): %s" % path)
        self.model.removeRows(0, self.model.rowCount())
        if not os.path.exists(path):
            return
        with open(path) as f:
            for state, title in parse_data(f):
                self.model.appendRow(
                    [QStandardItem(str(state)), QStandardItem(title)])

    def save(self):
        path = os.path.join(self.db_dir(), self.current_db)
        log.debug("save(): %s" % path)
        self.cleanup()
        if not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        data = []
        for i in range(0, self.model.rowCount()):
            data.append((int(self.model.index(i, 0).data().toPyObject()),
                         unicode(self.model.index(i, 1).data().toPyObject())))
        data.sort()
        with open(path, "wt+") as f:
            serialize_data(data, f)
        self.save_timer.stop()

    def delete_database(self):
        path = os.path.join(self.db_dir(), self.current_db)
        if os.path.exists(path):
            os.unlink(path)
        self.load_db_list(True)
        self.load()

    def _dataChanged(self, top_left, bottom_right):
        log.debug("_dataChanged")
        if not self._updatePending:
            self._updatePending = True
            QTimer.singleShot(1, self.cleanup)
        elif top_left.column() <= 1 and bottom_right.column() >= 1:
            QTimer.singleShot(1, self.invalidate)
            self.invalidate()
        self.save_timer.start()

    def cleanup(self, checkout=False):
        i = 0
        while i < self.model.rowCount():
            value = self.model.index(i, 1).data().toPyObject()
            value = value and unicode(value).strip()
            if not value:
                self.model.removeRow(i)
                continue
            index = self.model.index(i, 0)
            value = int(index.data().toPyObject())
            if checkout:
                if value == CHECKED:
                    self.model.setData(index, NOT_NEEDED)
            else:
                if value == FRESH:
                    self.model.setData(index, NEED)
            i += 1
        self._updatePending = False

    def lessThan(self, left, right):
        r = super(CheckListModel, self).lessThan(left, right)
        if r or left.column() or right.column():
            return r
        if super(CheckListModel, self).lessThan(right, left):
            return False
        new_left = self.model.index(left.row(), 1)
        new_right = self.model.index(right.row(), 1)
        return super(CheckListModel, self).lessThan(new_left, new_right)

    def set_show_all(self, show_all):
        self.show_all = show_all
        if show_all:
            self.setFilterRegExp("")
        else:
            self.setFilterRegExp(
                QRegExp("^%d|%d|%d$" % (FRESH, NEED, CHECKED)))

    def new(self):
        self.cleanup()
        self.model.insertRow(0, [QStandardItem(str(FRESH)), QStandardItem()])
        self.save_timer.stop()
        return self.mapFromSource(self.model.index(0, 1))

    def toggle(self, row):
        value = int(self.index(row, 0).data().toPyObject())
        if value in (FRESH, NOT_NEEDED):
            value = NEED
        elif value == NEED:
            value = CHECKED
        elif self.show_all:
            value = NOT_NEEDED
        else:
            value = NEED
        self.setData(self.index(row, 0), value)

    def checkout(self):
        self.cleanup(True)

class I4CheckWindow(QWidget):
    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setup_model()

        self.tableview = QTableView()
        self.tableview.setSelectionMode(QAbstractItemView.NoSelection)
        self.tableview.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.cbdelegate = CheckBoxDelegate()
        self.tableview.setItemDelegate(self.cbdelegate)
        self.tableview.setModel(self.model)
        self.tableview.sortByColumn(0, Qt.AscendingOrder)
        self.adjust_headers()
        self.connect(self.tableview,
                     SIGNAL("clicked(const QModelIndex&)"),
                     self.item_clicked)

        #self.model.setHeaderData(0, Qt.Horizontal, u"")
        #self.model.setHeaderData(1, Qt.Horizontal, u"Title")

        self.radio_all = QRadioButton("All")
        self.radio_need = QRadioButton("Need")
        self.radio_need.setChecked(True)
        self.connect(self.radio_all, SIGNAL("toggled(bool)"), self.set_show_all)

        label = QLabel("Database:")
        label.setFixedWidth(120)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        self.db_combo = QComboBox()
        self.populate_db_combo()
        self.connect(
            self.db_combo, SIGNAL("currentIndexChanged(int)"),
            self.db_index_changed)

        self.new_button = QPushButton("Add")
        self.connect(self.new_button, SIGNAL("clicked()"), self.new_item)
        self.checkout_button = QPushButton("Checkout")
        self.connect(self.checkout_button, SIGNAL("clicked()"), self.checkout)

        self.box = QVBoxLayout(self)
        self.top_box = QHBoxLayout()
        self.top_box.setSpacing(0)
        self.top_box.addWidget(self.radio_all)
        self.top_box.addWidget(self.radio_need)
        self.top_box.addWidget(label)
        self.top_box.addWidget(self.db_combo)
        self.box.addLayout(self.top_box)
        self.box.addWidget(self.tableview)
        self.button_box = QHBoxLayout()
        self.button_box.addWidget(self.checkout_button)
        self.button_box.addWidget(self.new_button)
        self.box.addLayout(self.button_box)

        self.setAttribute(Qt.WA_Maemo5AutoOrientation)

        self.dwim_after_load()

    def dwim_after_load(self):
        if self.model.rowCount() > 0:
            self.radio_need.setChecked(True)
            return
        self.radio_all.setChecked(True)
        if self.model.model.rowCount() == 0:
            edit_index = self.model.new()
            self.tableview.setCurrentIndex(edit_index)
            self.tableview.edit(edit_index)

    def adjust_headers(self):
        log.debug("adjust_sizes()")
        self.tableview.setColumnWidth(0, CHECK_FIELD_WIDTH)
        self.tableview.horizontalHeader().setResizeMode(1, QHeaderView.Stretch)
        self.tableview.setColumnWidth(1, 1)
        self.tableview.verticalHeader().setDefaultSectionSize(ITEM_HEIGHT)
        self.tableview.verticalHeader().hide()
        self.tableview.horizontalHeader().hide()

    def setup_model(self):
        self.model = CheckListModel()

    def item_clicked(self, index):
        if index.column() > 0:
            return
        cur_index = self.tableview.currentIndex()
        self.model.toggle(index.row())
        self.tableview.setCurrentIndex(cur_index)

    def new_item(self):
        index = self.model.new()
        self.tableview.setCurrentIndex(index)
        self.tableview.resizeRowToContents(index.row())
        self.tableview.edit(index)

    def set_show_all(self, show_all):
        if self.model.show_all == show_all:
            return
        self.model.set_show_all(show_all)
        self.tableview.resizeRowsToContents()

    def closeEvent(self, event):
        self.model.save()
        super(I4CheckWindow, self).closeEvent(event)

    def checkout(self):
        if QMessageBox.question(
            self, "Checkout", "Are you sure you want to check out?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == \
            QMessageBox.Yes:
            self.model.checkout()

    def delete_database(self):
        if QMessageBox.question(
            self, "Delete database",
            "Are you sure you want to delete the current database?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == \
            QMessageBox.Yes:
            self.model.delete_database()
            self.populate_db_combo()
            self.dwim_after_load()

    _loading_db_combo = False

    def populate_db_combo(self):
        self._loading_db_combo = True
        try:
            self.db_combo.clear()
            for db_name in self.model.databases:
                self.db_combo.addItem(re.sub("\\.org$", "", db_name), db_name)
            self.db_combo.addItem("New database...", "")
            self.db_combo.setCurrentIndex(
                self.model.databases.index(self.model.current_db))
        finally:
            self._loading_db_combo = False

    def db_index_changed(self, index):
        if self._loading_db_combo:
            return
        db_name = str(self.db_combo.itemData(index).toPyObject())
        if db_name == self.model.current_db:
            return

        self.model.save()

        if db_name:
            self.model.load(db_name)
            self.dwim_after_load()
            return

        db_name, ok = QInputDialog.getText(
            self, "New Database", "Enter database name")
        if ok:
            if not re.match(r"^[\w-]+$", db_name):
                QMessageBox.critical(
                    self, "Error",
                    "Database name must contain only the following chars: "
                    "A-Z a-z 0-9 _ -")
                ok = False
            elif db_name in self.model.databases:
                QMessageBox.critical(
                    self, "Error", "Database '%s' already exists" % db_name)
                ok = False
        if not ok:
            self.db_combo.setCurrentIndex(
                self.model.databases.index(self.model.current_db))
            return
        db_name = str(db_name) + ".org"
        self.model.load(db_name)
        self.populate_db_combo()
        self.dwim_after_load()

class I4CheckMainWindow(QMainWindow):
    def __init__(self):
        super(I4CheckMainWindow, self).__init__()
        self.setWindowTitle("i4checklist")
        self.checklist = I4CheckWindow()
        self.setCentralWidget(self.checklist)
        self.setup_menu()

    def setup_menu(self):
        self.act_del_db = QAction(self.tr('Delete database'), self)
        self.act_del_db.triggered.connect(self.checklist.delete_database)
        self.act_about = QAction(self.tr('About'), self)
        self.act_about.triggered.connect(self.about)

        menu_bar = self.menuBar()
        menu_bar.addAction(self.act_del_db)
        menu_bar.addAction(self.act_about)

    def about(self):
        QMessageBox.information(
            self, "About i4checklist",
            "Shopping list and check list application \n"
            "inspired by Handy Shopper for Palm OS.\n\n"
            "(c) Copyright Ivan Shvedunov 2010")

# TBD: disable checkout button when there are no checked items
# TBD: remove/separate test code
# TBD: reduce N of redundant saves
# TBD: main menu (remove database, etc.)
# TBD: style using qss
# TBD: don't crash on parse errors
# TBD: invent more convenient org format

#test_it()
logging.basicConfig(level=logging.DEBUG)
app = QApplication(sys.argv)
widget = I4CheckMainWindow()
widget.show()
sys.exit(app.exec_())
