#!/usr/bin/env python

import sys
import re
#from PySide import QtCore, QtGui #, QtMaemo5
from PyQt4.QtCore import Qt, QRect, SIGNAL
from PyQt4.QtGui import QApplication, QStyledItemDelegate, QPalette, \
    QStyle, QStyleOptionButton, QPen, QWidget, QStandardItemModel, \
    QStandardItem, QTreeView, QAbstractItemView, QPushButton, \
    QVBoxLayout, QSortFilterProxyModel

SAMPLE_DATA = """
* ALL
  - [ ] item one
  - [ ] item two
  - [ ] item three
  - [ ] item four
** NEEDED
   - [ ] item five
   - [x] item six
   - [x] item seven
"""

class ParseError(Exception):
    pass

def parse_check_line(line):
    m = re.match(r"\s*-\s*\[(.)\]\s*(.*?)\s*$", line)
    if not m:
        raise ParseError("expected check line, got %r" % line)
    return bool(m.group(1).strip()), m.group(2)

NEEDED = 0
CHECKED = 1
NOT_NEEDED = 2

BULLET_SIZE = 12

def parse_data(s):
    state = "notstarted"
    for line in s.readlines():
        if not line.strip():
            continue
        if state == "notstarted":
            if not re.match(r"\*\s*ALL", line):
                raise ParseError("expected * ALL, got %r" % line)
            state = "all"
        elif state == "all":
            if re.match(r"\*\*\s*NEEDED", line):
                state = "needed"
            continue
            yield ("all",) + parse_check_line(line)
        elif state == "needed":
            yield ("needed",) + parse_check_line(line)

class CheckBoxDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        return None

    def paint(self, painter, option, index):
        # print >>sys.stderr, "CheckBoxDelegate.paint(%d, %d, %d, %d)" % \
        #     (option.rect.left(), option.rect.top(),
        #      option.rect.width(), option.rect.height())
        self.initStyleOption(option, index)
        style = QApplication.style()
        brush = option.palette.brush(QPalette.Base)
        painter.fillRect(option.rect, brush)
        opts = QStyleOptionButton() # QtGui.QStyleOptionViewItem()
        opts.rect = option.rect
        data = int(index.data().toPyObject())
        se_rect = style.subElementRect(QStyle.SE_CheckBoxIndicator, opts)
        if data == NOT_NEEDED:
            bullet_rect = QRect(se_rect.x(), se_rect.y(), # FIXME
                                se_rect.width(), se_rect.height())
            if bullet_rect.width() > BULLET_SIZE:
                bullet_rect.setLeft(
                    bullet_rect.left() + (bullet_rect.width() - BULLET_SIZE) / 2)
                bullet_rect.setWidth(BULLET_SIZE)
            if bullet_rect.height() > BULLET_SIZE:
                bullet_rect.setTop(
                    bullet_rect.top() + (bullet_rect.height() - BULLET_SIZE) / 2)
                bullet_rect.setHeight(BULLET_SIZE)
            # print >>sys.stderr, "bullet_rect = QRect(%d, %d, %d, %d)" % \
            #     (bullet_rect.left(), bullet_rect.top(),
            #      bullet_rect.width(), bullet_rect.height())
            painter.save()
            painter.setPen(QPen(option.palette.color(QPalette.Text)))
            painter.setBrush(option.palette.brush(QPalette.Text))
            painter.drawEllipse(bullet_rect)
            painter.restore()
            return
        if data == CHECKED:
            # print >>sys.stderr, "on!"
            opts.state |= QStyle.State_On | QStyle.State_Enabled
        else:
            # print >>sys.stderr, "off!"
            opts.state |= QStyle.State_Off | QStyle.State_Enabled
        opts.rect = se_rect
        style.drawPrimitive(QStyle.PE_IndicatorCheckBox, opts, painter)
        # print >>sys.stderr, "out"

class CheckProxyModel(QSortFilterProxyModel):
    def __init__(self, model, parent=None):
        super(CheckProxyModel, self).__init__(parent)
        self.setSourceModel(model)
        self.setDynamicSortFilter(True)
        self.connect(model, SIGNAL("dataChanged(QModelIndex, QModelIndex)"),
                     self._dataChanged)

    def _dataChanged(self, top_left, bottom_right):
        if top_left.column() <= 1 and bottom_right.column() >= 1:
            print >>sys.stderr, "invalidating"
            self.invalidate()

    def lessThan(self, left, right):
        r = super(CheckProxyModel, self).lessThan(left, right)
        if r or left.column() or right.column():
            return r
        if super(CheckProxyModel, self).lessThan(right, left):
            return False
        new_left = self.sourceModel().index(left.row(), 1)
        new_right = self.sourceModel().index(right.row(), 1)
        return super(CheckProxyModel, self).lessThan(new_left, new_right)

class I4CheckWindow(QWidget):
    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setWindowTitle("i4checklist")

        self.model = QStandardItemModel(0, 2, self)
        self.model.setHeaderData(0, Qt.Horizontal, u"Test")
        self.model.setHeaderData(1, Qt.Horizontal, u"Test2")
        for i in range(10, 0, -1):
            for item in [[NOT_NEEDED, "erunda %02d" % i],
                         [NEEDED, "fignya %02d" % i],
                         [CHECKED, "zzzzz %02d" % i]]:
                self.model.appendRow([QStandardItem(unicode(x)) for x in item])
        self.proxy_model = CheckProxyModel(self.model)

        self.treeview = QTreeView()
        self.treeview.setRootIsDecorated(False)
        # self.treeview.setSortingEnabled(True)
        self.treeview.setSelectionMode(QAbstractItemView.NoSelection)
        self.treeview.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.treeview.setAllColumnsShowFocus(True)
          #self.treeview.setAlternatingRowColors(True)
        self.treeview.setColumnWidth(0, 250)
        self.cbdelegate = CheckBoxDelegate()
        self.treeview.setItemDelegateForColumn(0, self.cbdelegate)
        self.treeview.setModel(self.proxy_model)
        # FIXME: sortByColumn(0, ...) here is not a real solution
        # as we need to sort by name too
        self.treeview.sortByColumn(0, Qt.AscendingOrder)
        self.treeview.header().setSortIndicatorShown(False)

        self.connect(self.treeview,
                     SIGNAL("clicked(const QModelIndex&)"),
                     self.itemClicked)
        self.button = QPushButton("Zzzz")
        self.connect(self.button, SIGNAL("clicked()"), self.zzzz)

        self.box = QVBoxLayout(self)
        self.box.addWidget(self.treeview)
        self.box.addWidget(self.button)
        # self.box.addWidget(QtGui.QCheckBox("zzzz"))

    def itemClicked(self, index):
        if index.column() > 0:
            return
        value = self.proxy_model.index(index.row(), 0).data().toPyObject()
        value = (int(value) + 1) % 3 # FIXME
        self.proxy_model.setData(self.proxy_model.index(index.row(), 0), value)

    def zzzz(self):
        print >>sys.stderr, "ZZZZZ"

#print >>sys.stderr, QtCore.Qt
app = QApplication(sys.argv)
widget = I4CheckWindow()
widget.show()
sys.exit(app.exec_())

#from cStringIO import StringIO
#print repr(list(parse_data(StringIO(SAMPLE_DATA))))
# TBD: should implement custom model
# TBD: should use a QFont with setStrikeOut(True) for checked items as Qt::FontRole
