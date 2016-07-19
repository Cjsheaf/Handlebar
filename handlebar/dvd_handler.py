import re
from platform import system

import dvdvideo_backup_image
from dvdvideo.utils import ProgressStream

class WinDVDHandler:
    def __init__(self, initial_scan=False):
        import wmi
        self.win = wmi.WMI(find_classes=False)
        self.drives = {}
        if initial_scan is True:
            self.scan_drives()

    @staticmethod
    def save_to_file(media, output_filepath, progress_callback=None):
        # The save function writes a progress bar to a text stream. We want to parse that text in real time in order
        # to determine what percentage is complete. The ProgressWrapper class does exactly this by acting like a stream.
        stream = ProgressWrapper(progress_callback)

        print('Saving to file: "{}"'.format(output_filepath))
        if media.source_type == 'drive':
            drive = media.source_path.rstrip('\\')
            dvdvideo_backup_image.main(ProgressStream(stream), r'\\.\{}'.format(drive), output_filepath)
        else:
            raise RuntimeError('Media source is not from a drive and does not need to be saved to a file!')

    def scan_drives(self):
        for cdrom in self.win.Win32_CDROMDrive(['Drive', 'Size', 'VolumeName', 'MediaLoaded']):
            self.drives[cdrom.Drive] = cdrom  # Store the WMI CDROM object using its drive letter. (Example: 'F:')

    def get_media_drives(self):
        return [drive for letter, drive in self.drives.items() if drive.MediaLoaded]


class LinuxDVDHandler:
    pass

if system() == 'Windows':
    DVDHandler = WinDVDHandler
elif system() == "Linux":
    DVDHandler = LinuxDVDHandler
else:
    raise ImportError('This module does not support the current os: "{}"'.format(system()))


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