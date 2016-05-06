import wmi
import re
import os.path
import subprocess
import threading

import dvdvideo_backup_image
from dvdvideo.utils import ProgressStream


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


class Test:
    def __init__(self):
        @lazy_property
        def results(self):
            calcs = 'Really obvious test string.'
            return calcs


class LazyTitleScan:
    def __init__(self, media, handbrake_handler):
        self.media = media
        self.handbrake_handler = handbrake_handler
        self.titles = None

    def __get__(self, obj, cls):
        if self.titles is None:
            # TODO: Make HandbrakeHandler support Media objects.
            self.handbrake_handler.load_media(self.media.get_source_path())
            self.titles = self.handbrake_handler.get_title_info()
        return self.titles


class Media:
    """Generic container class for information describing a media file in either a CDROM drive or an .iso file.

    Primarily intended to be instantiated via a method of the MediaFactory class such as read_media_from_drives()
    or read_media_from_file().
    """
    def __init__(self, image_filepath, handbrake_handler, source_type='file', media_type='movie', volume_name=None):
        """image_filepath may also be a drive letter, such as 'G:'"""

        if source_type is 'file' or source_type is 'drive':
            self.source_type = source_type
        else:
            raise ValueError(
                'Argument source_type can only be "file" or "drive"! "{}" was given.'.format(source_type)
            )
        if media_type is 'movie' or media_type is 'series':
            self.media_type = media_type
        else:
            raise ValueError(
                'Argument media_type can only be "movie" or "series"! "{}" was given.'.format(media_type)
            )

        # image_path is either the drive letter or path to the directory containing this media image.
        # file_name will be the name of the file, or the VolumeName if the media is from a drive.
        self.image_path, self.file_name = self._format_paths(image_filepath, volume_name)
        # media_name is a formatted version of file_name in Title Case and without any special characters.
        self.media_name = self._format_media_name(self.file_name)

        # titles stores a semi-formatted nested dictionary tree of information. The information is parsed from a
        # Handbrake scan log, which is an expensive operation, so it is lazily evaluated. Title numbers in the
        # range [1-99] are used as the dictionary keys.
        @lazy_property
        def titles(self):
            handbrake_handler.load_media(self.get_source_path())
            return handbrake_handler.get_title_info()
        self.year = None
        self.season = None  # Only applies to a media_type of 'series'

    @staticmethod
    def _format_paths(image_filepath, volume_name):
        # If the filepath is a drive letter with no trailing backslashes, os.path.abspath() does not work as needed.
        # Handle this case by ensuring any drive letter (if present) has at least one backslash:
        drive_letter, tail = os.path.splitdrive(image_filepath)
        if drive_letter:
            image_filepath = os.path.abspath(os.path.join(drive_letter, '\\', tail.lstrip('\\')))

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
        if self.source_type is 'drive':
            return self.image_path  # Media in a drive has no file name. Return only the drive letter.
        else:
            return os.path.join(self.image_path, self.file_name)

    def __iter__(self):
        return iter(self.titles.keys())

    def items(self):
        return self.titles.items()

    def is_movie(self, set_movie=False):
        if set_movie:
            self.media_type = 'movie'

        if self.media_type is 'movie':
            return True
        else:
            return False

    def is_series(self, set_series=False):
        if set_series:
            self.media_type = 'series'

        if self.media_type is 'series':
            return True
        else:
            return False

    def format_as(self, media_formatter):
        """In order to accommodate any possible file naming scheme, this method calls the format_media() method of
        any provided formatter object and passes itself as the argument."""
        return media_formatter.format_media(self)


class PLEXFormatter:
    @staticmethod
    def format_media(media):
        return '{name} ({year}).mkv'.format(name=media.media_name, year=media.year)


class MediaFactory:
    def __init__(self, dvd_handler, handbrake_handler):
        self.dvd_handler = dvd_handler
        self.handbrake_handler = handbrake_handler

    def read_media_from_drives(self):
        """Scans all system drives for media and returns a list of Media objects created from the loaded drives."""
        self.dvd_handler.scan_drives()
        return [Media(drive.Drive, self.handbrake_handler, source_type='drive', volume_name=drive.VolumeName)
                for drive in self.dvd_handler.get_media_drives()]

    def read_media_from_file(self, filepath):
        pass


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
    def save_to_file(drive, filepath, queue_display=None):
        # The save function writes a progress bar to a text stream. We want to parse that text in real time in order
        # to determine what percentage is complete. The ProgressWrapper class does exactly this by acting like a stream.
        stream = ProgressWrapper()

        if queue_display:
            pass

        drive = drive.rstrip('\\')
        dvdvideo_backup_image.main(ProgressStream(stream), r'\\.\{}'.format(drive), filepath)

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
    def __init__(self, callback=None, media_name=None):
        self.percent = 0  # Integer value between 0 and 100 (inclusive)
        self.text = ''
        self.callback = callback
        self.mediaName = media_name

    def write(self, text):
        self.text += text

    def flush(self):
        self.percent = int(re.search(r' (\d{1,3})%$', self.text).group(1))
        self.text = ''
        if self.callback is not None:
            self.callback(self.percent)


