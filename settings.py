class HandlebarSettings:
    def __init__(self, temp_directory):
        self.temp_directory = temp_directory  # Stores the temporary ISO rips here until they can be encoded.

class HandbrakeSettings:
    def __init__(self, handbrake_path, output_format='mkv', encoder='x264', quality=24):
        self.handbrake_path = handbrake_path
        self.output_format = output_format
        self.encoder = encoder
        self.quality = quality