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

NOT_NEEDED = 0
NEED = 1
CHECKED = 2

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
        editor = super(CheckBoxDelegate, self). \
            createEditor(parent, option, index)
        if editor is not None:
            editor.setInputMethodHints(Qt.ImhNoAutoUppercase)
        return editor

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        if hasattr(option, "checkState"):
            if option.checkState == Qt.Unchecked:
                option.checkState = Qt.PartiallyChecked
            elif option.checkState == Qt.PartiallyChecked:
                option.checkState = Qt.Unchecked
            elif option.checkState == Qt.Checked:
                option.font = QFont(option.font)
                option.font.setStrikeOut(True)
        # ref: qt4-x11-4.6.2/src/gui/styles/qcommonstyle.cpp
        painter.save()
        painter.setClipRect(option.rect)
        # QApplication.style().drawControl(
        #     QStyle.CE_ItemViewItem, option, painter,
        #     getattr(option, "widget", None))
        style = QApplication.style()
        widget = getattr(option, "widget", None)
        # log.debug("widget: %r style: %r" % (widget, style.metaObject().className()))
        style.drawPrimitive(
            QStyle.PE_PanelItemViewItem, option, painter, widget)

        text_rect = style.subElementRect(
            QStyle.SE_ItemViewItemText, option, widget)
        item_text = option.fontMetrics.elidedText(
            option.text, option.textElideMode, text_rect.width())
        painter.setFont(option.font)
        style.drawItemText(painter, text_rect, option.displayAlignment,
                           option.palette, True, item_text, QPalette.Text)

        check_rect = style.subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, option, widget)
        if option.checkState == Qt.PartiallyChecked:
            brush = option.palette.brush(QPalette.Base)
            painter.fillRect(check_rect, brush)
            bullet_rect = QRect(check_rect)
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
            painter.setPen(QPen(option.palette.color(QPalette.Text)))
            painter.setBrush(option.palette.brush(QPalette.Text))
            painter.drawEllipse(bullet_rect)
        else:
            check_opt = QStyleOptionButton()
            check_opt.rect = check_rect
            check_opt.state = option.state & ~QStyle.State_HasFocus
            if option.checkState == Qt.Checked:
                check_opt.state |= QStyle.State_On
            else:
                check_opt.state |= QStyle.State_Off
            style.drawPrimitive(
                QStyle.PE_IndicatorItemViewItemCheck, check_opt, painter,
                widget)
        painter.restore()

class CheckListModel(QSortFilterProxyModel):
    # FIXME: should not use the proxy. just implement the real model
    def __init__(self, parent=None):
        super(CheckListModel, self).__init__(parent)
        self.settings = QSettings("fionbio", "i4checklist")
        self._updatePending = False
        model = QStandardItemModel(0, 1, self)
        self.setFilterRole(Qt.CheckStateRole)
        self.setSortRole(Qt.CheckStateRole)
        self.setDynamicSortFilter(True)
        self.setSourceModel(model)
        # setting filter regexp to non-empty pattern
        # causes the proxy to fail to sort its items
        self.set_show_all(True)
        self.load_db_list()
        self.load()
        self.sort(0, Qt.AscendingOrder)
        self.connect(model, SIGNAL("dataChanged(QModelIndex, QModelIndex)"),
                     self._dataChanged)
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(SAVE_INTERVAL_MS)
        self.connect(self.save_timer, SIGNAL("timeout()"), self.save)

    @property
    def model(self):
        return self.sourceModel()

    def setData(self, index, value, role):
        if not self.show_all and role == Qt.CheckStateRole and \
                value == Qt.Unchecked:
            value = Qt.PartiallyChecked
        return super(CheckListModel, self).setData(index, value, role)

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

    def state_to_check_state(self, state):
        if state == NOT_NEEDED:
            return Qt.Unchecked
        elif state == CHECKED:
            return Qt.Checked
        else: # NEED
            return Qt.PartiallyChecked

    def check_state_to_state(self, check_state):
        if check_state == Qt.Unchecked:
            return NOT_NEEDED
        elif check_state == Qt.Checked:
            return CHECKED
        else: # NEED
            return NEED

    def make_row(self, state, title):
        item = QStandardItem(title) if title else QStandardItem()
        item.setFlags(
            Qt.ItemIsUserCheckable | Qt.ItemIsTristate | Qt.ItemIsEnabled |
            Qt.ItemIsEditable)
        item.setData(self.state_to_check_state(state), Qt.CheckStateRole)
        return [item]

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
                self.model.appendRow(self.make_row(state, title))

    def save(self):
        path = os.path.join(self.db_dir(), self.current_db)
        log.debug("save(): %s" % path)
        self.cleanup()
        if not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        data = []
        for i in range(0, self.model.rowCount()):
            index = self.model.index(i, 0)
            v1 = self.check_state_to_state(
                index.data(Qt.CheckStateRole).toPyObject())
            v2 = unicode(index.data().toPyObject())
            data.append((v1, v2))
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
        self.save_timer.start()

    def cleanup(self, checkout=False):
        i = 0
        while i < self.model.rowCount():
            index = self.model.index(i, 0)
            value = index.data().toPyObject()
            value = value and unicode(value).strip()
            if not value:
                self.model.removeRow(i)
                continue
            check_value = int(index.data(Qt.CheckStateRole).toPyObject())
            if checkout and check_value == Qt.Checked:
                    self.model.setData(
                        index, Qt.Unchecked, Qt.CheckStateRole)
            i += 1
        self._updatePending = False

    def lessThan(self, left, right):
        # log.debug("left %d %d right %d %d" % (left.row(), left.column(), right.row(), right.column()))
        r = super(CheckListModel, self).lessThan(left, right)
        if r:
            return True
        if super(CheckListModel, self).lessThan(right, left):
            return False
        return unicode(left.data().toPyObject()) < unicode(right.data().toPyObject())

    def set_show_all(self, show_all):
        self.show_all = show_all
        if show_all:
            self.setFilterRegExp("")
        else:
            self.setFilterRegExp(
                QRegExp("^%d|%d$" % (Qt.Checked, Qt.PartiallyChecked)))

    def new(self):
        self.cleanup()
        self.model.insertRow(0, self.make_row(NEED, None))
        self.save_timer.stop()
        return self.mapFromSource(self.model.index(0, 0))

    def checkout(self):
        self.cleanup(True)

    def need_anything(self):
        for i in range(0, self.model.rowCount()):
            index = self.model.index(i, 0)
            v = self.check_state_to_state(
                index.data(Qt.CheckStateRole).toPyObject())
            if v != NOT_NEEDED:
                return True
        return False

