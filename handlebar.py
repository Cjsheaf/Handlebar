import sys

import settings
# noinspection PyUnresolvedReferences
from PyQt5.QtWidgets import QApplication
from Interface import MainWindow
from database import WorkQueue
from media_factory import DVDHandler, MediaFactory
from handbrake import HandbrakeHandler


class HandlebarApplication(QApplication):
    def __init__(self, args):
        super(HandlebarApplication, self).__init__(args)
        self.window = MainWindow(self)

        # TODO: Load these settings objects from a configuration file.
        self.program_settings = settings.SettingsObject(r'.\settings.ini', settings.get_handlebar_defaults())
        if self.program_settings['handbrake']['handbrake_path'] == 'not_set':
            pass  # TODO: Prompt the user to set the handbrake_path if it's not set.

        # TODO: Refactor things to decouple the dependency between WorkQueue and DisplayList.
        # TODO: EncodeQueue should be passed to the UI rather than the other way around.
        self.dvd_handler = DVDHandler()
        self.work_queue = WorkQueue('encode.db', self.program_settings, self.window.interface.queueDisplay)
        self.handbrake_handler = HandbrakeHandler(
            r'C:\Program Files\Handbrake\HandBrakeCLI.exe', self.work_queue, r'N:\Christopher\Media', self.dvd_handler
        )
        self.media_factory = MediaFactory(self.dvd_handler, self.handbrake_handler.handbrake_path)

        self.window.move(300, 300)
        self.window.show()
        self.work_queue.set_enabled(True)


def main():
    app = HandlebarApplication(sys.argv)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
