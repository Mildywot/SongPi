# SongPi - Song Recognition app written in Python

I wanted a program that could run continuously to recognise songs I'd play on vinyl records: 
- couldn't find one
- tried to make one (cheers ChatGPT for the help)
- somehow works?!

This project sets up a Python environment for recognizing songs using Shazamio, displaying album art with a blurred background, and dynamically adjusting text color based on background brightness. 
It uses Tkinter for the GUI and PyAudio for recording audio.

The following versions are available: 
- Raspberry Pi
- Windows (portable/easy as version: zip package that is already set up, just click the .exe to run)
- Windows (full/less easy version: installs a virtual Python environment and uses a script to run SongPi)

<details>
   <summary><h2>Raspberry Pi version</h2></summary>

### 1. Grab songpi.py and config.json file from [here](https://github.com/Mildywot/SongPi/tree/67d5aef5c0a94f321f2f83b06a3344e9e8749d90/SongPi%20-%20Pi%20version) and chuck them in a new folder

### 2. Install Python 
In terminal, update the package list & install Python:
```
sudo apt update
sudo apt upgrade
sudo apt install python3
```
### 3. Create a virtual environment in the current folder and activate it
```
python3 -m venv venv
source venv/bin/activate
```
### 4. Install the required dependicies: 
```
pip install pyaudio shazamio requests pillow screeninfo
```
### 5. Run SongPi
```
python shazam.py
```
When you're done, deactivate the virtual environment by running:
```
deactivate
```
</details>

<details>
   <summary><h2>Portable Windows setup instructions</h2></summary>

### 1. Download the 7zip file [Here](https://github.com/Mildywot/SongPi/tree/e9b0c92b65746b96c6b84673acddd6d015b774a9/SongPi%20-%20portable%20Windows)
(normal zip file wouldn't go smaller than 25MB for GitHub lol)


### 2. Extract the file and run ***SongPi.exe***
Enjoy 
</details> 


<details>
   <summary><h2>Full Windows setup instructions</h2></summary>

### 1. Download and extract the full Windows version from the releases section


### 2. Install Python

Install Python 3.12.3 from the Python website: https://www.python.org/downloads/release/python-3123/ 
(other Python versions probably work fine, just haven't tested them)

***Make sure that you select the 'add python.exe to PATH' option during the install.***


### 3. Run the Setup Script

Double click '1st time setup.bat' and let the script run until it finishes, if you get an error then try run it again I reckon. 
The script creates a virtual environment in Files\venv within your current folder, then installs four Python packages (pyaudio, shazamio, requests, and pillow screeninfo) using pip install.

***Once you've done the above setup the first time, you can just click the Start.bat file next time you want to run the program***


### 4. Run the script

Double click the 'Start.bat' file, it loads a virtual Python environment and runs the SongPi code for you.
</details> 

# Examples:
## Windowed
<img src="readme_images/Oshun-El-eee_windowed.png" style="width: 100%;" alt="Click to see the source">

<img src="readme_images/banger_windowed.png" style="width: 100%;" alt="Click to see the source">

## Full screen
<img src="readme_images/JVB_fullscreen.png" style="width: 100%;" alt="Click to see the source">

<img src="readme_images/divorced-aussie-dad-tunes_fullscreen.png" style="width: 100%;" alt="Click to see the source">

## Tips:

- Press Esc button to toggle between full screen and windowed mode, feel free to resize the window to your heart's content.
- Make sure your PC has a microphone (USB and built-in mics work well I think, haven't tested much else)
- Enjoy?! 

I'm surprised this works at all to be honest.

Let me know if you like it or have suggestions (especially for a better name, 'SongPi' is trash lol)

Cheers.

## Context on how this works:

1) SongPi loads the info from the config file, and sets up the environment for audio processing.

2) The audio input device (microphone) is selected using the functions list_audio_devices, select_input_device, and validate_device_channels handling the detection.

3) The record_audio function makes use of PyAudio's audio handling and records 4 seconds of audio from your microphone then saves it as a .WAV file (the recording time can be edited in the config, but recordings less than 3 seconds don't seem to work so well, so I settled on 4 seconds as its pretty consistent).

4) The recognize_song function uses the ShazamIO api to fingerprint the recorded audio in the .WAV file, send that fingerprint to Shazam, then receive back the song info. This functions runs in an asynchronous loop to repeatedly retry every 2 seconds in case of network errors.

5) Tkinter creates the GUI then displays the song title, artist and the cover art. It finds the display size of the current screen and only goes 'full screen' to the current screen (I was having issues with a multiple screen setup). I bound the escape button to toggle between full screen and windowed modes, along with having the mouse/cursor disappear after 5 seconds of inactivity (it shows again when moving the mouse). The update_images and update_gui functions only update if there are changes to the song recognition result (i.e. the GUI doesn't update if the same song or no song is detected).

6) Tkinter also modifies the font and text styling (song title is italic and the artist is bold), and anchors these below the central cover art (which resizes dynamically when detecting changes to the window size). The text should always be readable regardless of background colour as the calculate_brightness function adjusts the text colour based on the background's brightness. Thanks to my mate's suggestion, I changed the background to be the current cover art with a gaussian blur using the create_blurred_background function (initially it would find the most common colour of the cover art and displayed it as a solid coloured background, it looked kind of shit as half the time it was just black or white).

7) The background thread start_recognition_thread runs in the background separate to the GUI thread so it all remains responsive and usable. SongPi essentially records for 4 seconds, gets the song info back in about 1-2 seconds, then repeats the whole process every 5 seconds or so (depending on recognition its about 4-5 updates per minute).