class HandbrakeHandler:
    def __init__(self, handbrake_path, encode_queue, plex_path, dvd_handler, settings_file=None):
        self.handbrake_path = handbrake_path
        self.encode_queue = encode_queue
        self.plex_path = plex_path
        self.dvd_handler = dvd_handler
        self.media_path = None
        self.title_count = 0
        self.titles = {}  # A dictionary that contains any number of nested sub-dictionaries. Poor-man's tree structure.
        self.handbrake_args = self.get_default_handbrake_args()
        self.is_media_set = False

    @staticmethod
    def get_default_handbrake_args():
        args = [
            '-f', 'mkv',
            '--loose-anamorphic',
            '--modulus', '2',
            '-e', 'x264',
            '-q', '26',  # Set a slightly higher than average quality
            '--vfr'  # Use variable frame rate
        ]
        return args

    # TODO: Eventually break getTitleInfo() into individual methods that do not use a nested dict.
    def get_title_info(self):
        if not self.is_media_set:
            raise RuntimeError('No media was loaded to get title information for! Call "loadMedia()" first!')
        info = {}

        for title in self.titles.keys():
            title_number = int(re.search(r'^title (\d+):$', title).group(1))
            info[title_number] = {}
            # Find the key starting with the string 'duration:' and extract the actual duration from it:
            for titleKey in self.titles[title].keys():
                match = re.search(r'^duration: ((\d+):(\d+):(\d+))$', titleKey)
                if match:
                    info[title_number]['duration'] = match.group(1)
                    hours = int(match.group(2))
                    minutes = (hours * 60) + int(match.group(3))
                    seconds = (minutes * 60) + int(match.group(4))
                    info[title_number]['duration_seconds'] = seconds

                match = re.search(r'^subtitle tracks:$', titleKey)
                if match:
                    info[title_number]['subtitles'] = []
                    for sub in self.titles[title][titleKey].keys():
                        info[title_number]['subtitles'].append(sub)

                match = re.search(r'^audio tracks:$', titleKey)
                if match:
                    info[title_number]['audio'] = []
                    for audioTrack in self.titles[title][titleKey].keys():
                        info[title_number]['audio'].append(audioTrack)
        return info

    # TODO: Make this function also spit out a valid path on UNIX
    @staticmethod
    def fix_path(file_path):
        """Return a path that Handbrake accepts in all input cases.

        On Windows, the drive letter MUST be followed by two backslash characters for Handbrake to work in all cases.
        If the input source is directly from a drive, omitting these characters will make Handbrake fail to find it.
        For example, using "E:" as input will not work, but using "E:\\" will work correctly.
        If the input source is a file on a drive, either one or two backslashes following the drive letter both work
        correctly, so we can always add two backslashes for correctness in all cases.
        """
        drive_letter, tail = os.path.splitdrive(file_path)
        return os.path.join(drive_letter, r'\\', tail.lstrip('\\'))  # Guarantee two backslashes after the drive letter

    def load_media(self, file_path):
        self.media_path = self.fix_path(file_path)  # Handbrake has some path oddities on Windows that must be fixed.

        cmd = [self.handbrake_path, '-i', self.media_path, '-o', 'temp.mkv', '--title', '0']
        output = subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.STDOUT)
        self.parse_scan_output(output.splitlines())

        self.is_media_set = True

    """
        This function returns the root node of a tree formed from all lines indented more than
        the first line. Each line will be a separate node in the tree.

        Each node is a dictionary and may contain further dictionaries nested arbitrarily deep.
    """
    def build_summary_tree(self, lines):
        # The tree structure is determined by indentation levels. A child node is denoted by being indented at least
        # one level deeper than its parent. Record the indent level and content of our first child node.
        root_node = {}  # If there are any children, they will be added to this dict while using their names as keys.

        if len(lines) <= 1:  # If this is the last line, we are done.
            return root_node

        # Use the first child's indentation level as a reference. All direct children must also share this level.
        root_level = len(lines[0]) - len(lines[0].lstrip(' '))  # Number of leading space characters for this node
        child_level = len(lines[1]) - len(lines[1].lstrip(' '))
        if child_level <= root_level:  # The next line might not be a child of this node if this node has no children.
            return root_node

        lines = lines[1:]  # We already made lines[0] into the root node of this sub-tree.
        for index, line in enumerate(lines):
            line_content = line.lstrip(' +')
            new_level = len(line) - len(line.lstrip(' '))
            if new_level == child_level:
                # Recursively build this child node (build the sub-tree whose root is this child node):
                root_node[line_content] = self.build_summary_tree(lines[index:])
            elif new_level < child_level:
                return root_node  # A less-indented line is not part of this tree. The tree is therefore complete.
            else:  # Lines nested even deeper than child_level are not direct children of this root node.
                pass  # Ignore these lines; they will be part of the sub-tree formed by a direct child.

        return root_node  # If all lines were processed, we are done.

    def parse_scan_output(self, scan_output):
        summary_tree = None
        for index, line in enumerate(scan_output):
            match = re.search(r'libhb: scan thread found (\d+) valid title\(s\)$', line)
            if match:
                self.title_count = int(match.group(1))
                # Handbrake outputs a tree structure starting after this line, which summarizes the scan results:
                summary_tree = scan_output[index + 1:-2]  # The last two lines are not part of the summary.

        if not summary_tree:
            raise RuntimeError('Could not parse Handbrake scan output!')

        for index, line in enumerate(summary_tree):
            indent_level = len(line) - len(line.lstrip(' '))
            if indent_level == 0:
                line_content = line.lstrip(' +')
                self.titles[line_content] = self.build_summary_tree(summary_tree[index:])

        print(repr(self.titles))

    def set_handbrake_args(self, args):
        self.handbrake_args = args

    @staticmethod
    def intersperse(iterable, delimiter):
        """Handy method to add a delimiter between every element of 'iterable'.

        Found in this StackOverflow answer: http://stackoverflow.com/a/5656097/1741965
        """
        it = iter(iterable)
        yield next(it)
        for x in it:
            yield delimiter
            yield x

    # Defaults to encoding with all audio tracks and all subtitle tracks included.
    def encode_media(self, out_path, title_number):
        title_info = self.get_title_info()
        selected_title = title_info[title_number]

        audio_tracks = [str(i) for i in range(1, len(selected_title['audio']) + 1)]
        subtitle_tracks = [str(i) for i in range(1, len(selected_title['subtitles']) + 1)]

        # String-ify the audio track numbers with commas, E.G: '1,2,3,...,n' which is how Handbrake expects them:
        audio_args = ['-a', ''.join(self.intersperse(audio_tracks, ','))]
        # For each audio track, there needs to be a corresponding encoder entry:
        # Should result in a string of the form: 'av_aac,av_aac,av_aac,av_aac,...' with the same length as audio_tracks.
        audio_args += ['-E', ''.join(self.intersperse(['av_aac'] * len(audio_tracks), ','))]
        # Do the same for the mixdown option, keeping it at 5.1 surround sound (6 channel) at 384 KB/s:
        audio_args += ['--mixdown', ''.join(self.intersperse(['6ch'] * len(audio_tracks), ','))]
        audio_args += ['-B', ''.join(self.intersperse(['384'] * len(audio_tracks), ','))]
        audio_args += ['--audio-fallback', 'ac3']

        # String-ify the subtitle track numbers, with an additional 'scan' track at the beginning:
        if subtitle_tracks:  # There may not be any subtitle tracks.
            subtitle_args = ['--subtitle', ''.join(self.intersperse(['scan'] + subtitle_tracks, ','))]
        else:
            subtitle_args = []

        cmd = [
            self.handbrake_path,
            '-i', '"' + self.media_path + '"',
            '-o', '"' + out_path + '"',
            '--title', str(title_number)
        ]
        cmd += self.handbrake_args
        cmd += audio_args
        cmd += subtitle_args
        print('ENCODE ARGS:')
        print(repr(cmd))
        cmd_string = ''.join(self.intersperse(cmd, ' '))
        print(cmd_string)

        threading.Thread(
            target=self._enqueue,
            args=(self.media_path, out_path, cmd_string, self.dvd_handler, self.encode_queue)
        ).start()

    @staticmethod
    def _enqueue(media_path, out_path, cmd_string, dvd_handler, encode_queue):
        temp_file = os.path.abspath(os.path.join('.\\', os.path.split(out_path)[1] + '.iso'))
        dvd_handler.save_to_file(media_path, temp_file)
        encode_queue.enqueue(temp_file, cmd_string)
