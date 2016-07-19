import os.path
import re
import subprocess

import Handlebar.util as util
from Handlebar.media_factory import SubtitleTrack, AudioTrack, Title


class TitleScan:
    def __init__(self, handbrake_path, media_filepath):
        if handbrake_path == 'not_set':
            raise RuntimeError('The handbrake executable path has not been set!')
        self.handbrake_path = handbrake_path
        # self.titles is basically a dict used as a sparse array. Title numbers are keys with Title objects as values.
        # Titles reported by Handbrake may start at any title number and are not guaranteed to be contiguous.
        self.titles = self.scan_titles(media_filepath)

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
        if drive_letter:
            return os.path.join(drive_letter, r'\\', tail.lstrip('\\'))  # Guarantee two backslashes after the drive letter
        else:
            return file_path

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
    @staticmethod
    def get_default_args():
        args = [
            '--loose-anamorphic',
            '--modulus', '2',
            '--vfr'  # Variable frame rate
        ]
        return args

    @staticmethod
    def build_handbrake_cmd(program_settings, media, out_path, title_number):
        selected_title = media.titles[title_number]

        # Get a list of track numbers for both the audio and subtitle tracks:
        audio_tracks = [str(track.track_number) for track in selected_title.audio_tracks]
        subtitle_tracks = [str(track.track_number) for track in selected_title.subtitle_tracks]

        # String-ify the audio track numbers with commas, E.G: '1,2,3,...,n' which is how Handbrake expects them:
        audio_args = ['-a', ''.join(util.intersperse(audio_tracks, ','))]
        # For each audio track, there needs to be a corresponding encoder entry:
        # Should result in a string of the form: 'av_aac,av_aac,av_aac,av_aac,...' with the same length as audio_tracks.
        audio_args += ['-E', ''.join(util.intersperse(['av_aac'] * len(audio_tracks), ','))]
        # Do the same for the mixdown option, keeping it at 5.1 surround sound (6 channel) at 384 KB/s:
        audio_args += ['--mixdown', ''.join(util.intersperse(['6ch'] * len(audio_tracks), ','))]
        audio_args += ['-B', ''.join(util.intersperse(['384'] * len(audio_tracks), ','))]
        audio_args += ['--audio-fallback', 'ac3']

        # String-ify the subtitle track numbers, with an additional 'scan' track at the beginning:
        if subtitle_tracks:  # There might not be any subtitle tracks.
            subtitle_args = ['--subtitle', ''.join(util.intersperse(['scan'] + subtitle_tracks, ','))]
        else:
            subtitle_args = []

        cmd = [
            program_settings['handbrake']['handbrake_path'],
            '-i', '"' + media.source_path + '"',
            '-o', '"' + out_path + '"',
            '--title', str(title_number)
        ]
        cmd += HandbrakeHandler.get_default_args()
        cmd += ['-f', program_settings['handbrake']['output_format']]
        cmd += ['-q', program_settings['handbrake']['quality']]
        cmd += ['-e', program_settings['handbrake']['encoder']]
        cmd += audio_args
        cmd += subtitle_args
        print('ENCODE ARGS:')
        print(repr(cmd))
        cmd_string = ''.join(util.intersperse(cmd, ' '))
        return cmd_string
