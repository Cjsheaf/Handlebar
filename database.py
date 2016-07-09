import os
import sqlite3
import subprocess
import threading
import re
from enum import IntEnum
from datetime import datetime

from media_factory import DVDHandler, Media, MediaFactory
from handbrake import HandbrakeHandler
# noinspection PyUnresolvedReferences
from PyQt5.QtCore import (QThread, pyqtSignal)


class EncodeStatus(IntEnum):
    """All recognized states that an encode job can be in. Used with the EncodeDatabase class"""
    Error = -1
    Stopped = 0
    Pending_Rip = 1
    Ripping = 2
    Pending_Encode = 3
    Encoding = 4
    Finished = 5


class EncodeDatabase:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def __init__(self, db_filepath):
        self.connection = sqlite3.connect(db_filepath, detect_types=sqlite3.PARSE_DECLTYPES)
        self.db = self.connection.cursor()

        # Register the adapter and converter methods to store and retrieve Media objects seamlessly.
        sqlite3.register_adapter(Media, self.adapt_media)
        sqlite3.register_converter('MEDIA_OBJECT', self.convert_media)

    def verify_db(self):
        """Verify that the database is fully formed and includes all necessary tables."""
        self.db.execute('''SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'media_table\'''')
        if self.db.fetchone() is None:
            return False
        self.db.execute('''SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'media_lookup\'''')
        self.db.execute('''SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'encode_status\'''')
        if self.db.fetchone() is None:
            return False

        return True  # Return True if none of the previous tests failed.

    def construct_db(self):
        """Constructs an empty database and populates it with all necessary tables. Overwrites any old data."""
        self.db.execute(
            '''CREATE TABLE media_table
            (id INTEGER primary key autoincrement, media MEDIA_OBJECT, output_filepath TEXT,
            title_number INTEGER, encode_status INTEGER, start_time TIMESTAMP)'''
        )
        self.db.execute(
            '''CREATE TABLE media_lookup
            (media_filename TEXT UNIQUE, media_id INTEGER)'''
        )
        self.db.execute(
            '''CREATE TABLE encode_status
            (status INTEGER, name TEXT)'''
        )
        # TODO: Populate the encode_status table with the values in the EncodeStatus enum.
        self.connection.commit()

    def add_entry(self, media, output_filepath, title_number, encode_status=EncodeStatus.Pending_Rip):
        now = datetime.now()
        self.db.execute(
            '''INSERT INTO media_table
            (media, output_filepath, title_number, encode_status, start_time)
            VALUES (?, ?, ?, ?, ?)''',
            (media, output_filepath, title_number, encode_status.value, now)
        )
        self.db.execute(
            '''INSERT INTO media_lookup
            (media_filename, media_id)
            VALUES (?, ?)''',
            (media.file_name, self.db.lastrowid)
        )
        self.connection.commit()

    def get_with_status(self, encode_status):
        if not isinstance(encode_status, EncodeStatus):
            raise RuntimeError('Argument encode_status must be an instance of the EncodeStatus Enum!')

        self.db.execute(
            '''SELECT * FROM media_table WHERE encode_status=:status''',
            {'status': encode_status.value}
        )
        return self.db.fetchall()

    def set_status(self, row_id, encode_status):
        if not isinstance(encode_status, EncodeStatus):
            raise RuntimeError('Argument encode_status must be an instance of the EncodeStatus Enum!')

        now = datetime.now()
        self.db.execute(
            '''UPDATE media_table SET encode_status=:status, start_time=:start WHERE id=:row''',
            {'status': encode_status.value, 'start': now, 'row': row_id}
        )
        self.connection.commit()

    def update_media(self, row_id, updated_media):
        self.db.execute(
            '''UPDATE media_table SET media=:updated WHERE id=:row''',
            {'updated': updated_media, 'row': row_id}
        )
        self.connection.commit()

    def get_with_name(self, media_filename):
        self.db.execute(
            '''SELECT media_id FROM media_lookup where media_filename=:filename''',
            {'filename': media_filename}
        )
        row = self.db.fetchone()
        if not row:
            return None

        row_id = int(row[0])
        self.db.execute(
            '''SELECT * FROM media_table WHERE id=:row''',
            {'row': row_id}
        )
        return self.db.fetchone()  # There cannot be duplicate entries for the same media file.

    @staticmethod
    def adapt_media(media):
        media_string = '{path};{handbrake_path};{source_type};{media_type};{volume};{year};{season}'.format(
            path=media.get_source_path(),
            handbrake_path=media.handbrake_path,
            source_type=media.source_type,
            media_type=media.media_type,
            volume=(lambda: media.file_name if media.source_type == 'drive' else None)(),
            year=media.year,
            season=media.season
        )
        print('Storing media object into database:', media_string)
        return media_string

    @staticmethod
    def convert_media(db_string):
        path, handbrake_path, source_type, media_type, volume, year, season = db_string.decode('ascii').split(';')
        print('Reading media object from database:', db_string.decode('ascii'))
        if volume == 'None':
            volume = None
        media = Media(path, handbrake_path, source_type, media_type, volume)
        if year != 'None':
            media.year = int(year)
        if season != 'None':
            media.season = int(season)
        return media


