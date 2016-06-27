import sys
import threading

# noinspection PyUnresolvedReferences
from PyQt5.QtCore import (QThread, pyqtSignal, QTimer)
# noinspection PyUnresolvedReferences
from PyQt5.QtWidgets import (QApplication, QFrame, QWidget, QProgressBar, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMainWindow)


class ProducerThread(QThread):
    progress_update = pyqtSignal(int)

    def __init__(self, name, display_list):
        super(ProducerThread, self).__init__()
        self.name = name
        self.progress_value = 0
        self.display_list = display_list
        self.display = self.display_list.create_display(self.name)
        self.progress_update.connect(self.display.set_progress)

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start(200)

    def update(self):
        self.progress_value += 1
        self.progress_update.emit(self.progress_value)


class ProgressDisplay(QFrame):
    def __init__(self, name):
        super(ProgressDisplay, self).__init__()
        self.name = name

        self.main_layout = QHBoxLayout()
        self.setLayout(self.main_layout)

        self.name_label = QLabel(self.name)
        self.progress_bar = QProgressBar()
        self.do_layout()

    def do_layout(self):
        self.progress_bar.minimum = 0
        self.progress_bar.maximum = 100

        self.main_layout.addWidget(self.name_label)
        self.main_layout.addWidget(self.progress_bar)

    def set_progress(self, progress_value):
        """Should be used as a QT slot, and ONLY called as the result of a QT signal"""
        self.progress_bar.setValue(progress_value)


class DisplayList(QFrame):
    init_display = pyqtSignal(str, object)  # Used internally

    def __init__(self):
        super(DisplayList, self).__init__()
        self.displays = {}  # ProgressDisplay instances are stored under their display name.
        self.display_widget = QListWidget(self)
        self.init_display.connect(self._init_display)

    def get_display(self, display_name):
        if display_name in self.displays.keys():
            return self.displays[display_name]
        else:
            return None

    def create_display(self, display_name):
        """Creates and returns a new ProgressDisplay instance in a thread-safe manner.
        Can be called from any thread, and will block until the display has been created by the main QT thread."""
        ready_event = threading.Event()
        ready_event.clear()

        self.init_display.emit(display_name, ready_event)
        ready_event.wait()
        return self.displays[display_name]

    def _init_display(self, display_name, ready_event):
        """This private method is called by the main QT thread in response to create_display being called.
        """
        display = ProgressDisplay(display_name)
        list_item = QListWidgetItem()
        list_item.setSizeHint(display.sizeHint())
        self.display_widget.addItem(list_item)
        self.display_widget.setItemWidget(list_item, display)
        self.displays[display_name] = display
        ready_event.set()

def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.move(300, 300)
    window.resize(250, 250)

    display_list = DisplayList()
    window.setCentralWidget(display_list)

    ProducerThread('Producer 1', display_list)
    ProducerThread('Producer 2', display_list)
    ProducerThread('Producer 3', display_list)

    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()