import sys

# noinspection PyUnresolvedReferences
from PyQt5.QtWidgets import QApplication
from Interface import MainWindow
from database import EncodeQueue
from media_factory import DVDHandler, MediaFactory
from handbrake import HandbrakeHandler


class HandlebarApplication(QApplication):
    def __init__(self, args):
        super(HandlebarApplication, self).__init__(args)
        self.encode_queue = EncodeQueue('encode.db')
        self.dvd_handler = DVDHandler()
        self.handbrake_handler = HandbrakeHandler(
            r'C:\Program Files\Handbrake\HandBrakeCLI.exe', self.encode_queue, r'N:\Dan\Media', self.dvd_handler
        )
        self.media_factory = MediaFactory(self.dvd_handler, self.handbrake_handler)
        self.window = MainWindow(self)
        self.window.move(300, 300)
        self.window.show()
        self.encode_queue.set_enabled(True)


def main():
    app = HandlebarApplication(sys.argv)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
