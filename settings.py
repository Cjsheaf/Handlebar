from configparser import ConfigParser
import os

# noinspection PyUnresolvedReferences
from PyQt5.QtWidgets import (QWidget, QDialog, QListWidget, QListWidgetItem, QStackedWidget, QHBoxLayout, QVBoxLayout,
                             QPushButton, QGroupBox, QLabel, QLineEdit, QFileDialog, QGridLayout, QSpinBox, QComboBox)


class SettingsObject(ConfigParser):
    """Stores up-to-date values for program-wide settings. Many classes and methods require an instance of this.

    Values can be safely read from any thread, but writing values and calling the save() method are not currently
    thread-safe operations. These operations should only be performed by the SettingsDialog class, anyway."""

    def __init__(self, settings_filepath, defaults={}, create_if_missing=True):
        super().__init__()
        self.filepath = settings_filepath
        self._load_settings_file(settings_filepath, create_if_missing, defaults)

    def _load_settings_file(self, filepath, create_if_missing, defaults):
        self.read_dict(defaults)

        if create_if_missing and not os.path.isfile(filepath):
            os.makedirs(os.path.split(filepath)[0], exist_ok=True)
            with open(filepath, 'w') as file:
                self.write(file)

        self.read(filepath)

    def save(self):
        with open(self.filepath, 'w') as file:
            self.write(file)

def get_handlebar_defaults():
    return {
        'handlebar': {
            # The temporary ISO rips are stored here until being encoded.
            'temp_directory': os.path.abspath('./Temp'),
        },
        'handbrake': {
            'handbrake_path': 'not_set',  # TODO: Make this value spawn a UI prompt to set handbrake_path
            'output_format': 'mkv',
            'encoder': 'x264',
            'quality': '20'
        },
        'output': {
            'media_directory': os.path.abspath('./Media')
        }
    }