class WorkQueue:
    def __init__(self, db_filepath, program_settings, display_list=None):
        self.db_filepath = db_filepath
        with EncodeDatabase(self.db_filepath) as db:
            if not db.verify_db():
                print('Database not initialized, creating new database...')
                db.construct_db()

        self.program_settings = program_settings
        self.display_list = display_list
        self.enabled = False  # Do not start processing until setEnabled(True) is called.

        # Used to resume the worker thread when new media is ready to be ripped or encoded.
        # Since WorkQueue starts in a disabled state, pause the worker threads initially.
        self.rip_ready = threading.Event()
        self.rip_ready.clear()
        self.encode_ready = threading.Event()
        self.encode_ready.clear()

        # TODO: Allow the option to use more than one worker thread at a time.
        self.rip_worker = RipThread(self.db_filepath, self.rip_ready, self.encode_ready, self.program_settings, self.display_list)
        self.rip_worker.start()
        self.encode_worker = EncodeThread(self.db_filepath, self.encode_ready, self.program_settings, self.display_list)
        self.encode_worker.start()

        self.restart_incomplete_jobs()

    def restart_incomplete_jobs(self):
        """Search for any incomplete jobs present in the database, and start them over again."""
        incomplete = []
        with EncodeDatabase(self.db_filepath) as db:
            incomplete.extend(db.get_with_status(EncodeStatus.Pending_Rip))
            incomplete.extend(db.get_with_status(EncodeStatus.Pending_Encode))

        for job in incomplete:
            print(repr(job))

    def __len__(self):
        with EncodeDatabase(self.db_filepath) as db:
            return len(db.get_with_status(EncodeStatus.Pending_Encode))

    def set_enabled(self, is_enabled):
        self.enabled = bool(is_enabled)
        if self.enabled:
            print('Resuming worker thread.')
            self.encode_ready.set()
        else:
            # Prevent any new jobs from being started.
            self.encode_ready.clear()

    def enqueue(self, media, output_filepath, title_number, do_rip=True):
        if do_rip:
            new_status = EncodeStatus.Pending_Rip
        else:
            new_status = EncodeStatus.Pending_Encode

        # TODO: Warn the user if a DB entry for this media already exists (a potential duplicate job).
        with EncodeDatabase(self.db_filepath) as db:
            if not db.get_with_name(media.file_name):
                db.add_entry(media, output_filepath, title_number, new_status)

        if not self.display_list.getDisplay(media.media_name):
            self.display_list.createDisplay(media.media_name, new_status)

        if self.enabled:
            if do_rip:
                self.rip_ready.set()
            else:
                self.encode_ready.set()


class RipThread(QThread):
    status_change = pyqtSignal(object)
    progress_change = pyqtSignal(int)

    def __init__(self, db_path, rip_ready, encode_ready, program_settings, display_list=None):
        super(RipThread, self).__init__()
        self.db_path = db_path
        self.rip_ready = rip_ready
        self.encode_ready = encode_ready  # TODO: Do not signal the encode thread directly. Use WorkQueue.enqueue() instead.
        self.program_settings = program_settings
        self.display_list = display_list

    def run(self):
        while True:
            self.rip_ready.wait()

            work = self.get_work()
            if work:
                row_id, media, output_filepath, title_number = work
            else:
                continue

            if self.display_list:
                display = self.display_list.getDisplay(media.media_name)
                if display:
                    self.status_change.connect(display.set_status)
                    self.status_change.emit(EncodeStatus.Ripping)
                    self.progress_change.connect(display.set_progress)
                    self.progress_change.emit(0)

            temp_file = os.path.abspath(
                os.path.join(
                    self.program_settings['handlebar']['temp_directory'],
                    os.path.splitext(media.file_name)[0] + '.iso'
                )
            )
            DVDHandler.save_to_file(media, temp_file, progress_callback=self.progress_change.emit)
            with EncodeDatabase(self.db_path) as db:
                # Signal that the media is ready to be encoded. The media source will now be the newly-ripped temp file.
                ripped_media = MediaFactory.read_media_from_file(temp_file, self.program_settings)
                ripped_media.media_type = media.media_type
                # TODO: Find a more permanent solution for ensuring the media_name stays the same between
                # TODO: media instances. It's possible to have a malformed name stored in the original.
                ripped_media.media_name = media.media_name
                db.update_media(row_id, ripped_media)  # Update the media object to reference the temp file.
                db.set_status(row_id, EncodeStatus.Pending_Encode)

            self.status_change.emit(EncodeStatus.Pending_Encode)

            # TODO: Do not signal the encode thread directly. Use WorkQueue.enqueue() instead.
            self.encode_ready.set()

    def get_work(self):
        with EncodeDatabase(self.db_path) as db:
            pending = db.get_with_status(EncodeStatus.Pending_Rip)
            if len(pending) == 0:
                self.rip_ready.clear()
                return None
            else:
                print(repr(pending[0]))
                db.set_status(pending[0][0], EncodeStatus.Ripping)
                return pending[0][:4]


