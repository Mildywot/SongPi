# SongPi - Automatic Song Recognition & Visualiser

SongPi is a Python application that listens to audio playing around your computer (or through a specified microphone), automatically identifies the song, and displays its title, artist, and cover art in a sleek, dynamic interface. It uses Shazamio for the core recognition functionality and Tkinter for the graphical user interface.

## How It Works

1.  **Audio Capture:** SongPi records a short audio snippet (typically a few seconds) from your computer's selected audio input device. The recording parameters like duration, sample rate, and device can be configured.
2.  **Recognition:** The captured audio is sent to Shazam (via the Shazamio library) to identify the song.
3.  **Information Retrieval:** If a match is found, the application fetches metadata including the song's title, artist, and URLs for the cover art.
4.  **Dynamic Display:**
    * The cover art is displayed prominently, with a larger, blurred version of it serving as the window background.
    * The song title and artist are overlaid on the display.
    * Text colour (black or white) is dynamically chosen based on the background's brightness to ensure readability.
5.  **Continuous Operation:** The app periodically repeats this process, automatically updating the display if a new song is detected.

Examples:
![Landscape view 1](readme_images/Landscape_bright.png)
![Landscape view 2](readme_images/Landscape_dark.png)
![Portrait view](readme_images/Portrait.png)

## Key Features

* **Automatic Song Identification:** "Always-on" recognition that listens for music and updates the display in real-time.
* **Immersive Visuals:**
    * Fullscreen (or windowed) display focusing on the current song's album art.
    * Blurred album art background for an aesthetic look.
    * Adaptive text colouring ensures song title and artist are always clear.
    * Font sizes adjust dynamically for optimal viewing based on window size.
* **Song History:**
    * Keeps track of recently identified songs and displays them in a history panel.
    * **Smart Layout:** The history panel intelligently positions itself:
        * To the **left** of the main cover art in wider (landscape) windows.
        * **Below** the main song details in taller (portrait) windows or when side space is limited.
    * Cover art for history items is cached locally for quick access and to minimise downloads.
    * A persistent text log (`song_history.log`) is maintained in the application's root directory, recording the timestamp, artist, and title of each recognised song.
    * Manages disk space by automatically cleaning up older cached history images.
* **State Persistence:**
    * Remembers the last successfully identified song (including its title, artist, and cover art path).
    * Restores and displays this last known song when the application starts up.
* **Audio Input Management:**
    * Allows manual selection of the audio input device index via `config.json`.
    * If no device is specified or the configured one is invalid, SongPi attempts to auto-select a suitable input device.
* **User Interface Controls:**
    * Toggle between fullscreen and windowed mode by pressing the `Esc` key.
    * The mouse cursor automatically hides after a few seconds of inactivity and reappears on movement.
* **Highly Configurable:**
    * Many aspects of the application's behaviour can be customised through the `config.json` file located in the `Files` directory.
    * Settings include audio recording parameters (format, channels, sample rate, chunk size, record seconds, device index), GUI update interval, blur strength, font sizes, history panel appearance (max items, art size, padding, offsets), network settings (timeout, retry count, retry delay), and logging preferences.

## Setup & Installation

1.  **Python:** Ensure you have Python installed (recommended version 3.8+).
2.  **Dependencies:** Install the required Python packages. These are listed in `requirements.txt` and can typically be installed by navigating to the `v1.1` (or relevant version) directory in your terminal and running:
    ```bash
    pip install -r requirements.txt
    ```
    Key dependencies include: `pyaudio`, `shazamio`, `requests`, `Pillow`, `screeninfo`.
3.  **Audio Input:** Make sure your PC has a working microphone or an audio input source that can capture the music you want to identify. For identifying system audio directly, you might need to configure a loopback device (like "Stereo Mix" on Windows or using software like VB-Cable).
4.  **Configuration (Optional):**
    * Before first run, you can review and modify `v1.1/Files/config.json`.
    * Specifically, you might want to set `audio.device_index` if you know which input device you want to use. If left as `null`, the application will try to pick one.

## Running the Application

* Navigate to the directory containing the version you want to run (e.g., `v1.1`).
* You may have a `Start.bat` (or similar) script to launch the application.
* Alternatively, you can run it directly using Python from within the `v1.1/Files/` directory:
    ```bash
    python SongPi.py
    ```
    (Ensure your terminal's working directory is `v1.1/Files/` or adjust the path to `SongPi.py` accordingly if running from `v1.1/`).

## Troubleshooting

* **No Audio Devices Found / Cannot Open Device:**
    * Ensure your microphone/input device is properly connected and enabled in your system settings.
    * Check the `audio.device_index` in `config.json`. Try setting it to `null` to let the app auto-select, or use a tool to list audio devices and find the correct index for your desired input. The application logs available devices if it fails to find a suitable one.
* **Recognition Fails:**
    * Ensure the audio is clear and loud enough.
    * Check your internet connection, as recognition requires communication with Shazam's servers.
    * Look at the application logs or console output for error messages from Shazamio or network requests.

---

## What's New in v1.1 (Latest Version)

Version 1.1 introduces significant enhancements over previous versions, focusing on user experience, reliability, and new functionalities:

* **Revamped Song History:**
    * Visually displays a list of recently recognised songs within the app.
    * Intelligently adapts its layout (side or below main info) based on window dimensions.
    * Caches cover art for history items and maintains a persistent `.log` file of all recognised tracks.
* **State Persistence:** The app now remembers the last identified song and restores it upon restarting.
* **Smarter Audio Device Handling:** Includes improved automatic selection of audio input devices if not explicitly configured or if the set device is invalid.
* **Enhanced Visuals & Layout:** More dynamic font scaling and more robust GUI updates. Placeholder images are shown if cover art is unavailable.
* **Expanded Configuration:** More options in `config.json` to customise the history panel, logging behaviour, and more.
* **Improved Reliability:** Features comprehensive logging for easier troubleshooting, a more graceful shutdown process, and safer file operations.
* **Code Quality:** Significant code refactoring for better readability, maintainability, and the introduction of type hinting.
