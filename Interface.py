import re
import os.path
import datetime
import queue
import threading

# noinspection PyUnresolvedReferences
from PyQt5.QtCore import (Qt, QTimer, pyqtSignal)
# noinspection PyUnresolvedReferences
from PyQt5.QtWidgets import (QMainWindow, QWidget, QPushButton, QFileDialog, QMenuBar, QMenu, QVBoxLayout,
                             QHBoxLayout, QFrame, QLabel, QLineEdit, QToolButton, QCheckBox, QComboBox,
                             QSpacerItem, QMessageBox, QDialog, QDialogButtonBox, QTreeView, QProgressBar,
                             QListWidget, QListWidgetItem, QApplication, QAction)
# noinspection PyUnresolvedReferences
from PyQt5.QtGui import (QIntValidator, QStandardItemModel)
from database import EncodeStatus
from settings import SettingsDialog
from media_factory import MediaFactory


class MovieEntry(QWidget):
    def __init__(self):
        super(MovieEntry, self).__init__()
        self.title_strings = None

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.file_label = QLabel('Disk_Filename')
        self.year_text_box = QLineEdit(placeholderText='[Year]')
        self.movie_name_text_box = QLineEdit(placeholderText='[Movie Name]')
        self.title_dropdown = QComboBox()

        self.doLayout()

    def doLayout(self):
        # Add the top-most horizontal group:
        top_group = QHBoxLayout()
        self.main_layout.addLayout(top_group)

        self.file_label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.file_label.setMinimumWidth(200)
        top_group.addWidget(self.file_label)

        top_group.addStretch(1)
        year_label = QLabel('Year:')
        top_group.addWidget(year_label)
        self.year_text_box.setMaximumWidth(37)
        year_validator = QIntValidator(1000, 9999)
        self.year_text_box.setValidator(year_validator)
        top_group.addWidget(self.year_text_box)

        # Add the bottom-most horizontal group:
        bottom_group = QHBoxLayout()
        self.main_layout.addLayout(bottom_group)

        self.movie_name_text_box.setMinimumWidth(200)
        bottom_group.addWidget(self.movie_name_text_box)

        bottom_group.addStretch(1)
        self.title_dropdown.setMinimumWidth(110)
        bottom_group.addWidget(self.title_dropdown)

    def set_title_strings(self, title_strings):
        self.title_strings = title_strings
        self.title_dropdown.clear()
        self.title_dropdown.addItems(title_strings)