class EncodeThread(QThread):
    status_change = pyqtSignal(object)
    progress_change = pyqtSignal(int)

    def __init__(self, db_path, encode_ready, program_settings, display_list=None):
        super(EncodeThread, self).__init__()
        self.db_path = db_path
        self.encode_ready = encode_ready
        self.display_list = display_list
        self.program_settings = program_settings

    def run(self):
        while True:
            self.encode_ready.wait()  # Wait if no media is ready to be processed.

            work = self.get_work()
            if work:
                row_id, media, output_filepath, title_number = work
                handbrake_cmd = HandbrakeHandler.build_handbrake_cmd(
                    self.program_settings, media, output_filepath, title_number
                )
            else:
                continue  # Start the loop over, which will have the thread call wait() again.

            if self.display_list:
                display = self.display_list.getDisplay(media.media_name)
                if display:
                    self.status_change.connect(display.set_status)
                    self.status_change.emit(EncodeStatus.Encoding)
                    self.progress_change.connect(display.set_progress)
                    self.progress_change.emit(0)

            # Create a handbrake log file with the same name as the media_filename (but with the .log extension).
            log_filename = os.path.splitext(os.path.basename(media.file_name))[0] + '.log'
            handbrake_log = open(log_filename, 'w')

            try:
                self.encode(handbrake_cmd, display, handbrake_log)
            except subprocess.CalledProcessError:
                print('Encode Failed!')
                if display:
                    self.status_change.emit(EncodeStatus.Error)

            # Now re-open the database with a new connection and change the status of this media item to 'Finished'.
            with EncodeDatabase(self.db_path) as db:
                db.set_status(row_id, EncodeStatus.Finished)
                print('Worker completed job.')

    def encode(self, handbrake_cmd, display=None, log_file=None):
        if not log_file:
            log_file = subprocess.DEVNULL  # Do not print stderr to anything if a log file is not given.
        # TODO: Verify that the mediaFilepath still points to a valid file.
        process = subprocess.Popen(handbrake_cmd, stdout=subprocess.PIPE, stderr=log_file, bufsize=1)

        if display:
            # Parse the handbrake output in real time and periodically update the queue on the encode progress.
            # Handbrake uses carriage returns '\r' when displaying encode progress updates, so we must parse
            # the output character-by-character looking for '\r'.
            line = []
            for character in iter(lambda: process.stdout.read(1), b''):
                line.append(character)  # Collect characters until we have a complete line (until a '\r' is found).
                if character == b'\r':
                    # Convert the output from a list of binary strings to a regular string for easier processing.
                    decoded_line = b''.join(line).decode('ascii')
                    line = []
                    # Look for the integer portion of the encode percentage that Handbrake reports.
                    match = re.search(r'^Encoding: task \d+ of \d+, (\d+)\.\d+ %', decoded_line)
                    if match:
                        # Update the EncodeDisplay's progress bar with the encode percentage.
                        self.progress_change.emit(int(match.group(1)))

        process.stdout.close()
        process.wait()

        # If the process gets this far without throwing an exception, it means that Handbrake has completed
        # successfully (returned a 0). Note: This does not guarantee the encode was successful, only that
        # Handbrake reported no errors.
        if display:
            self.progress_change.emit(100)
            self.status_change.emit(EncodeStatus.Finished)

    def get_work(self):
        # Open a new database connection each time we search for media to encode, and close it as soon as
        # we have the information. This is the only way to reliably share a database among multiple threads.
        print('Worker getting new job:')
        with EncodeDatabase(self.db_path) as db:
            pending = db.get_with_status(EncodeStatus.Pending_Encode)  # Contains the tuple: (row_id, media_filepath, handbrake_cmd).
            if len(pending) == 0:  # If there is no media to process, make this thread wait until there is:
                self.encode_ready.clear()
                return None
            else:  # Get the information for the first pending item:
                print(repr(pending[0]))
                db.set_status(pending[0][0], EncodeStatus.Encoding)
                return pending[0][:4]

        # The database connection MUST be closed immediately after retrieving pending job information.
        # If the connection was left open while encoding, no other threads could access it until encoding finished.
