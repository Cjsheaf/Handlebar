import os.path
import re
import sqlite3

import wmi
from dvdvideo.utils import ProgressStream

import dvdvideo_backup_image


class lazy_property:
    """From an excellent StackOverflow answer here: http://stackoverflow.com/a/6849299/1741965"""
    def __init__(self, parent_func):
        self.parent_func = parent_func
        self.func_name = parent_func.__name__

    def __get__(self, obj, cls):
        if obj is None:
            return None
        value = self.parent_func(obj)
        setattr(obj, self.func_name, value)  # Very elegant way to lazily initialize value
        return value


class Media:
    """Generic container class for information describing a media file in either a CDROM drive or an .iso file.

    Primarily intended to be instantiated via a method of the MediaFactory class such as read_media_from_drives()
    or read_media_from_file().
    """

    @lazy_property
    def titles(self):
        """titles stores a semi-formatted nested dictionary tree of information. The information is parsed from a
        Handbrake scan log, which is performed lazily because it is an expensive operation. Title numbers in the
        range [1-99] are used as the dictionary keys."""
        from handbrake import TitleScan
        if self.source_type == 'drive':
            return TitleScan(self.handbrake_path, self.image_path).titles
        else:
            return TitleScan(self.handbrake_path, self.get_source_path()).titles

    @property
    def source_type(self):
        return self._source_type

    @source_type.setter
    def source_type(self, value):
        if value == 'file' or value == 'drive':
            self._source_type = value
        else:
            raise ValueError(
                'Argument source_type can only be "file" or "drive"! "{}" was given.'.format(value)
            )

    @property
    def media_type(self):
        return self._media_type

    @media_type.setter
    def media_type(self, value):
        if value == 'movie' or value == 'series':
            self._media_type = value
        else:
            raise ValueError(
                'Argument media_type can only be "movie" or "series"! "{}" was given.'.format(value)
            )

    def __init__(self, image_filepath, handbrake_path, source_type='file', media_type='movie', volume_name=None):
        """image_filepath may also be a drive letter, such as 'G:'"""
        self.handbrake_path = handbrake_path
        self.source_type = source_type
        self.media_type = media_type

        # image_path is either the drive letter or path to the directory containing this media image.
        # file_name will be the name of the file, or the VolumeName if the media is from a drive.
        self.image_path, self.file_name = self._format_paths(image_filepath, volume_name)
        # media_name is a formatted version of file_name in Title Case and without any special characters.
        self.media_name = self._format_media_name(self.file_name)
        self.year = None
        self.season = None  # Only applies to a media_type of 'series'

    @staticmethod
    def _format_paths(image_filepath, volume_name):
        # If the filepath is a drive letter with no trailing backslashes, os.path.abspath() does not work as needed.
        # Handle this case by ensuring any drive letter (if present) has at least one backslash:
        drive_letter, tail = os.path.splitdrive(image_filepath)
        if drive_letter:
            drive_letter = os.path.join(drive_letter, '\\')
            image_filepath = os.path.abspath(os.path.join(drive_letter, tail.lstrip('\\')))

        # If a volume_name has been provided, this media image must be from a drive rather than a file.
        # In that case, there is no file name, so we use the volume_name instead. The "directory" is simply the drive.
        if volume_name:
            return (drive_letter, volume_name)
        else:
            return os.path.split(image_filepath)

    @staticmethod
    def _format_media_name(file_name):
        stripped_name = os.path.splitext(file_name)[0]
        stripped_name = re.sub(r'[^_ \w]', '', stripped_name)  # Strip unnecessary punctuation.
        stripped_name = stripped_name.replace('_', ' ')  # Use space characters only for word spacing.
        return Media.to_title_case(stripped_name)

    @staticmethod
    def to_title_case(name, articles=('a', 'an', 'of', 'the', 'is')):
        """Found in the StackOverflow answer here: http://stackoverflow.com/a/3729957/1741965"""
        word_list = re.split(' ', name)
        final = [word_list[0].capitalize()]
        for word in word_list[1:]:
            final.append(word in articles and word or word.capitalize())
        return " ".join(final)

    def get_source_path(self):
        if self.source_type == 'drive':
            return self.image_path  # Media in a drive has no file name. Return only the drive letter.
        else:
            return os.path.join(self.image_path, self.file_name)

    def __iter__(self):
        return iter(self.titles.keys())

    def items(self):
        return self.titles.items()

    def format_name(self, media_formatter):
        """In order to accommodate any possible file naming scheme, this method calls the format_media() method of
        any provided formatter object and passes this Media instance as the argument."""
        return media_formatter.format_media(self)