class SeriesEntry(QWidget):
    def __init__(self):
        super(SeriesEntry, self).__init__()
        self.title_strings = None
        self.first_episode = None
        self.last_episode = None

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.file_label = QLabel('Disk_Filename')
        self.season_text_box = QLineEdit(placeholderText='#')
        self.year_text_box = QLineEdit(placeholderText='[Year]')
        self.movieNameTextBox = QLineEdit(placeholderText='[Series Name]')
        self.episodeStartTextBox = QLineEdit(placeholderText='#', text='1')
        self.episodeEndTextBox = QLineEdit(placeholderText='#', text='3')
        self.selectorRows = []
        self.episodeSelector = QVBoxLayout()

        self.doLayout()

    def doLayout(self):
        # Add the top-most horizontal group:
        top_group = QHBoxLayout()
        self.main_layout.addLayout(top_group)

        self.file_label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.file_label.setMinimumWidth(200)
        top_group.addWidget(self.file_label)

        top_group.addStretch(1)
        seasonlabel = QLabel('Season:')
        top_group.addWidget(seasonlabel)
        self.season_text_box.setMaximumWidth(22)
        season_validator = QIntValidator(1, 99)
        self.season_text_box.setValidator(season_validator)
        self.season_text_box.setMaxLength(2)
        top_group.addWidget(self.season_text_box)

        year_label = QLabel('Year:')
        top_group.addWidget(year_label)
        self.year_text_box.setMaximumWidth(37)
        year_validator = QIntValidator(1900, 2100)
        self.year_text_box.setValidator(year_validator)
        self.year_text_box.setMaxLength(4)
        top_group.addWidget(self.year_text_box)

        # Add the bottom-most horizontal group:
        bottom_group = QHBoxLayout()
        self.main_layout.addLayout(bottom_group)

        self.movieNameTextBox.setMinimumWidth(200)
        bottom_group.addWidget(self.movieNameTextBox)

        bottom_group.addStretch(1)
        episode_number_label = QLabel('Episodes:')
        bottom_group.addWidget(episode_number_label)

        episode_validator = QIntValidator(1, 99)
        self.episodeStartTextBox.setMaximumWidth(30)
        self.episodeStartTextBox.setValidator(episode_validator)
        self.episodeStartTextBox.setMaxLength(2)
        bottom_group.addWidget(self.episodeStartTextBox)
        episode_separator_label = QLabel('to')
        bottom_group.addWidget(episode_separator_label)
        self.episodeEndTextBox.setMaximumWidth(30)
        self.episodeEndTextBox.setValidator(episode_validator)
        self.episodeEndTextBox.setMaxLength(2)
        bottom_group.addWidget(self.episodeEndTextBox)

        self.episodeStartTextBox.editingFinished.connect(self.populateEpisodeSelector)
        self.episodeEndTextBox.editingFinished.connect(self.populateEpisodeSelector)

        self.main_layout.addLayout(self.episodeSelector)
        self.populateEpisodeSelector()

    def populateEpisodeSelector(self):
        num_episodes = self.getNumEpisodes()

        # Add extra rows if necessary:
        if len(self.selectorRows) < num_episodes:
            for i in range(0, num_episodes - len(self.selectorRows)):
                row_container = QWidget()
                episode_layout = QHBoxLayout()
                row_container.setLayout(episode_layout)
                episode_label = QLabel()
                episode_layout.addWidget(episode_label)

                title_dropdown = QComboBox()
                title_dropdown.setMinimumWidth(110)
                if self.title_strings:
                    title_dropdown.addItems(self.title_strings)
                episode_layout.addWidget(title_dropdown)
                episode_layout.addStretch(1)
                self.episodeSelector.addWidget(row_container)
                self.selectorRows.append((episode_label, title_dropdown))

        # Set the correct episode numbers in the labels:
        for i in range(self.first_episode, self.last_episode + 1):
            self.selectorRows[i - self.first_episode][0].setText('Episode ' + str(i))

        # First, show all rows (this resets any previously hidden rows):
        for i, j in self.selectorRows:
            i.show()
            j.show()

        # Then, hide any extra rows: (Trying to delete them seems to cause crashes, and is mostly unnecessary)
        if len(self.selectorRows) > num_episodes:
            extra_count = len(self.selectorRows) - num_episodes
            for i in range(len(self.selectorRows) - extra_count, len(self.selectorRows)):
                self.selectorRows[i][0].hide()
                self.selectorRows[i][1].hide()

    def getNumEpisodes(self):
        # It is not an error if either of the episode number boxes is empty. There is simply nothing to display yet.
        if len(self.episodeStartTextBox.text()) == 0 or len(self.episodeEndTextBox.text()) == 0:
            return 0

        if self.episodeStartTextBox.hasAcceptableInput() is False:
            QMessageBox(QMessageBox.Warning, 'Invalid Input',
                        'The first episode number must be between 1 and 99!').exec()
            return 0
        if self.episodeEndTextBox.hasAcceptableInput() is False:
            QMessageBox(QMessageBox.Warning, 'Invalid Input',
                        'The second episode number must be between 1 and 99!').exec()
            return 0

        self.first_episode = int(self.episodeStartTextBox.text())
        self.last_episode = int(self.episodeEndTextBox.text())
        if self.first_episode > self.last_episode:
            return 0

        return self.last_episode - self.first_episode + 1

    def setTitleStrings(self, title_strings):
        self.title_strings = title_strings
        for label, dropdown in self.selectorRows:
            dropdown.clear()
            dropdown.addItems(title_strings)


