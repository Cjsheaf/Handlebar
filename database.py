import sqlite3
import subprocess
import threading
from enum import IntEnum
from datetime import datetime


class EncodeStatus(IntEnum):
    """All recognized states that an encode job may be in. Used with the EncodeDatabase class"""
    Error = -1
    Stopped = 0
    Pending = 1
    In_Progress = 2
    Finished = 3


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
        self.db.execute(
            '''SELECT * FROM media WHERE encode_status=:status''',
            {'status': EncodeStatus.Pending.value}
        )
        return self.db.fetchall()

    def get_incomplete(self):
        """Includes "Stopped" (status 0), "Pending" (status 1), "In Progress" (status 2), and "Error" (status -1)"""
        self.db.execute(
            '''SELECT * FROM media WHERE encode_status<:status''',
            {'status': EncodeStatus.Finished.value}
        )
        return self.db.fetchall()

    def add_entry(self, media_filepath, handbrake_cmd):
        self.db.execute(
            '''INSERT INTO media
            (media_filepath, handbrake_cmd, encode_status, start_time, end_time)
            VALUES (?, ?, ?, ?, ?)''', (media_filepath, handbrake_cmd, EncodeStatus.Pending.value, None, None)
        )
        self.connection.commit()

    def start_encode(self, row_id):
        now = datetime.now()
        self.db.execute(
            '''UPDATE media SET encode_status=:status, start_time=:start WHERE id=:row''',
            {'status': EncodeStatus.In_Progress.value, 'start': now, 'row': row_id}
        )
        self.connection.commit()

    def finish_encode(self, row_id):
        now = datetime.now()
        self.db.execute(
            '''UPDATE media SET encode_status=:status, end_time=:end WHERE id=:row''',
            {'status': EncodeStatus.Finished.value, 'end': now, 'row': row_id}
        )
        self.connection.commit()


class EncodeQueue:
    def __init__(self, db_filepath, display_list=None, maxsize=0):
        self.db_filepath = db_filepath
        with EncodeDatabase(self.db_filepath) as db:
            if not db.verify_db():
                print('Database not initialized, creating new database...')
                db.construct_db()

        self.display_list = display_list
        self.enabled = False  # Do not start processing until setEnabled(True) is called.
        self.mediaReady = threading.Event()  # Used to resume the worker thread when new media is ready to be encoded.
        self.mediaReady.clear()  # Since EncodeQueue starts in a disabled state, pause the worker thread initially.

        # TODO: Allow the option to use more than one worker thread at a time.
        self.worker = threading.Thread(
            target=self._process_work,
            args=(self.db_filepath, self.mediaReady, self.display_list)
        )
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
            # Prevent any new jobs from being started.
            self.mediaReady.clear()

    def enqueue(self, media_filename, media_filepath, handbrake_cmd, block=False):
        from Interface import EncodeDisplay  # Putting this at the top of the file causes a circular-import.
        with EncodeDatabase(self.db_filepath) as db:
            db.add_entry(media_filepath, handbrake_cmd)
            if self.queue_display:
                #
                self.queue_display.new_displays.put_nowait(EncodeDisplay(media_filename, EncodeStatus.Pending))
        if self.enabled:
            self.mediaReady.set()  # Resume the worker thread if it has been waiting for media.

    @staticmethod
    def _process_work(db_path, media_ready, display_list=None):
        while True:
            media_ready.wait()  # Wait if no media is ready to be processed.
            media_filepath, handbrake_cmd = None, None

            # Open a new database connection each time we search for media to encode, and close it as soon as
            # we have the information. This is the only way to reliably share a database among multiple threads.
            print('Worker getting new job:')
            with EncodeDatabase(db_path) as db:
                pending = db.get_pending()  # Contains the tuple: (row_id, media_filepath, handbrake_cmd).
                print(repr(pending))
                if len(pending) == 0:  # If there is no media to process, make this thread wait until there is:
                    media_ready.clear()
                    continue  # Start the loop over, which will have the thread call wait() again.
                else:  # Get the information on the first pending item:
                    row_id, media_filepath, handbrake_cmd = pending[0]
                    db.start_encode(row_id)
                    print('\t' + repr(pending[0]))

            # The database connection MUST be closed immediately after retrieving pending job information.
            # If the connection was left open while encoding, no other threads could access it until encoding finished.

            # TODO: Verify that the mediaFilepath still points to a valid file.
            try:
                output = subprocess.Popen(handbrake_cmd, stdout=subprocess.PIPE, bufsize=1)

                # Parse the handbrake output in real time and periodically update the queue on the encode progress:
                for line in iter(output.stdout.readline, b''):
                    print(line)

                output.stdout.close()
                output.wait()
            except subprocess.CalledProcessError:
                print('Encode Failed!')

            # Now re-open the database with a new connection and change the status of this media item to 'complete'.
            with EncodeDatabase(db_path) as db:
                db.finish_encode(row_id)
                print('Worker completed job.')