class PLEXFormatter:
    @staticmethod
    def format_media(media):
        return '{name} ({year}).mkv'.format(name=media.media_name, year=media.year)


class MediaFactory:
    def __init__(self, dvd_handler, handbrake_path):
        self.dvd_handler = dvd_handler
        self.handbrake_path = handbrake_path

    # TODO: Make this a static method that does not rely on a MediaFactory instance to hold state.
    def read_media_from_drives(self):
        """Scans all system drives for media and returns a list of Media objects created from the loaded drives."""
        self.dvd_handler.scan_drives()
        return [Media(drive.Drive, self.handbrake_path, source_type='drive', volume_name=drive.VolumeName)
                for drive in self.dvd_handler.get_media_drives()]

    @staticmethod
    def read_media_from_file(filepath, program_settings):
        return Media(filepath, program_settings['handbrake']['handbrake_path'], source_type='file')


class DVDHandler:
    def __init__(self, initial_scan=False):
        self.win = wmi.WMI(find_classes=False)
        self.drives = {}
        if initial_scan is True:
            self.scan_drives()

    def drive_has_media(self, drive):
        if isinstance(drive, str):
            d = self.drives[drive]
        else:
            d = drive
        return d.MediaLoaded

    @staticmethod
    def save_to_file(media, output_filepath, progress_callback=None):
        # The save function writes a progress bar to a text stream. We want to parse that text in real time in order
        # to determine what percentage is complete. The ProgressWrapper class does exactly this by acting like a stream.
        stream = ProgressWrapper(progress_callback)

        print('Saving to file: "{}"'.format(output_filepath))
        if media.source_type == 'drive':
            drive = media.image_path.rstrip('\\')
            dvdvideo_backup_image.main(ProgressStream(stream), r'\\.\{}'.format(drive), output_filepath)
        else:
            raise RuntimeError('Media source is not from a drive and does not need to be saved to a file!')

    def scan_drives(self):
        for cdrom in self.win.Win32_CDROMDrive():
            self.drives[cdrom.Drive] = cdrom  # Store the WMI CDROM object using its drive letter. (Example: 'F:')

    def get_media_drives(self):
        return [drive for letter, drive in self.drives.items() if drive.MediaLoaded]

    def media_properties(self, drive):
        properties = {}

        # Take certain properties from the CDROM Drive and store them with more general names
        drive_properties = ['Drive', 'Size', 'VolumeName']
        media_properties = ['Path', 'Size', 'Name']
        for d, m in zip(drive_properties, media_properties):
            properties[m] = getattr(self.drives[drive], d)

        return properties


class ProgressWrapper:
    def __init__(self, callback=None):
        self.percent = 0  # Integer value between 0 and 100 (inclusive)
        self.text = ''
        self.callback = callback

    def write(self, text):
        self.text += text

    def flush(self):
        self.percent = int(re.search(r' (\d{1,3})%$', self.text).group(1))
        self.text = ''
        if self.callback:
            self.callback(self.percent)


class SubtitleTrack:
    def __init__(self, track_number, language):
        self.track_number = track_number
        self.language = language

    def __lt__(self, other):
        if other:
            return self.track_number < other.track_number
        else:
            return False


class AudioTrack:
    def __init__(self, track_number, language, encoding, channels, hertz, bitrate):
        self.track_number = track_number
        self.language = language
        self.encoding = encoding
        self.channels = channels
        self.hertz = hertz
        self.bitrate = bitrate

    def __lt__(self, other):
        if other:
            return self.track_number < other.track_number
        else:
            return False


class TrackList(list):
    """A list-like container that starts at index 1 instead of index 0"""
    def __init__(self, iterable):
        self._data = list(iterable)

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, index):
        return self._data[index - 1]

    def __setitem__(self, index, value):
        self._data[index - 1] = value


class Title:
    """Every movie or series is comprised of at least one title, which in turn usually contains multiple video
    and audio tracks. Not to be confused with the NAME of the movie or series."""
    def __init__(self, duration, resolution, framerate, subtitle_tracks=None, audio_tracks=None):
        self.duration = duration  # In seconds
        self.resolution = resolution
        self.framerate = framerate

        # Track numbers use 1-based indexes, so the TrackList objects act like a list that starts at index 1.
        self.subtitle_tracks = TrackList(subtitle_tracks)
        self.audio_tracks = TrackList(audio_tracks)