class EntryFrame(QFrame):
    # TODO: Use signals to directly alter the data in self.media as widgets are edited.
    # TODO: Sanity check user input so that self.media is never in an invalid state.
    def __init__(self):
        super(EntryFrame, self).__init__()
        self.media = None
        self.mode = 'Movie'  # Shows which type of entry mode is active. Can equal either 'Movie' or 'Series'
        self.selected_movie = None

        self.mainLayout = QHBoxLayout()
        self.setLayout(self.mainLayout)

        self.diskButton = QToolButton()
        self.fileButton = QToolButton()
        self.seriesCheckbox = QCheckBox('Series')
        self.movieEntry = MovieEntry()
        self.seriesEntry = SeriesEntry()

        self.doLayout()

    def doLayout(self):
        # Add the "Select Disk" button in a column on the left:
        left_col = QVBoxLayout()
        top_buttons = QHBoxLayout()

        top_buttons.addWidget(self.diskButton)
        self.diskButton.clicked.connect(self.selectMediaDrive)
        top_buttons.addWidget(self.fileButton)
        self.fileButton.clicked.connect(self.selectMediaFile)
        left_col.addLayout(top_buttons)

        left_col.addWidget(self.seriesCheckbox)
        self.seriesCheckbox.stateChanged.connect(self.switchEntry)
        left_col.addStretch(1)

        self.mainLayout.addLayout(left_col)

        # The space to the right will contain either a MovieEntry or a SeriesEntry. Default is MovieEntry:
        right_col = QVBoxLayout()
        right_col.addWidget(self.movieEntry)
        right_col.addWidget(self.seriesEntry)
        self.seriesEntry.hide()
        right_col.addStretch(1)
        self.mainLayout.addLayout(right_col)

    def switchEntry(self, checkbox_state):
        if checkbox_state == 0:  # Unchecked
            self.seriesEntry.hide()
            self.movieEntry.show()
            if self.media:
                self.media.media_type = 'movie'
        else:  # Checked
            self.movieEntry.hide()
            self.seriesEntry.show()
            if self.media:
                self.media.media_type = 'series'

    def selectMediaFile(self):
        media_filepath = QFileDialog.getOpenFileName(filter="*.iso")[0]
        if media_filepath:
            self.media = MediaFactory.read_media_from_file(media_filepath, MainWindow.handlebar.program_settings)
            if self.media:
                self.populateData()

    def selectMediaDrive(self):
        media_drives = MainWindow.handlebar.media_factory.read_media_from_drives()
        selector = DriveSelectorDialog(media_drives, self)
        if selector.exec() == QDialog.Accepted:
            self.media = selector.getSelectedDrive()
            self.populateData()
        else:
            self.media = None

    def populateData(self):
        self.movieEntry.file_label.setText(os.path.join(self.media.image_path, self.media.file_name))
        self.movieEntry.movie_name_text_box.setText(self.media.media_name)
        self.seriesEntry.file_label.setText(os.path.join(self.media.image_path, self.media.file_name))
        self.seriesEntry.movieNameTextBox.setText(self.media.media_name)

        title_strings = []
        for title_number, title in self.media.titles.items():
            title_strings.append('Title {number} - {duration}'.format(
                number=title_number, duration=str(datetime.timedelta(seconds=title.duration))
            ))
        self.movieEntry.set_title_strings(title_strings)
        self.seriesEntry.setTitleStrings(title_strings)

    def submitEntry(self):
        if self.mode == 'Movie':
            # TODO: Sanity check all the fields for valid data. Preferably using QT methods.
            match = re.search(r'^Title (\d+)', self.movieEntry.title_dropdown.currentText())
            title_number = int(match.group(1))

            output_filename = '{name} ({year}).mkv'.format(
                name=self.movieEntry.movie_name_text_box.text(), year=self.movieEntry.year_text_box.text()
            )
            media_dir = MainWindow.handlebar.program_settings['output']['media_directory']
            filepath = os.path.join(media_dir, 'Movies\\', output_filename)
            print(filepath)

            # Enqueue a rip job if the source_type is from a drive, otherwise enqueue an encode job.
            MainWindow.handlebar.work_queue.enqueue(self.media, filepath, title_number, self.media.source_type == 'drive')
        elif self.mode == 'Series':
            pass


class DriveSelectorDialog(QDialog):
    def __init__(self, drives, parent=None):
        super(DriveSelectorDialog, self).__init__(parent)
        self.media_drives = drives
        self.drive_mapping = {}  # Used to find the corresponding media_drive entry from a given drive letter.
        self.selectedDrive = None

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.listModel = QStandardItemModel(0, 2)
        self.listView = QTreeView()

        self.doLayout()
        self.setWindowTitle('Select a DVD Drive')

    def doLayout(self):
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # noinspection PyPep8Naming
        LETTER, MEDIA = range(2)
        self.listModel.setHeaderData(LETTER, Qt.Horizontal, 'Drive Letter')
        self.listModel.setHeaderData(MEDIA, Qt.Horizontal, 'Media Name')
        for media in self.media_drives:
            self.listModel.insertRow(0)
            self.listModel.setData(self.listModel.index(0, LETTER), media.image_path)
            self.listModel.setData(self.listModel.index(0, MEDIA), media.file_name)
            self.drive_mapping[media.image_path] = media  # Map the drive letter to its corresponding media object

        self.listView.setModel(self.listModel)
        self.listView.selectionModel().currentRowChanged.connect(self.selectionChanged)

        self.main_layout.addWidget(self.listView)
        self.main_layout.addWidget(button_box)

    def selectionChanged(self, current, previous):
        letter_col = self.listModel.index(current.row(), 0)
        self.selectedDrive = self.drive_mapping[self.listModel.data(letter_col)]

    def getSelectedDrive(self):
        return self.selectedDrive


