import sys
import subprocess
import sqlite3
import threading
from datetime import datetime

# noinspection PyUnresolvedReferences
from PyQt5.QtWidgets import QApplication
from Interface import MainWindow
from MediaFactory import DVDHandler, HandbrakeHandler, MediaFactory


class EncodeDatabase:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def __init__(self, db_filepath):
        self.connection = sqlite3.connect(db_filepath, detect_types=sqlite3.PARSE_DECLTYPES)
        self.db = self.connection.cursor()

    def verify_db(self):
        """Verify that the database is fully formed and includes all necessary tables."""
        self.db.execute('''SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'media\'''')
        if self.db.fetchone() is None:
            return False

        self.db.execute('''SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'encode_status\'''')
        if self.db.fetchone() is None:
            return False

        return True

    def construct_db(self):
        """Constructs an empty database and populates it with all necessary tables. Overwrites any old data."""
        self.db.execute(
            '''CREATE TABLE media
            (id INTEGER primary key autoincrement, media_filepath TEXT, handbrake_cmd TEXT,
            encode_status INTEGER, start_time TIMESTAMP, end_time TIMESTAMP)'''
        )
        self.db.execute(
            '''CREATE TABLE encode_status
            (status INTEGER, name TEXT)'''
        )
        self.connection.commit()

    def get_pending(self):
        self.db.execute('''SELECT * FROM media WHERE encode_status=1''')
        return self.db.fetchall()

    def get_incomplete(self):
        # Includes "Pending" (status 0), "In Progress" (status 2), and "Error" (status -1)
        self.db.execute('''SELECT * FROM media WHERE encode_status<3''')
        return self.db.fetchall()

    def add_entry(self, media_filepath, handbrake_cmd):
        self.db.execute(
            '''INSERT INTO media
            (media_filepath, handbrake_cmd, encode_status, start_time, end_time)
            VALUES (?, ?, ?, ?, ?)''', (media_filepath, handbrake_cmd, 1, None, None)
        )
        self.connection.commit()

    def start_encode(self, row_id):
        now = datetime.now()
        self.db.execute(
            '''UPDATE media SET encode_status=2, start_time=? WHERE id=?''',
            (now, row_id)
        )
        self.connection.commit()

    def finish_encode(self, row_id):
        now = datetime.now()
        self.db.execute(
            '''UPDATE media SET encode_status=3, end_time=? WHERE id=?''',
            (now, row_id)
        )
        self.connection.commit()


class EncodeQueue:
    def __init__(self, db_filepath, maxsize=0):
        self.db_filepath = db_filepath
        with EncodeDatabase(self.db_filepath) as db:
            if not db.verify_db():
                print('Database not initialized, creating new database...')
                db.construct_db()

        self.enabled = False  # Do not start processing until setEnabled(True) is called.
        self.mediaReady = threading.Event()  # Used to resume the worker thread when new media is ready to be encoded.
        self.mediaReady.clear()  # Since EncodeQueue starts in a disabled state, pause the worker thread initially.

        self.worker = threading.Thread(target=self._process_work, args=(self.db_filepath, self.mediaReady))
        self.worker.setDaemon(True)
        self.worker.start()

    def __len__(self):
        with EncodeDatabase(self.db_filepath) as db:
            return len(db.get_pending())

    def get_incomplete(self):
        with EncodeDatabase(self.db_filepath) as db:
            return db.get_incomplete()

    def set_enabled(self, is_enabled):
        self.enabled = bool(is_enabled)
        if self.enabled:
            print('Resuming worker thread.')
            self.mediaReady.set()
        else:
            self.mediaReady.clear()

    def enqueue(self, media_filepath, handbrake_cmd, block=False):
        """Argument 'media' should be a tuple with [0] as the media filepath, and [1] as the handbrake command"""
        # super(EncodeQueue, self).put(media, block=block)
        with EncodeDatabase(self.db_filepath) as db:
            db.add_entry(media_filepath, handbrake_cmd)
        if self.enabled:
            self.mediaReady.set()  # Resume the worker thread if it has been waiting for media.

    @staticmethod
    def _process_work(db_path, media_ready):
        while True:
            media_ready.wait()  # Wait if no media is ready to be processed.

            # Open a new database connection each time we search for media to encode, and close it as soon as
            # we have the information. This is the only way to reliably share a database among multiple threads.
            print('Worker getting new job:')
            with EncodeDatabase(db_path) as db:
                pending = db.get_pending()
                print(repr(pending))
                if len(pending) == 0:  # If there is no media to process, make this thread wait until there is:
                    media_ready.clear()
                    continue
                else:  # Get the information on the first pending item:
                    row_id = pending[0][0]
                    media = (pending[0][1], pending[0][2])  # Contains: (mediaFilepath, handbrakeCmd).
                    db.start_encode(row_id)
                    print('\t' + repr(media))

            # The database connection MUST be closed immediately after retrieving pending job information.
            # If the connection was left open while encoding, no other threads could access it until encoding finished.

            # TODO: Verify that the mediaFilepath still points to a valid file.
            try:
                output = subprocess.check_output(media[1], universal_newlines=True, stderr=subprocess.STDOUT)
                print(output)
            except subprocess.CalledProcessError:
                print('Encode Failed!')

            # Now re-open the database with a new connection and change the status of this media item to 'complete'.
            with EncodeDatabase(db_path) as db:
                db.finish_encode(row_id)
                print('Worker completed job.')


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