class I4CheckWindow(QWidget):
    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setup_model()

        self.tableview = QTableView()
        self.tableview.setSelectionMode(QAbstractItemView.NoSelection)
        self.tableview.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.cbdelegate = CheckBoxDelegate()
        self.tableview.setItemDelegate(self.cbdelegate)
        self.tableview.setAutoScroll(False)
        self.tableview.setModel(self.model)
        self.tableview.sortByColumn(0, Qt.AscendingOrder)
        self.adjust_headers()

        #self.model.setHeaderData(0, Qt.Horizontal, u"")
        #self.model.setHeaderData(1, Qt.Horizontal, u"Title")

        self.radio_all = QRadioButton("All")
        self.radio_all.setChecked(True)
        self.radio_need = QRadioButton("Need")
        self.connect(self.radio_all, SIGNAL("toggled(bool)"), self.set_show_all)

        label = QLabel("DB:")
        label.setFixedWidth(40)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        self.db_combo = QComboBox()
        self.populate_db_combo()
        self.connect(
            self.db_combo, SIGNAL("currentIndexChanged(int)"),
            self.db_index_changed)

        self.new_button = QPushButton("New")
        self.connect(self.new_button, SIGNAL("clicked()"), self.new_item)

        self.box = QVBoxLayout(self)
        self.box.addWidget(self.tableview)
        self.button_box = QHBoxLayout()
        self.button_box.setSpacing(0)
        self.button_box.addWidget(self.new_button)
        self.button_box.addWidget(self.radio_all)
        self.button_box.addWidget(self.radio_need)
        self.button_box.addWidget(label)
        self.button_box.addWidget(self.db_combo)
        self.box.addLayout(self.button_box)

        # self.setStyleSheet("""
        # QComboBox {
        #     font-size: 16px;
        # }
        # """)

        self.dwim_after_load()

    def dwim_after_load(self):
        if self.model.need_anything():
            self.radio_need.setChecked(True)
            return
        self.radio_all.setChecked(True)
        if self.model.model.rowCount() == 0:
            edit_index = self.model.new()
            self.tableview.setCurrentIndex(edit_index)
            self.tableview.scrollTo(edit_index)
            self.tableview.edit(edit_index)

    def adjust_headers(self):
        log.debug("adjust_sizes()")
        self.tableview.horizontalHeader().setResizeMode(0, QHeaderView.Stretch)
        self.tableview.setColumnWidth(0, 1)
        self.tableview.verticalHeader().setDefaultSectionSize(ITEM_HEIGHT)
        self.tableview.verticalHeader().hide()
        self.tableview.horizontalHeader().hide()

    def setup_model(self):
        self.model = CheckListModel()

    def new_item(self):
        index = self.model.new()
        self.tableview.setCurrentIndex(index)
        self.tableview.resizeRowToContents(index.row())
        self.tableview.scrollTo(index)
        self.tableview.edit(index)

    def set_show_all(self, show_all):
        if self.model.show_all == show_all:
            return
        self.model.set_show_all(show_all)
        self.tableview.resizeRowsToContents()

    def save(self):
        self.model.save()

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
        self.setAttribute(Qt.WA_Maemo5AutoOrientation)

    def closeEvent(self, event):
        self.checklist.save()
        super(I4CheckMainWindow, self).closeEvent(event)

    def setup_menu(self):
        self.act_checkout = QAction(self.tr('Checkout'), self)
        self.act_checkout.triggered.connect(self.checklist.checkout)
        self.act_del_db = QAction(self.tr('Delete database'), self)
        self.act_del_db.triggered.connect(self.checklist.delete_database)
        self.act_about = QAction(self.tr('About'), self)
        self.act_about.triggered.connect(self.about)
        menu_bar = self.menuBar()
        menu_bar.addAction(self.act_checkout)
        menu_bar.addAction(self.act_del_db)
        menu_bar.addAction(self.act_about)

    def about(self):
        QMessageBox.information(
            self, "About i4checklist",
            "Shopping list and check list application \n"
            "inspired by Handy Shopper for Palm OS.\n\n"
            "(c) Copyright Ivan Shvedunov 2010")

# TBD: QSortFilterProxyModel still fscks up unpredictably after setFilterRegExp()...
# TBD: reset: like checkout, but resets everything, not just checked items
# TBD: use pale color for checked items
# TBD: disable checkout menu item when there are no checked items
# TBD: separate logic, write more tests
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