class SettingsDialog(QDialog):
    def __init__(self, settings_object, parent=None):
        super().__init__(parent)

        # The settings object should not be changed directly. Use enqueue_change() to set values and call
        # commit_changes() to write them to file when the user clicks either the "Ok" or "Apply" button.
        self.settings_object = settings_object
        self.pending_changes = {}

        # A list of different settings groups, categorized by the application they apply to.
        self.category_list = QListWidget()
        self.category_list.setSpacing(3)
        self.category_list.setMaximumWidth(100)
        handlebar_category = QListWidgetItem(self.category_list)
        handlebar_category.setText('General')
        handbrake_category = QListWidgetItem(self.category_list)
        handbrake_category.setText('Encoder')
        handbrake_category = QListWidgetItem(self.category_list)
        handbrake_category.setText('Output')

        self.category_pages = QStackedWidget()
        self.category_pages.addWidget(GeneralSettingsPage(self, settings_object))
        self.category_pages.addWidget(EncoderSettingsPage(self, settings_object))
        self.category_pages.addWidget(OutputSettingsPage(self, settings_object))

        self.category_list.setCurrentRow(0)
        self.category_list.currentItemChanged.connect(self.change_category)

        category_layout = QHBoxLayout()
        category_layout.addWidget(self.category_list)
        category_layout.addWidget(self.category_pages)

        ok_button = QPushButton('Ok')
        cancel_button = QPushButton('Cancel')
        self.apply_button = QPushButton('Apply')
        self.apply_button.setEnabled(False)

        ok_button.clicked.connect(self.commit_changes_and_close)
        cancel_button.clicked.connect(self.close)
        self.apply_button.clicked.connect(self.commit_changes)

        button_bar_layout = QHBoxLayout()
        button_bar_layout.addStretch(1)
        button_bar_layout.addWidget(ok_button)
        button_bar_layout.addWidget(cancel_button)
        button_bar_layout.addWidget(self.apply_button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(category_layout)
        main_layout.addLayout(button_bar_layout)
        self.setLayout(main_layout)

        self.setWindowTitle('Configure Settings')
        self.resize(600, 300)

    def change_category(self, current, previous):
        if not current:
            current = previous

        self.category_pages.setCurrentIndex(self.category_list.row(current))

    def commit_changes_and_close(self):
        """Convenience function that calls commit_changes and then closes the dialog. Used by the "OK" button"""
        self.commit_changes()
        self.close()

    def commit_changes(self):
        if len(self.pending_changes) > 0:
            print('Settings committed to file.')
            self.settings_object.read_dict(self.pending_changes)
            self.settings_object.save()
            self.pending_changes = {}
            self.apply_button.setEnabled(False)  # There are no longer any pending changes.

    def enqueue_change(self, category, name, value):
        print('Setting "{}" changed to {}.'.format(name, value))
        if category in self.pending_changes.keys():  # If a nested dict already exists for this category:
            self.pending_changes[category][name] = value  # Add this pair to the nested dict.
        else:
            self.pending_changes[category] = {name: value}  # Create the nested dict with this pair.
        self.apply_button.setEnabled(True)  # There are now pending changes that can be applied.


class GeneralSettingsPage(QWidget):
    def __init__(self, parent, settings_object):
        super().__init__()
        self.parent = parent
        self.settings_object = settings_object

        temp_group = QGroupBox('Temporary Files')
        temp_group_layout = QHBoxLayout()
        temp_path_label = QLabel('Location:')
        self.temp_path_edit = QLineEdit(self.settings_object['handlebar']['temp_directory'])
        temp_path_browse_button = QPushButton('Browse')

        temp_path_browse_button.clicked.connect(self.browse_temp_directory)
        self.temp_path_edit.textEdited.connect(self.set_temp_directory)

        temp_group_layout.addWidget(temp_path_label)
        temp_group_layout.addWidget(self.temp_path_edit)
        temp_group_layout.addWidget(temp_path_browse_button)
        temp_group.setLayout(temp_group_layout)

        main_layout = QVBoxLayout()
        main_layout.addWidget(temp_group)
        main_layout.addStretch(1)
        self.setLayout(main_layout)

    def browse_temp_directory(self):
        filepath = QFileDialog.getExistingDirectory()
        if filepath:
            self.temp_path_edit.setText(filepath)
            self.set_temp_directory(filepath)

    def set_temp_directory(self, filepath):
        # TODO: Sanity-check filepath and warn the user if it is not valid.
        self.parent.enqueue_change('handlebar', 'temp_directory', filepath)


class EncoderSettingsPage(QWidget):
    FORMAT_VALUES = ['mkv', 'mp4']
    ENCODER_VALUES = ['x264', 'x265']

    def __init__(self, parent, settings_object):
        super().__init__()
        self.parent = parent
        self.settings_object = settings_object

        handbrake_group = self.create_handbrake_group()

        main_layout = QVBoxLayout()
        main_layout.addWidget(handbrake_group)
        main_layout.addStretch(1)
        self.setLayout(main_layout)

    def create_handbrake_group(self):
        handbrake_group = QGroupBox('Handbrake Settings')
        handbrake_layout = QGridLayout()

        handbrake_path_label = QLabel('Executable:')
        self.handbrake_path_edit = QLineEdit(self.settings_object['handbrake']['handbrake_path'])
        handbrake_path_browse_button = QPushButton('Browse')
        handbrake_path_browse_button.clicked.connect(self.browse_handbrake_path)
        self.handbrake_path_edit.textEdited.connect(self.set_handbrake_path)

        handbrake_format_label = QLabel('Format:')
        handbrake_format_dropdown = QComboBox()
        handbrake_format_dropdown.addItems(self.FORMAT_VALUES)
        current_format = self.settings_object['handbrake']['output_format']
        if current_format in self.FORMAT_VALUES:
            handbrake_format_dropdown.setCurrentIndex(handbrake_format_dropdown.findText(current_format))
        else:
            raise SyntaxError('Format "{}" found in settings file is not a supported output format!')
        handbrake_format_dropdown.currentTextChanged.connect(
            lambda text: self.parent.enqueue_change('handbrake', 'output_format', text)
        )

        handbrake_encoder_label = QLabel('Encoder:')
        handbrake_encoder_dropdown = QComboBox()
        handbrake_encoder_dropdown.addItems(self.ENCODER_VALUES)
        current_encoder = self.settings_object['handbrake']['encoder']
        if current_encoder in self.ENCODER_VALUES:
            handbrake_encoder_dropdown.setCurrentIndex(handbrake_encoder_dropdown.findText(current_encoder))
        else:
            raise SyntaxError('Encoder "{}" found in settings file is not a supported encoder!')
        handbrake_encoder_dropdown.currentTextChanged.connect(
            lambda text: self.parent.enqueue_change('handbrake', 'encoder', text)
        )

        handbrake_quality_label = QLabel('Quality:')
        handbrake_quality_spinner = QSpinBox()
        handbrake_quality_spinner.setValue(int(self.settings_object['handbrake']['quality']))
        handbrake_quality_spinner.setMinimum(1)
        handbrake_quality_spinner.setMaximum(30)
        handbrake_quality_spinner.valueChanged.connect(
            lambda value: self.parent.enqueue_change('handbrake', 'quality', value)
        )

        handbrake_layout.addWidget(handbrake_path_label, 0, 0)
        handbrake_layout.addWidget(self.handbrake_path_edit, 0, 1)
        handbrake_layout.addWidget(handbrake_path_browse_button, 0, 2)
        handbrake_layout.addWidget(handbrake_format_label, 1, 0)
        handbrake_layout.addWidget(handbrake_format_dropdown, 1, 1)
        handbrake_layout.addWidget(handbrake_encoder_label, 2, 0)
        handbrake_layout.addWidget(handbrake_encoder_dropdown, 2, 1)
        handbrake_layout.addWidget(handbrake_quality_label, 3, 0)
        handbrake_layout.addWidget(handbrake_quality_spinner, 3, 1)
        handbrake_group.setLayout(handbrake_layout)

        return handbrake_group

    def browse_handbrake_path(self):
        filepath = QFileDialog.getOpenFileName(filter='HandBrakeCLI.exe')[0]
        if filepath:
            self.handbrake_path_edit.setText(filepath)
            self.set_handbrake_path(filepath)

    def set_handbrake_path(self, filepath):
        # TODO: Sanity-check filepath and warn the user if it is not valid.
        self.parent.enqueue_change('handbrake', 'handbrake_path', filepath)

class OutputSettingsPage(QWidget):
    def __init__(self, parent, settings_object):
        super().__init__()
        self.parent = parent
        self.settings_object = settings_object

        media_group = QGroupBox('Media Files')
        media_group_layout = QHBoxLayout()
        media_path_label = QLabel('Media Folder:')
        self.media_path_edit = QLineEdit(self.settings_object['output']['media_directory'])
        media_path_browse_button = QPushButton('Browse')

        media_path_browse_button.clicked.connect(self.browse_media_directory)
        self.media_path_edit.textEdited.connect(self.set_media_directory)

        media_group_layout.addWidget(media_path_label)
        media_group_layout.addWidget(self.media_path_edit)
        media_group_layout.addWidget(media_path_browse_button)
        media_group.setLayout(media_group_layout)

        main_layout = QVBoxLayout()
        main_layout.addWidget(media_group)
        main_layout.addStretch(1)
        self.setLayout(main_layout)

    def browse_media_directory(self):
        filepath = QFileDialog.getExistingDirectory()
        if filepath:
            self.media_path_edit.setText(filepath)
            self.set_media_directory(filepath)

    def set_media_directory(self, filepath):
        # TODO: Sanity-check filepath and warn the user if it is not valid.
        self.parent.enqueue_change('output', 'media_directory', filepath)
