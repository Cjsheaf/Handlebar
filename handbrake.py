import os.path
import re
import subprocess
import threading


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


class TitleScan:
    def __init__(self, handbrake_path, media_filepath):
        self.handbrake_path = handbrake_path
        # self.titles is basically a dict used as a sparse array. Title numbers are keys with Title objects as values.
        # Titles reported by Handbrake may start at any title number and are not guaranteed to be contiguous.
        self.titles = self.scan_titles(media_filepath)

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

    def scan_titles(self, media_filepath):
        fixed_path = self.fix_path(media_filepath) # Handbrake has some path oddities on Windows that must be fixed.
        cmd = [self.handbrake_path, '-i', fixed_path, '-o', 'temp.mkv', '--title', '0']
        scan_output = subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.STDOUT).splitlines()

        summary_tree = None
        for index, line in enumerate(scan_output):
            match = re.search(r'libhb: scan thread found (\d+) valid title\(s\)$', line)
            if match:
                # Handbrake outputs a tree structure starting after this line, which summarizes the scan results:
                summary_tree = scan_output[index + 1:-2]  # The last two lines are not part of the summary.

        if not summary_tree:
            raise RuntimeError('Could not parse Handbrake scan output!')

        # The tree structure is defined by indentation levels, where more-indented lines are considered child nodes of
        # less-indented lines. Parse this tree into an intermediate nested dictionary structure for further processing.
        title_tree = {}
        for index, line in enumerate(summary_tree):
            indent_level = len(line) - len(line.lstrip(' '))
            if indent_level == 0:  # Title entries are at level 0 and form their own sub-tree.
                line_content = line.lstrip(' +')
                title_tree[line_content] = self.build_indentation_tree(summary_tree[index:])

        # Parse each title in title_tree and instantiate a Title object for it. Store these Titles by title number.
        titles = {}
        for title_name, sub_tree in title_tree.items():
            title_number = int(re.search(r'^title (\d+):$', title_name).group(1))
            # The sub_tree contains all of the information for this title, but still needs to be parsed further.
            titles[title_number] = self.build_title(sub_tree)

        return titles

    """This function returns the root node of a tree formed from all lines indented more than
    the first line. Each line will be a separate node in the tree.

    Each node is a dictionary and may contain further dictionaries nested arbitrarily deep.
    """
    def build_indentation_tree(self, lines):
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
                root_node[line_content] = self.build_indentation_tree(lines[index:])
            elif new_level < child_level:
                return root_node  # A less-indented line is not part of this tree. The tree is therefore complete.
            else:  # Lines nested even deeper than child_level are not direct children of this root node.
                pass  # Ignore these lines; they will be part of the sub-tree formed by a direct child.

        return root_node  # If all lines were processed, we are done.

    def build_title(self, title_root):
        duration = None
        resolution = None
        framerate = None
        subtitle_tracks = []
        audio_tracks = []

        for title_key in title_root.keys():
            match = re.search(r'^duration: (\d+):(\d+):(\d+)$', title_key)
            if match:
                hours = int(match.group(1))
                minutes = (hours * 60) + int(match.group(2))
                seconds = (minutes * 60) + int(match.group(3))
                duration = seconds

            match = re.search(r'^subtitle tracks:$', title_key)
            if match:
                for subtitle_string in title_root[title_key].keys():
                    # Each subtitle string contains the subtitle track number, language name, iso639-2 language code,
                    # text type, and subtitle format, in that order. Only the language code is currently used.
                    # Example: "1, English (Closed Caption) (iso639-2: eng) (Bitmap)(VOBSUB)"
                    subtitle_match = re.search(
                        r'^(\d+), (.+?) \(iso639-2: (.+?)\) \((.+?)\)\((.+?)\)$',
                        subtitle_string
                    )
                    if subtitle_match:
                        subtitle_tracks.append(SubtitleTrack(
                            track_number=subtitle_match.group(1),
                            language=subtitle_match.group(3)
                        ))
                    else:
                        raise RuntimeError('Unable to parse subtitle string: "{}"'.format(subtitle_string))


            match = re.search(r'^audio tracks:$', title_key)
            if match:
                for audio_string in title_root[title_key].keys():
                    # Each audio string contains the audio track number, language name, channel configuration,
                    # iso639-2 language code, hertz, and bitrate, in that order.
                    audio_match = re.search(
                        r'^(\d+), (.+?) \((.+?)\) \((.+?)\) \(iso639-2: (.+?)\), (\d+)Hz, (\d+)bps$',
                        audio_string
                    )
                    if audio_match:
                        audio_tracks.append(AudioTrack(
                            track_number=audio_match.group(1),
                            encoding=audio_match.group(3),
                            channels=audio_match.group(4),
                            language=audio_match.group(5),
                            hertz=audio_match.group(6),
                            bitrate=audio_match.group(7)
                        ))
                    else:
                        raise RuntimeError('Unable to parse audio string: "{}"'.format(audio_string))

        subtitle_tracks.sort()
        audio_tracks.sort()
        return Title(duration, resolution, framerate, subtitle_tracks, audio_tracks)


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
        return self.titles

    def load_media(self, file_path):
        self.titles = TitleScan(self.handbrake_path, file_path).titles
        self.is_media_set = True

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

        # Get a list of track numbers for both the audio and subtitle tracks:
        audio_tracks = [str(track.track_number) for track in selected_title.audio_tracks]
        subtitle_tracks = [str(track.track_number) for track in selected_title.subtitle_tracks]

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