class EncodeDisplay(QFrame):
    """Displays the encode status, or displays a progress bar if the encode is in progress."""
    def __init__(self, media_name, encode_status):
        super(EncodeDisplay, self).__init__()
        if not isinstance(encode_status, EncodeStatus):
            raise RuntimeError('Argument encode_status must be a value from Enum class database.EncodeStatus!')

        self.media_name = media_name
        self.encode_status = None

        self.main_layout = QHBoxLayout()
        self.setLayout(self.main_layout)

        self.name_label = QLabel(self.media_name)
        self.progress_bar = QProgressBar()
        self.status_label = QLabel()

        self.doLayout()
        self.set_status(encode_status)

    def doLayout(self):
        # The progress bar will show whole percentages:
        self.progress_bar.minimum = 0
        self.progress_bar.maximum = 100
        self.progress_bar.hide()  # Do not show the progress bar unless an encode is in progress.

        self.main_layout.addWidget(self.name_label)
        self.main_layout.addWidget(self.progress_bar)
        self.main_layout.addWidget(self.status_label)

    def set_status(self, encode_status):
        self.encode_status = encode_status
        self.status_label.setText(self.encode_status.name)

        # Only show a progress bar if a rip or encode is currently in progress.
        if self.encode_status is EncodeStatus.Ripping or self.encode_status is EncodeStatus.Encoding:
            self.progress_bar.show()
        else:
            self.progress_bar.hide()

    def set_progress(self, percent_complete):
        self.progress_bar.setValue(percent_complete)


class DisplayList(QFrame):
    init_display = pyqtSignal(str, object, object)

    def __init__(self):
        super(DisplayList, self).__init__()
        self.ui_thread = threading.current_thread()

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)
        self.displays = QListWidget()
        self.display_mapping = {}  # Used to retrieve a display given the media_name it was created with.
        self.main_layout.addWidget(self.displays)
        self.init_display.connect(self._initDisplay)

    def getDisplay(self, media_name):
        if media_name in self.display_mapping.keys():
            return self.display_mapping[media_name]
        else:
            return None

    def createDisplay(self, media_name, encode_status):
        ready_event = threading.Event()
        ready_event.clear()

        # The display can ONLY be created on the UI thread. By using QT signals,
        # we can have the UI thread run _initDisplay(). Use ready_event to
        # wait until the UI thread signals that the display has been created.
        self.init_display.emit(media_name, encode_status, ready_event)
        if threading.current_thread() == self.ui_thread:
            QApplication.processEvents()  # Force the event manager to process the init_display we signal just sent.
        else:
            ready_event.wait()
        return self.display_mapping[media_name]

    def _initDisplay(self, media_name, encode_status, ready_event):
        display = EncodeDisplay(media_name, encode_status)
        list_item = QListWidgetItem()
        list_item.setSizeHint(display.sizeHint())
        self.displays.addItem(list_item)
        self.displays.setItemWidget(list_item, display)
        self.display_mapping[media_name] = display
        ready_event.set()  # Allow the consumer thread to resume.


class Interface(QWidget):
    def __init__(self):
        super(Interface, self).__init__()
        self.mainLayout = QHBoxLayout()
        self.setLayout(self.mainLayout)

        self.entryWidget = EntryFrame()
        self.queueDisplay = DisplayList()

        self.doLayout()

    def doLayout(self):
        entry_layout = QVBoxLayout()
        file_button_layout = QHBoxLayout()

        disk_button = QPushButton('Load From Disk')
        disk_button.clicked.connect(self.entryWidget.selectMediaDrive)
        file_button_layout.addWidget(disk_button)

        file_button = QPushButton('Load From File')
        file_button.clicked.connect(self.entryWidget.selectMediaFile)
        file_button_layout.addWidget(file_button)

        queue_button = QPushButton('Add To Queue')
        queue_button.clicked.connect(self.addToQueue)
        file_button_layout.addWidget(queue_button)

        entry_layout.addWidget(self.entryWidget)
        entry_layout.addLayout(file_button_layout)
        self.mainLayout.addLayout(entry_layout)

        self.mainLayout.addWidget(self.queueDisplay)

    def addToQueue(self):
        self.entryWidget.submitEntry()


class MainWindow(QMainWindow):
    handlebar = None  # Static class reference to the application

    def __init__(self, handlebar):
        super(MainWindow, self).__init__()
        MainWindow.handlebar = handlebar

        self.setWindowTitle('Handlebar')
        self.menu_bar = QMenuBar()
        self.setMenuBar(self.menu_bar)
        self.setupMenuBar()

        self.interface = Interface()
        self.setCentralWidget(self.interface)

    def setupMenuBar(self):
        file_menu = self.menu_bar.addMenu('File')
        settings_action = QAction('Settings', self, statusTip='Open a window to access program settings.',
                                  triggered=self.openSettingsMenu)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction('Exit', self, statusTip='Close the application.', triggered=self.close)
        file_menu.addAction(exit_action)

    def openSettingsMenu(self):
        settings_dialog = SettingsDialog(self.handlebar.program_settings, self).exec()