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
        self.window = MainWindow(self)

        # TODO: Refactor things to decouple the dependency between EncodeQueue and DisplayList.
        # TODO: EncodeQueue should be passed to the UI rather than the other way around.
        self.dvd_handler = DVDHandler()
        self.encode_queue = EncodeQueue('encode.db', self.window.interface.queueDisplay)
        self.handbrake_handler = HandbrakeHandler(
            r'C:\Program Files\Handbrake\HandBrakeCLI.exe', self.encode_queue, r'N:\Christopher\Media', self.dvd_handler
        )
        self.media_factory = MediaFactory(self.dvd_handler, self.handbrake_handler)

        self.window.move(300, 300)
        self.window.show()
        self.encode_queue.set_enabled(True)


def main():
    app = HandlebarApplication(sys.argv)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
