# --- START OF FILE shazam.py ---

import pyaudio
import wave
import asyncio
# import tkinter as tk
# from tkinter import font as tkFont
from shazamio import Shazam
import requests
from PIL import Image, ImageFilter, ImageStat, ImageDraw, ImageFont # ImageTk removed
import io
import os
import json
from screeninfo import get_monitors
import threading
import logging
import tempfile
from datetime import datetime
import shutil
import sys
from typing import Optional, Dict, Any, Tuple, List, Literal, Union
from pathlib import Path
import time # Potentially needed
import base64

# --- Constants ---
SCRIPT_DIR = Path(__file__).parent.resolve()

# APP_DATA_DIR will be determined by input from Neutralino or default.
# It needs to be globally accessible after being set in __main__ or relevant handler.
APP_DATA_DIR: Path = None # Will be set dynamically
DEFAULT_APP_DATA_PARENT_DIR = SCRIPT_DIR # Default if no path given (e.g. direct script run)
DEFAULT_APP_DATA_SUBDIR_NAME = 'data_default' # Subdirectory for default data

# Filenames (remain constant)
CONFIG_FILENAME = 'config.json'
DEFAULT_CONFIG_FILENAME = 'default_config.json' # For the bundled default
IMAGE_FILENAME = 'image.jpg'
TEMP_IMAGE_FILENAME = 'image_temp.jpg' # This can remain script-relative or system temp
HISTORY_IMAGE_DIR_NAME = 'history_images'
LAST_STATE_FILENAME = 'last_state.json'
SONG_HISTORY_FILENAME = 'song_history.log'
LOG_FILENAME = 'songpi_backend.log' # Changed from songpi.log to avoid conflict if SCRIPT_DIR is used by old logger

# Path variables - these will be dynamically set AFTER APP_DATA_DIR is known
CONFIG_PATH: Path = None
IMAGE_PATH: Path = None
HISTORY_IMAGE_DIR_PATH: Path = None
SONG_HISTORY_FILE_PATH: Path = None
LAST_STATE_FILE_PATH: Path = None
LOG_FILE_PATH: Path = None # For the logger

# TEMP_IMAGE_PATH can be decided: either APP_DATA_DIR or SCRIPT_DIR or system temp.
# Using SCRIPT_DIR for temp file is simpler for now if it's just for intermediate processing.
# However, if it's related to current song image, it should be in APP_DATA_DIR.
# Let's assume TEMP_IMAGE_PATH is for processing the current cover art, so make it APP_DATA_DIR related.
TEMP_IMAGE_PATH: Path = None


MIN_WINDOW_WIDTH = 250 # Likely unused
MIN_WINDOW_HEIGHT = 200 # Likely unused

# --- Global State ---
config: Dict[str, Any] = {} # Loaded config
# root: Optional[tk.Tk] = None # Tkinter removed
# canvas: Optional[tk.Canvas] = None # Tkinter removed
# title_label_id: Optional[int] = None # Tkinter removed
# artist_label_id: Optional[int] = None # Tkinter removed
# status_label_id: Optional[int] = None # Tkinter removed
# coverart_item_id: Optional[int] = None # Tkinter removed

# bg_photo_ref: Optional[ImageTk.PhotoImage] = None # ImageTk removed
# square_photo_ref: Optional[ImageTk.PhotoImage] = None # ImageTk removed
# history_photo_refs: List[Dict[str, Any]] = [] # Stores PIL.ImageTk objects, will need adjustment if history is kept
history_photo_refs: List[Dict[str, Any]] = [] # This will likely need to store file paths or PIL Images if GUI is separate

last_track_title: str = ""
last_artist_name: str = ""
last_persistent_image_path: Optional[str] = None
current_status_message: str = "Initialising..."
song_history_list: List[Dict[str, Any]] = [] # In-memory list of recent songs

resize_job_id: Optional[str] = None
cursor_hide_timer_id: Optional[str] = None
recognition_thread: Optional[threading.Thread] = None
recognition_thread_stop_event = threading.Event()

logger = logging.getLogger("SongRecognizer")


# --- Configuration Loading ---
def merge_dicts(source: Dict, destination: Dict) -> Dict:
    """Recursively merge source dict into destination dict."""
    for key, value in source.items():
        if isinstance(value, dict):
            node = destination.setdefault(key, {})
            merge_dicts(value, node)
        else:
            destination[key] = value
    return destination

def load_config() -> Dict[str, Any]:
    """Loads configuration from JSON file, providing defaults."""
    defaults = {
        "audio": {
            "format": "paInt16", "channels": 1, "sample_rate": 48000,
            "chunk_size": 8192, "record_seconds": 4, "device_index": None
        },
        "gui": {
            "update_interval_ms": 5000, "blur_strength": 15, "border_size_ratio": 0.15,
            "base_font_size": 12, "history_max_items": 5, # Max items displayed
            "history_art_size": 60, "history_item_padding": 10,
            "history_x_offset": 20, "history_y_offset": 20,
            "history_font_size_ratio": 0.7, "history_min_side_width": 300,
            "layout_side_min_buffer": 50, "layout_below_min_buffer": 50,
            "status_font_size_ratio": 0.8, # Base ratio before halving
            "history_max_items_retain": 20 # Max items to keep images for on disk
        },
        "network": {"timeout": 7, "retry_count": 3, "retry_delay": 2},
        "logging": {
             "level": "INFO",
             "format": "%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s",
             "datefmt": "%Y-%m-%d %H:%M:%S"
        }
    }
    loaded_config = {}
    # Use the globally defined CONFIG_PATH
    try:
        with open(CONFIG_PATH, 'r') as f:
            loaded_config = json.load(f)
        logger.debug(f"Configuration loaded from {CONFIG_PATH}")
    except FileNotFoundError:
        logger.warning(f"Configuration file not found at {CONFIG_PATH}. Using default settings.")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding configuration file {CONFIG_PATH}: {e}. Using default settings.")

    final_config = defaults.copy()
    merge_dicts(loaded_config, final_config)


    log_cfg = final_config.get("logging", defaults["logging"])
    log_level_str = log_cfg.get("level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Clear existing handlers (if any) to avoid duplicate logging on re-runs in same session (e.g. testing)
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]: # Iterate over a copy
            root_logger.removeHandler(handler)
            handler.close()

    # Configure file logging to the new LOG_FILE_PATH (which is based on APP_DATA_DIR)
    if LOG_FILE_PATH: # LOG_FILE_PATH should be set before load_config is called
        log_file_path_obj = LOG_FILE_PATH
    else: # Fallback if somehow not set (should not happen if setup_app_paths is called)
        log_file_path_obj = APP_DATA_DIR / LOG_FILENAME

    file_handler = logging.FileHandler(log_file_path_obj, encoding='utf-8')
    formatter = logging.Formatter(log_cfg.get("format"), log_cfg.get("datefmt"))
    file_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.setLevel(log_level)
    logger.info(f"Logging configured at level {log_level_str} to {log_file_path_obj}.")

    # Config file handling
    # CONFIG_PATH should already be set based on APP_DATA_DIR before this function is called
    if not CONFIG_PATH.is_file():
        logger.info(f"Config file not found at {CONFIG_PATH}. Attempting to copy default config.")
        try:
            default_config_src = SCRIPT_DIR / DEFAULT_CONFIG_FILENAME
            if default_config_src.is_file():
                shutil.copy2(default_config_src, CONFIG_PATH)
                logger.info(f"Copied default config from {default_config_src} to {CONFIG_PATH}")
            else:
                logger.warning(f"Default config {default_config_src} not found. Using hardcoded defaults.")
        except Exception as e:
            logger.error(f"Error copying default config: {e}. Using hardcoded defaults.")

    loaded_from_file = {}
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH, 'r') as f:
                loaded_from_file = json.load(f)
            logger.debug(f"Configuration loaded from {CONFIG_PATH}")
        except FileNotFoundError: # Should be handled by copy above, but as a safeguard
            logger.warning(f"Configuration file not found at {CONFIG_PATH} after copy attempt. Using default settings.")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding configuration file {CONFIG_PATH}: {e}. Using default settings.")

    final_config = defaults.copy()
    merge_dicts(loaded_from_file, final_config) # Merge loaded config into defaults

    # Ensure data subdirectories are created (IMAGE_PATH's parent, HISTORY_IMAGE_DIR_PATH)
    # These paths should be set before load_config is called.
    try:
        if IMAGE_PATH: IMAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if HISTORY_IMAGE_DIR_PATH: HISTORY_IMAGE_DIR_PATH.mkdir(parents=True, exist_ok=True)
        logger.info(f"Checked/created data subdirectories within {APP_DATA_DIR}")
    except Exception as e: # More general exception if paths are None
        logger.error(f"Could not create data subdirectories: {e} (APP_DATA_DIR may not be set yet)")

    return final_config


# --- Audio Handling ---
# ... (Audio handling functions remain unchanged) ...
def list_audio_devices() -> List[Tuple[int, str, int]]:
    """Lists available input audio devices."""
    audio = None
    devices = []
    try:
        logger.debug("Initializing PyAudio to list devices...")
        audio = pyaudio.PyAudio()
        host_api_info = audio.get_host_api_info_by_index(0)
        num_devices = host_api_info.get('deviceCount', 0)
        logger.debug(f"Host API reports {num_devices} devices.")
        for i in range(num_devices):
            try:
                device_info = audio.get_device_info_by_host_api_device_index(0, i)
                if device_info.get('maxInputChannels', 0) > 0:
                     logger.debug(f"  Device {i}: {device_info['name']} (In:{device_info['maxInputChannels']}, Out:{device_info['maxOutputChannels']})")
                     devices.append((i, device_info['name'], device_info['maxInputChannels']))
            except Exception as e:
                logger.warning(f"Could not query device index {i}: {e}")
        logger.info(f"Found {len(devices)} input devices.")
    except Exception as e:
         logger.error(f"Error listing audio devices: {e}", exc_info=True)
    finally:
        if audio:
            audio.terminate()
            logger.debug("PyAudio terminated after listing devices.")
    return devices

def validate_device_channels(device_index: int, required_channels: int) -> bool:
    """Checks if a device index is valid and has enough input channels."""
    audio = None
    is_valid = False
    try:
        logger.debug(f"Validating device index {device_index} for {required_channels} channels...")
        audio = pyaudio.PyAudio()
        device_info = audio.get_device_info_by_index(device_index)
        actual_channels = device_info.get('maxInputChannels', 0)
        is_valid = actual_channels >= required_channels
        logger.debug(f"Device {device_index} ('{device_info.get('name', 'N/A')}') has {actual_channels} channels. Valid: {is_valid}")
    except OSError as e:
        logger.warning(f"Device index {device_index} seems invalid or inaccessible: {e}")
    except Exception as e:
        logger.error(f"Error validating device {device_index}: {e}")
    finally:
        if audio:
            audio.terminate()
            logger.debug(f"PyAudio terminated after validating device {device_index}.")
    return is_valid

def select_input_device(required_channels: int) -> Optional[int]:
    """Automatically selects the first suitable input device."""
    logger.info("Attempting to auto-select an input device...")
    devices = list_audio_devices()
    if not devices:
        logger.error("No input audio devices found during auto-selection.")
        return None
    preferred_keywords = ["pulse", "default", "sampler", "loopback", "monitor", "what u hear", "stereo mix"]
    suitable_devices = []
    other_suitable_devices = []
    for i, name, channels in devices:
        if channels >= required_channels:
            if any(keyword in name.lower() for keyword in preferred_keywords):
                suitable_devices.append((i, name))
            else:
                other_suitable_devices.append((i, name))
    if suitable_devices:
        selected_index, device_name = suitable_devices[0]
        logger.info(f"Auto-selected preferred input device: Index {selected_index} ('{device_name}')")
        return selected_index
    elif other_suitable_devices:
         selected_index, device_name = other_suitable_devices[0]
         logger.info(f"Auto-selected input device: Index {selected_index} ('{device_name}')")
         return selected_index
    else:
        logger.error(f"No input device found with required channels ({required_channels}). Available devices logged previously.")
        return None

def record_audio() -> Optional[str]:
    """Records audio for a configured duration to a temporary WAV file."""
    global current_status_message
    # schedule_gui_update(set_status_message, "Listening...") # UI Call
    set_status_message("Listening...") # Keep logic, schedule_gui_update is no-op
    audio_cfg = config['audio']
    dev_index = audio_cfg.get('device_index')
    chans = audio_cfg['channels']
    samp_rate = audio_cfg['sample_rate']
    record_secs = audio_cfg['record_seconds']
    chunk = audio_cfg['chunk_size']
    audio = None
    try:
        py_audio_format = getattr(pyaudio, audio_cfg['format'])
    except AttributeError:
        logger.error(f"Invalid PyAudio format: {audio_cfg['format']}")
        # schedule_gui_update(set_status_message, "Error: Invalid audio format") # UI Call
        set_status_message("Error: Invalid audio format")
        return None

    selected_device_index = dev_index
    if selected_device_index is None or not validate_device_channels(selected_device_index, chans):
        if selected_device_index is not None:
            logger.warning(f"Configured device index {selected_device_index} invalid/insufficient. Auto-selecting.")
        else:
            logger.info("No device index configured. Auto-selecting.")
        selected_device_index = select_input_device(chans)
        if selected_device_index is None:
            # schedule_gui_update(set_status_message, "Error: No suitable audio device") # UI Call
            set_status_message("Error: No suitable audio device")
            return None
        else:
            config['audio']['device_index'] = selected_device_index

    stream = None
    temp_wav_path: Optional[str] = None
    try:
        # Use the globally defined TEMP_IMAGE_PATH for consistency?
        # No, NamedTemporaryFile handles system temp dir better.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_f:
            temp_wav_path = temp_f.name
        logger.debug(f"Created temporary WAV file: {temp_wav_path}")
        logger.debug("Initializing PyAudio for recording...")
        audio = pyaudio.PyAudio()
        logger.debug(f"Opening audio stream on device {selected_device_index}...")
        stream = audio.open(format=py_audio_format, rate=samp_rate, channels=chans,
                            input_device_index=selected_device_index, input=True, frames_per_buffer=chunk)
        logger.info(f"Recording started on device {selected_device_index}...")
        frames = []
        num_chunks_to_record = int((samp_rate / chunk) * record_secs)
        for i in range(num_chunks_to_record):
            if recognition_thread_stop_event.is_set():
                logger.info("Recording stopped early by shutdown signal.")
                # schedule_gui_update(set_status_message, "Shutting down...") # UI Call
                set_status_message("Shutting down...")
                safe_remove(temp_wav_path, "temp WAV on cancelled recording")
                return None
            try:
                data = stream.read(chunk, exception_on_overflow=False)
                frames.append(data)
            except IOError as e:
                if e.errno == pyaudio.paInputOverflowed:
                    logger.warning("Input overflowed during recording.")
                else:
                    logger.error(f"IOError during stream read: {e}")
                    # schedule_gui_update(set_status_message, "Error: Audio input failed") # UI Call
                    set_status_message("Error: Audio input failed")
                    safe_remove(temp_wav_path, "temp WAV on IO read error")
                    return None
            except Exception as e:
                logger.exception(f"Unexpected error reading audio stream: {e}")
                # schedule_gui_update(set_status_message, "Error: Audio read failed") # UI Call
                set_status_message("Error: Audio read failed")
                safe_remove(temp_wav_path, "temp WAV on unexpected read error")
                return None
        logger.info(f"Recording finished ({len(frames)} chunks captured).")
    except OSError as e:
        logger.error(f"OSError opening stream on device {selected_device_index}: {e}")
        # schedule_gui_update(set_status_message, f"Error: Cannot open device {selected_device_index}") # UI Call
        set_status_message(f"Error: Cannot open device {selected_device_index}")
        safe_remove(temp_wav_path, "temp WAV on stream open error")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during recording: {e}")
        # schedule_gui_update(set_status_message, "Error: Recording failed") # UI Call
        set_status_message("Error: Recording failed")
        safe_remove(temp_wav_path, "temp WAV on unexpected setup error")
        return None
    finally:
        if stream:
            try:
                if stream.is_active(): stream.stop_stream()
                stream.close()
                logger.debug("Audio stream stopped/closed.")
            except Exception as e:
                logger.warning(f"Error closing audio stream: {e}")
        if audio:
            audio.terminate()
            logger.debug("PyAudio terminated after recording.")

    if temp_wav_path and frames:
        logger.debug(f"Writing {len(frames)} frames to {temp_wav_path}")
        audio_instance_for_size = None
        try:
            audio_instance_for_size = pyaudio.PyAudio()
            sample_width = audio_instance_for_size.get_sample_size(py_audio_format)

            with wave.open(temp_wav_path, 'wb') as wave_file_obj:
                 wave_file_obj.setnchannels(chans)
                 wave_file_obj.setsampwidth(sample_width)
                 wave_file_obj.setframerate(samp_rate)
                 wave_file_obj.writeframes(b''.join(frames))
            logger.info(f"Audio saved successfully to: {temp_wav_path}")
            return temp_wav_path
        except wave.Error as e:
            logger.error(f"Wave library error writing WAV file {temp_wav_path}: {e}")
            # schedule_gui_update(set_status_message, "Error: Could not save audio") # UI Call
            set_status_message("Error: Could not save audio")
            safe_remove(temp_wav_path, "temp WAV on wave write error")
            return None
        except Exception as e:
             logger.exception(f"Unexpected error writing WAV file: {e}")
             # schedule_gui_update(set_status_message, "Error: Saving audio failed") # UI Call
             set_status_message("Error: Saving audio failed")
             safe_remove(temp_wav_path, "temp WAV on unexpected write error")
             return None
        finally:
            if audio_instance_for_size:
                audio_instance_for_size.terminate()

    else:
        if not frames:
            logger.warning("No audio frames captured.")
            # schedule_gui_update(set_status_message, "Error: No audio captured") # UI Call
            set_status_message("Error: No audio captured")
        safe_remove(temp_wav_path, "temp WAV when no frames recorded")
        return None


# --- Song Recognition ---
# ... (recognize_song function remains unchanged) ...
async def recognize_song(wav_file_path: str) -> Optional[Dict[str, Any]]:
    """Recognizes the song from a WAV file using Shazamio."""
    # schedule_gui_update(set_status_message, "Recognizing...") # UI Call
    set_status_message("Recognizing...")
    shazam = Shazam()
    max_retries = config['network']['retry_count']
    retry_delay = config['network']['retry_delay']
    result = None
    for attempt in range(max_retries):
        if recognition_thread_stop_event.is_set():
            logger.info("Recognition cancelled by shutdown.")
            # schedule_gui_update(set_status_message, "Shutting down...") # UI Call
            set_status_message("Shutting down...")
            return None
        try:
            logger.info(f"Attempting recognition (Attempt {attempt + 1}/{max_retries})...")
            new_result = await shazam.recognize(wav_file_path)
            logger.debug(f"Raw result (Attempt {attempt+1}): {new_result}")
            if isinstance(new_result, dict):
                 if 'track' in new_result and new_result['track']:
                     logger.info("Recognition successful.")
                     result = new_result
                     break
                 elif 'matches' in new_result and not new_result.get('matches'):
                     logger.info("Recognition: No match.")
                     result = new_result
                     break
                 else:
                     if 'track' in new_result and not new_result['track']:
                         logger.info("Recognition: Got result structure but no track info (effectively no match).")
                         result = {'matches': []}
                         break
                     else:
                         logger.warning(f"Recognition attempt {attempt + 1} unexpected format/content: {new_result}")

            else:
                 logger.warning(f"Recognition attempt {attempt + 1} returned non-dict type: {type(new_result)}")
        except Exception as e:
            logger.error(f"Recognition attempt {attempt + 1} failed: {e}", exc_info=False)
            if attempt < max_retries - 1:
                 # schedule_gui_update(set_status_message, f"Retrying ({attempt+2})...") # UI Call
                 set_status_message(f"Retrying ({attempt+2})...")
                 try:
                     await asyncio.sleep(retry_delay)
                 except asyncio.CancelledError:
                     logger.info("Asyncio sleep cancelled during retry.")
                     return None
            else:
                logger.error("Max retry attempts reached for recognition.")
                # schedule_gui_update(set_status_message, "Error: Recognition failed") # UI Call
                set_status_message("Error: Recognition failed")
                result = None
                break
    return result

# --- Image Processing ---
# ... (create_blurred_background, calculate_brightness, create_placeholder_image functions remain unchanged) ...
def create_blurred_background(source_image_path: Path, target_width: int, target_height: int, blur_strength: int) -> Optional[Image.Image]:
    """Creates a blurred, cropped, and resized background image."""
    if not source_image_path.is_file():
        logger.warning(f"Source for blur does not exist: {source_image_path}")
        return None
    try:
        logger.debug(f"Creating blurred background from: {source_image_path}")
        with Image.open(source_image_path) as original_image:
            original_image = original_image.convert('RGB')
            blurred_image = original_image.filter(ImageFilter.GaussianBlur(blur_strength))
            source_aspect = original_image.width / original_image.height
            target_aspect = target_width / target_height

            if target_aspect > source_aspect:
                new_width = target_width
                new_height = int(new_width / source_aspect)
            else:
                new_height = target_height
                new_width = int(new_height * source_aspect)

            blurred_image = blurred_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            left = (new_width - target_width) // 2
            top = (new_height - target_height) // 2
            right = left + target_width
            bottom = top + target_height

            blurred_image = blurred_image.crop((left, top, right, bottom))
            logger.debug("Blurred background created.")
            return blurred_image
    except FileNotFoundError:
        logger.error(f"FileNotFound during blur (should be caught earlier): {source_image_path}")
        return None
    except Exception as e:
        logger.exception(f"Error creating blurred background from {source_image_path}: {e}")
        return None

def calculate_brightness(image: Image.Image) -> float:
    """Calculates the perceived brightness of an image (0.0 to 1.0)."""
    try:
        grayscale_image = image.convert('L')
        stat = ImageStat.Stat(grayscale_image)
        brightness = stat.mean[0] / 255.0
        logger.debug(f"Calculated brightness: {brightness:.2f}")
        return brightness
    except Exception as e:
        logger.warning(f"Could not calculate brightness: {e}")
        return 0.5

def create_placeholder_image(path: Path, width: int, height: int, text: str) -> bool:
    """Creates a simple placeholder image with text and saves it."""
    logger.info(f"Creating placeholder image at: {path}")
    try:
        img = Image.new('RGB', (width, height), color = (70, 70, 70))
        d = ImageDraw.Draw(img)
        try:
            font_size = max(15, int(min(width, height) * 0.1))
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except IOError:
                try:
                    font = ImageFont.truetype("verdana.ttf", font_size)
                except IOError:
                    logger.warning("Arial/Verdana not found, using default PIL font.")
                    font = ImageFont.load_default()

            if hasattr(d, 'textbbox'):
                 bbox = d.textbbox((0, 0), text, font=font, anchor="lt")
                 text_width = bbox[2] - bbox[0]
                 text_height = bbox[3] - bbox[1]
            else:
                 text_width, text_height = d.textsize(text, font=font)

            text_x = (width - text_width) / 2
            text_y = (height - text_height) / 2
            d.text((text_x, text_y), text, fill=(200, 200, 200), font=font)
        except Exception as font_e:
            logger.error(f"Error during text drawing on placeholder: {font_e}")
            pass
        img.save(path)
        logger.info(f"Placeholder saved.")
        return True
    except Exception as e:
        logger.error(f"Failed to create placeholder image {path}: {e}")
        return False

# --- History Management ---
# ... (safe_remove, add_to_history, cleanup_old_history_images functions remain unchanged) ...
def safe_remove(path: Optional[Union[str, Path]], description: str = "file") -> bool:
    """Safely remove a file or path, logging errors. Returns True if removed, False otherwise."""
    if path:
        path_obj = Path(path)
        if path_obj.is_file():
            try:
                path_obj.unlink()
                logger.debug(f"Removed {description}: {path_obj}")
                return True
            except OSError as e:
                logger.error(f"Error removing {description} {path_obj}: {e}")
                return False
    return False


def add_to_history(track_title: str, artist_name: str, source_image_path: Path) -> Optional[str]:
    """Adds song to history, copies art, manages list size, logs to file, returns persistent path."""
    global song_history_list
    if song_history_list and song_history_list[0]['title'] == track_title and song_history_list[0]['artist'] == artist_name:
        logger.debug("Skipping adding duplicate song to history (same as last).")
        return song_history_list[0]['image_path']

    timestamp = datetime.now()
    safe_title = "".join(c for c in track_title if c.isalnum() or c in (' ', '_')).rstrip()[:30].replace(' ', '_')
    history_filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{safe_title}.jpg"
    persistent_image_path_obj = HISTORY_IMAGE_DIR_PATH / history_filename
    persistent_image_path_str = str(persistent_image_path_obj)

    try:
        if not source_image_path.is_file():
            logger.error(f"Source for history copy does not exist: {source_image_path}")
            return None

        HISTORY_IMAGE_DIR_PATH.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_image_path, persistent_image_path_obj)
        logger.info(f"Copied cover art to history: {persistent_image_path_obj}")

        history_entry = {'title': track_title, 'artist': artist_name, 'image_path': persistent_image_path_str, 'timestamp': timestamp}
        song_history_list.insert(0, history_entry)

        max_mem_items = config['gui']['history_max_items'] + 1
        if len(song_history_list) > max_mem_items:
            song_history_list = song_history_list[:max_mem_items]
            logger.debug(f"Pruned in-memory history list to {max_mem_items} items.")


        try:
            log_timestamp = timestamp.strftime('%Y-%m-%d %H:%M')
            log_line = f"{log_timestamp} | {artist_name} - {track_title}\n"
            with open(SONG_HISTORY_FILE_PATH, 'a', encoding='utf-8') as f:
                f.write(log_line)
            logger.debug(f"Logged song to history file: {SONG_HISTORY_FILE_PATH}")
        except IOError as e:
            logger.error(f"Failed to write to song history file {SONG_HISTORY_FILE_PATH}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error writing to history log file: {e}")

        return persistent_image_path_str

    except FileNotFoundError:
        logger.error(f"Source not found during history copy: {source_image_path}")
        return None
    except OSError as e:
        logger.error(f"OS error during history image copy or directory creation: {e}")
        safe_remove(persistent_image_path_obj, "history image on OS error")
        return None
    except Exception as e:
        logger.exception(f"Error adding song to history/copying image {source_image_path}: {e}")
        safe_remove(persistent_image_path_obj, "history image on error")
        return None

def cleanup_old_history_images(keep_count: int = 20):
    """Removes oldest history images based on filename timestamp, keeping the specified number."""
    logger.info(f"Running history cleanup, aiming to keep newest {keep_count} images based on filename.")
    if not HISTORY_IMAGE_DIR_PATH.is_dir():
        logger.warning(f"History image directory not found: {HISTORY_IMAGE_DIR_PATH}. Skipping cleanup.")
        return

    try:
        history_files = [
            p for p in HISTORY_IMAGE_DIR_PATH.glob('*.jpg') if p.is_file()
        ]
        history_files.sort(key=lambda p: p.name, reverse=True)

        if len(history_files) > keep_count:
            files_to_remove = history_files[keep_count:]
            logger.info(f"Found {len(history_files)} history images. Removing {len(files_to_remove)} oldest ones.")
            removed_count = 0
            for file_path in files_to_remove:
                if safe_remove(file_path, "old history image during cleanup"):
                    removed_count += 1
            logger.info(f"History cleanup finished. Successfully removed {removed_count} images.")
        else:
            logger.info(f"Found {len(history_files)} history images. No cleanup needed (Keep count: {keep_count}).")

    except OSError as e:
        logger.error(f"OS Error during history cleanup scan in {HISTORY_IMAGE_DIR_PATH}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error during history image cleanup: {e}")


# --- State Persistence ---
# ... (save_last_state, load_last_state functions remain unchanged) ...
def save_last_state(title: str, artist: str, persistent_image_path: Optional[str]):
    """Saves the last successfully identified song details."""
    state = {
        'title': title,
        'artist': artist,
        'persistent_image_path': persistent_image_path,
        'timestamp': datetime.now().isoformat()
    }
    try:
        with open(LAST_STATE_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4)
        logger.info(f"Saved last state to {LAST_STATE_FILE_PATH}")
    except IOError as e:
        logger.error(f"Failed to save last state to {LAST_STATE_FILE_PATH}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error saving last state: {e}")

def load_last_state() -> bool:
    """Loads the last state if available and valid."""
    global last_track_title, last_artist_name, last_persistent_image_path, current_status_message
    if not LAST_STATE_FILE_PATH.is_file():
        logger.info("No previous state file found.")
        return False
    try:
        logger.info(f"Loading last state from: {LAST_STATE_FILE_PATH}")
        with open(LAST_STATE_FILE_PATH, 'r', encoding='utf-8') as f:
            state = json.load(f)

        required_keys = ['title', 'artist']
        if not all(key in state for key in required_keys):
            logger.warning("Last state file missing required keys (title, artist). Discarding.")
            safe_remove(LAST_STATE_FILE_PATH, "invalid last state file")
            return False

        last_track_title = state.get('title', 'Unknown Title')
        last_artist_name = state.get('artist', 'Unknown Artist')
        logger.info(f"Restored last known song text: '{last_track_title}' by {last_artist_name}")
        text_loaded = True

        image_restored = False
        img_path_str = state.get('persistent_image_path')
        if img_path_str:
            img_path = Path(img_path_str)
            if img_path.is_file():
                try:
                    shutil.copy2(img_path, IMAGE_PATH)
                    logger.info(f"Restored active image '{IMAGE_PATH}' from persistent state: {img_path}")
                    last_persistent_image_path = img_path_str
                    image_restored = True
                except Exception as e:
                    logger.error(f"Failed to copy image from last state {img_path} to {IMAGE_PATH}: {e}")
                    safe_remove(IMAGE_PATH, "failed restore image copy")
                    last_persistent_image_path = None
            else:
                logger.warning(f"Image path in last state file not found: {img_path}. Active image may be missing.")
                last_persistent_image_path = None
        else:
             logger.info("Persistent image path null/missing in last state file. Active image may be missing.")
             last_persistent_image_path = None

        if not IMAGE_PATH.is_file():
            create_placeholder_image(IMAGE_PATH, 300, 300, "Image Unavailable")

        if text_loaded:
            if image_restored:
                 # schedule_gui_update(set_status_message, "Ready (Restored)") # UI Call
                 set_status_message("Ready (Restored)")
            else:
                 # schedule_gui_update(set_status_message, "Ready (Restored Text Only)") # UI Call
                 set_status_message("Ready (Restored Text Only)")
            return True
        else:
            return False

    except json.JSONDecodeError:
        logger.error(f"Error decoding last state file: {LAST_STATE_FILE_PATH}. Discarding.")
        safe_remove(LAST_STATE_FILE_PATH, "corrupted last state file")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error loading last state: {e}")
        return False


# --- GUI Update Functions ---
# ... (schedule_gui_update, set_status_message, update_status_display_text functions remain unchanged) ...
def schedule_gui_update(func, *args):
    """Schedules a function to run safely on the main Tkinter thread. (COMMENTED OUT)"""
    # This function is now a no-op as Tkinter is removed.
    # Neutralino will handle communication with the frontend.
    # logger.debug(f"Attempted GUI update ({func.__name__}) with args: {args} - (No-op due to Tkinter removal)")
    pass

def set_status_message(message: str):
    """ Safely update the global status message and trigger display update """
    global current_status_message
    if message != current_status_message:
         current_status_message = message
         logger.debug(f"Status updated: {message}")
         # schedule_gui_update(update_status_display_text) # UI Call, update_status_display_text is commented

def update_status_display_text():
    pass

def update_images() -> Dict[str, Any]:
    pass


def redraw_history_display(layout_info: Dict[str, Any]):
    pass


# ... (update_gui, trigger_full_redraw, Event Handlers, Async Task Runner, Main Execution functions remain unchanged) ...
def update_gui(update_data: Dict[str, Any]):
    pass


def trigger_full_redraw():
    pass

def get_monitor_for_window() -> Optional[Any]:
    pass


def toggle_fullscreen(event=None):
    pass

def hide_cursor():
    pass

def show_cursor():
    pass

def reset_cursor_hide_timer(event=None):
    pass

def on_resize(event=None):
    pass

def on_closing():
    """Handles the window closing event for graceful shutdown."""
    global recognition_thread, recognition_thread_stop_event, root
    logger.info("Shutdown requested via window close.")

    # set_status_message("Shutting down...") # UI Call, set_status_message has its own schedule_gui_update commented
    logger.info("on_closing called. Setting status to Shutting down...") # Direct log
    current_status_message = "Shutting down..." # Set global directly

    if recognition_thread_stop_event:
        logger.debug("Setting stop event for recognition thread.")
        recognition_thread_stop_event.set()

    if recognition_thread and recognition_thread.is_alive():
        logger.info(f"Waiting for {recognition_thread.name} to join (max 5s)...")
        recognition_thread.join(timeout=5.0)
        if recognition_thread.is_alive():
            logger.warning(f"{recognition_thread.name} did not stop gracefully within timeout.")
        else:
            logger.info(f"{recognition_thread.name} finished.")
    else:
        logger.debug("Recognition thread was not running or already finished.")

    try:
        retain_count = config['gui'].get('history_max_items_retain', 20)
        cleanup_old_history_images(keep_count=retain_count)
    except Exception as e:
        logger.exception("Error occurred during history cleanup call.")

    safe_remove(TEMP_IMAGE_PATH, "temp image on closing") # TEMP_IMAGE_PATH is now under DATA_DIR_PATH

    #     logger.info("Destroying Tkinter window.") # Tkinter removed
    #     try: # Tkinter removed
    #          root.after_idle(root.destroy) # Tkinter removed
    #     except tk.TclError as e: # Tkinter removed
    #          logger.warning(f"TclError during root.destroy(): {e}") # Tkinter removed
    #     root = None # Tkinter removed

    logger.info("Shutdown sequence complete.")

async def process_recognition_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """ Processes successful Shazam result: checks cache, downloads image (with retries), adds to history, saves state."""
    global song_history_list
    track_info = result.get('track', {})
    new_title = track_info.get('title', 'Unknown Title')
    new_artist = track_info.get('subtitle', 'Unknown Artist')

    logger.info(f"Processing result: '{new_title}' by '{new_artist}'")

    persistent_path_for_this_song: Optional[str] = None # Path to be saved in state
    image_processed_successfully = False # Track if we have a valid image for this song
    last_image_error_message = ""
    current_display_image_path = IMAGE_PATH # Path for the active image in the GUI
    cache_hit = False # Flag to track if cache was used

    # --- Check Cache First ---
    logger.debug("Checking history cache for existing cover art...")
    for history_item in song_history_list:
        if history_item.get('title') == new_title and history_item.get('artist') == new_artist:
            cached_image_path_str = history_item.get('image_path')
            if cached_image_path_str:
                cached_image_path = Path(cached_image_path_str)
                if cached_image_path.is_file():
                    logger.info(f"Cache hit found: {cached_image_path}")
                    try:
                        shutil.copy2(cached_image_path, current_display_image_path)
                        logger.info(f"Copied cached image to active path: {current_display_image_path}")
                        image_processed_successfully = True
                        last_image_error_message = "Used Cache"
                        cache_hit = True
                        persistent_path_for_this_song = str(cached_image_path) # Use the existing path
                        break
                    except OSError as e:
                        logger.error(f"Failed to copy cached image {cached_image_path} to {current_display_image_path}: {e}")
                    except Exception as e:
                        logger.exception(f"Unexpected error copying cached image: {e}")
                else:
                    logger.warning(f"Cache hit found path {cached_image_path}, but file does not exist.")
            else:
                 logger.warning(f"Cache hit found for song, but history item lacks image path.")
        if cache_hit:
            break

    # --- Download if Cache Miss (with Retries) ---
    if not cache_hit:
        logger.info("Cache miss or failed to use cache. Attempting download...")
        images_dict = track_info.get('images', {})
        hq_url = images_dict.get('coverarthq')
        std_url = images_dict.get('coverart')
        urls_to_try = [url for url in [hq_url, std_url] if isinstance(url, str) and url.startswith('http')]
        network_timeout = config['network']['timeout']
        max_retries = config['network']['retry_count']
        retry_delay = config['network']['retry_delay']
        last_image_error_message = "No Cover Art URL"

        if not urls_to_try:
            logger.warning("No valid cover art URLs found for download.")
        else:
            for url in urls_to_try: # Try HQ then Standard
                logger.info(f"Attempting image download from URL: {url}")
                for attempt in range(max_retries):
                    if recognition_thread_stop_event.is_set():
                        logger.info("Image download cancelled by shutdown.")
                        last_image_error_message = "Download Cancelled"
                        image_processed_successfully = False
                        break # Break inner retry loop

                    logger.debug(f"  Download attempt {attempt + 1}/{max_retries}...")
                    try:
                        response = requests.get(url, timeout=network_timeout, stream=True)
                        response.raise_for_status()

                        with open(TEMP_IMAGE_PATH, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)

                        if TEMP_IMAGE_PATH.stat().st_size > 0:
                            try:
                                with Image.open(TEMP_IMAGE_PATH) as img_verify: img_verify.verify()
                                os.replace(TEMP_IMAGE_PATH, current_display_image_path)
                                logger.info(f"Image downloaded and updated successfully (Attempt {attempt+1}) using URL: {url}")
                                image_processed_successfully = True # Mark success
                                last_image_error_message = "" # Clear error
                                break # SUCCESS: Break inner retry loop
                            except (Image.UnidentifiedImageError, SyntaxError, TypeError, ValueError) as verify_e:
                                last_image_error_message = f"Downloaded file invalid ({verify_e.__class__.__name__})"
                                logger.error(f"  {last_image_error_message} from {url} (Attempt {attempt+1})")
                                safe_remove(TEMP_IMAGE_PATH, "invalid downloaded image")
                        else:
                            last_image_error_message = "Downloaded Image Empty"
                            logger.error(f"  {last_image_error_message} for URL {url} (Attempt {attempt+1})")
                            safe_remove(TEMP_IMAGE_PATH, "empty downloaded image")

                    except requests.exceptions.Timeout:
                         last_image_error_message = "Download Timeout"
                         logger.warning(f"  {last_image_error_message} for {url} (Attempt {attempt+1}, timeout={network_timeout}s)")
                    except requests.exceptions.RequestException as e:
                         last_image_error_message = f"Download Failed ({e.__class__.__name__})"
                         logger.warning(f"  {last_image_error_message} for {url} (Attempt {attempt+1}): {e}")
                    except Exception as e:
                         last_image_error_message = f"Unknown Image Error ({e.__class__.__name__})"
                         logger.exception(f"  {last_image_error_message} during download/processing for {url} (Attempt {attempt+1}): {e}")
                    finally:
                        safe_remove(TEMP_IMAGE_PATH, "temp image after download attempt")

                    if image_processed_successfully:
                        break

                    if attempt < max_retries - 1 and not recognition_thread_stop_event.is_set():
                        logger.debug(f"  Waiting {retry_delay}s before next download attempt...")
                        try:
                            await asyncio.sleep(retry_delay)
                        except asyncio.CancelledError:
                             logger.info("Image download sleep cancelled.")
                             last_image_error_message = "Download Cancelled"
                             break

                if image_processed_successfully or recognition_thread_stop_event.is_set():
                    break

            if not image_processed_successfully and not last_image_error_message:
                 last_image_error_message = "Image Download Failed (Unknown Reason)"


    # --- Add to History & Save State ---
    final_persistent_path = None

    # Only add to history if image was successfully processed
    if image_processed_successfully and current_display_image_path.is_file():
        logger.debug(f"Adding to history using valid active image: {current_display_image_path}")
        final_persistent_path = add_to_history(new_title, new_artist, current_display_image_path)
        if final_persistent_path:
            logger.debug(f"Song added/updated in history. Persistent path: {final_persistent_path}")
        else:
            logger.error("add_to_history returned None despite processed image. State might be inconsistent.")
    elif not image_processed_successfully:
        logger.warning("Image download/cache failed. Not adding entry to history cache.")
    else:
        logger.warning("No valid display image path available despite image_processed_successfully=True.")


    path_to_save = persistent_path_for_this_song if cache_hit else final_persistent_path
    save_last_state(new_title, new_artist, path_to_save)

    return {
        'status': 'success',
        'title': new_title,
        'artist': new_artist,
        'persistent_path': path_to_save,
        'image_updated': image_processed_successfully,
        'message': last_image_error_message
    }


async def periodic_recognition_task(stop_event: threading.Event = None): # stop_event can be None for single run
    """The main async loop: record -> recognize -> process -> schedule update -> wait."""
    # interval_seconds = config['gui']['update_interval_ms'] / 1000.0 # Not used for single run
    # wait_chunk = 0.1 # Not used for single run

    # This loop is removed for on-demand execution.
    # while not stop_event.is_set():
    logger.info("--- Starting New Recognition Cycle (On-Demand) ---")
    update_data = {'status': 'error', 'message': 'Cycle Interrupted'}
    wav_file_path = None
    try:
        wav_file_path = record_audio()

        # if wav_file_path and not stop_event.is_set(): # stop_event check removed for single run
        if wav_file_path:
             shazam_result = await recognize_song(wav_file_path)

             # if shazam_result and not stop_event.is_set(): # stop_event check removed
             if shazam_result:
                  if 'track' in shazam_result and shazam_result.get('track'):
                       update_data = await process_recognition_result(shazam_result)
                  elif 'matches' in shazam_result and not shazam_result.get('matches'):
                       update_data = {'status': 'no_match', 'message': 'No Match Found'}
                  else:
                       logger.error(f"Unexpected Shazam result format or empty track: {shazam_result}")
                       update_data = {'status': 'error', 'message': 'Bad Shazam Result'}
             # elif not shazam_result and not stop_event.is_set(): # stop_event check removed
             elif not shazam_result:
                  update_data = {'status': 'error', 'message': current_status_message}
             # elif stop_event.is_set(): # stop_event check removed
             #      logger.info("Stop event detected after recognize_song.")
             #      update_data = {'status': 'error', 'message': 'Shutdown'}


        # elif not wav_file_path and not stop_event.is_set(): # stop_event check removed
        elif not wav_file_path:
             logger.warning("Recording failed or produced no file.")
             update_data = {'status': 'error', 'message': current_status_message}
        # elif stop_event.is_set(): # stop_event check removed
        #      logger.info("Stop event detected after record_audio.")
        #      update_data = {'status': 'error', 'message': 'Shutdown'}

    except Exception as e:
         logger.exception(f"Unhandled error in recognition cycle: {e}")
         update_data = {'status': 'error', 'message': 'Cycle Failed Unexpectedly'}
    finally:
        safe_remove(wav_file_path, "temp WAV after cycle")

        # if not stop_event.is_set(): # stop_event check removed
        logger.debug(f"Recognition cycle update data: {update_data}")
        # The data is returned by handle_get_current_song_data, not processed here by set_status_message
        # Global state like last_track_title is updated by process_recognition_result
        # current_status_message is also updated by various functions like record_audio, recognize_song
        # This function will now return the data directly.
        # else:
        #     logger.info("Stop event set, skipping final GUI update for this cycle.")

    # if not stop_event.is_set(): # stop_event check removed
    #      logger.debug(f"Waiting {interval_seconds:.1f}s for next cycle...")
    #      start_wait = asyncio.get_event_loop().time()
    #      while (asyncio.get_event_loop().time() - start_wait) < interval_seconds:
    #          if stop_event.is_set():
    #              logger.info("Wait interrupted by stop event.")
    #              break
    #          try:
    #              await asyncio.sleep(wait_chunk)
    #          except asyncio.CancelledError:
    #              logger.info("Waiting sleep cancelled.")
    #              break
    # else:
    #      logger.info("Stop event set, exiting recognition loop.")

    logger.info("Periodic recognition task finished (On-Demand).")
    return update_data # Return data for on-demand call


# def recognition_loop_runner(stop_event: threading.Event): # Threading removed
#     """Sets up and runs the asyncio event loop for the background thread."""
#     logger.info("Recognition thread starting.")
#     loop = None
#     try:
#         loop = asyncio.new_event_loop()
#         asyncio.set_event_loop(loop)
#         loop.run_until_complete(periodic_recognition_task(stop_event))
#     except Exception as e:
#         logger.exception(f"Exception in recognition thread runner: {e}")
#     finally:
#         if loop and not loop.is_closed():
#              logger.info("Closing asyncio loop in recognition thread.")
#              try:
#                   tasks = asyncio.all_tasks(loop)
#                   if tasks:
#                      logger.debug(f"Cancelling {len(tasks)} outstanding tasks...")
#                      for task in tasks: task.cancel()
#                      loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
#                      logger.debug("Outstanding tasks cancelled.")
#                   logger.debug("Shutting down async generators...")
#                   loop.run_until_complete(loop.shutdown_asyncgens())
#                   logger.debug("Async generators shutdown.")
#              except Exception as cleanup_e:
#                   logger.error(f"Error during asyncio task cleanup: {cleanup_e}")
#              finally:
#                  try:
#                      loop.close()
#                      logger.info("Asyncio loop closed.")
#                  except Exception as close_e:
#                      logger.error(f"Error closing asyncio loop: {close_e}")
#         logger.info("Recognition thread finished.")


# def start_recognition_thread(): # Threading removed
#     """Creates and starts the background thread for song recognition."""
#     global recognition_thread
#     if recognition_thread and recognition_thread.is_alive():
#         logger.warning("Recognition thread already running. Skipping start.")
#         return
#     recognition_thread_stop_event.clear()
#     recognition_thread = threading.Thread(
#         target=recognition_loop_runner,
#         args=(recognition_thread_stop_event,),
#         name="RecognitionThread",
#         daemon=True
#     )
#     recognition_thread.start()
#     logger.info("Recognition thread initiated.")


# --- Main Execution ---
# ... (write_history_separator function remains unchanged) ...
def write_history_separator():
     """ Writes a separator line to the history log file if it exists and is not empty. """
     if SONG_HISTORY_FILE_PATH.is_file() and SONG_HISTORY_FILE_PATH.stat().st_size > 0:
          try:
               with open(SONG_HISTORY_FILE_PATH, 'a', encoding='utf-8') as f:
                    f.write(f"\n--- New Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
               logger.info(f"Wrote session separator to {SONG_HISTORY_FILE_PATH}")
          except IOError as e:
               logger.error(f"Could not write session separator to history log: {e}")
     else:
          logger.debug("History log file doesn't exist or is empty. Skipping separator.")


def main():
    # global root, canvas, config, title_label_id, artist_label_id, status_label_id, coverart_item_id # Tkinter globals
    global config # Keep config

    config = load_config()
    logger.info("--- Song Recognition Application Starting (Python Backend) ---")
    write_history_separator()

    # root = tk.Tk() # Tkinter removed
    # root.title("Song Recognition") # Tkinter removed
    # root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT) # Tkinter removed

    restored = load_last_state()
    if not restored:
         logger.info("Starting with empty state or failed restore.")
         if not IMAGE_PATH.is_file(): # This path needs to be valid
              # Create placeholder in the new DATA_DIR_PATH
              DATA_DIR_PATH.mkdir(parents=True, exist_ok=True)
              create_placeholder_image(IMAGE_PATH, 500, 500, "Play a song!")
         # if current_status_message == "Play a song!": # current_status_message might be updated by load_last_state via set_status_message
         #    set_status_message("Ready") # set_status_message calls schedule_gui_update, which is now a no-op

    # initial_width = 800 # Tkinter removed
    # initial_height = 600 # Tkinter removed
    # start_fullscreen = False # Tkinter removed

    # root.geometry(f"{initial_width}x{initial_height}") # Tkinter removed
    # root.update_idletasks() # Tkinter removed

    # if start_fullscreen: # Tkinter removed
    #     toggle_fullscreen() # Tkinter removed
    #     logger.info(f"Attempting to start fullscreen.") # Tkinter removed
    # else: # Tkinter removed
    #     logger.info(f"Starting windowed: {initial_width}x{initial_height}") # Tkinter removed

    # canvas = tk.Canvas(root, bg="black", highlightthickness=0) # Tkinter removed
    # canvas.pack(fill=tk.BOTH, expand=tk.YES) # Tkinter removed

    # title_label_id = None # Tkinter removed
    # artist_label_id = None # Tkinter removed
    # status_label_id = None # Tkinter removed
    # coverart_item_id = None # Tkinter removed

    # root.bind("<Escape>", toggle_fullscreen) # Tkinter removed
    # root.bind("<Motion>", reset_cursor_hide_timer) # Tkinter removed
    # root.bind("<Configure>", on_resize) # Tkinter removed
    # root.protocol("WM_DELETE_WINDOW", on_closing) # Tkinter removed

    # root.update() # Tkinter removed
    # root.after(100, trigger_full_redraw) # Tkinter removed
    # root.after(100, reset_cursor_hide_timer) # Tkinter removed

    # start_recognition_thread() # Threading removed for on-demand calls

    logger.info("Python backend main() function called. Script is now on-demand via command line arguments.")
    # The main loop `while not recognition_thread_stop_event.is_set()` is removed.
    # The script will exit after handling a command if called with one.

    logger.info("--- Song Recognition Application Exited (Python Backend main()) ---")

# --- Stub Function for Neutralino ---
def get_song_info_stub_command(): # Renamed to avoid clash if we import main
    """
    Handles the 'get_song_info_stub' command.
    Prints a static JSON string to stdout.
    """
    logger.info("get_song_info_stub_command() called.")
    print(json.dumps({"status": "Python backend connected", "version": "0.1-stub"}))

# --- Handler for Actual Song Data ---
def handle_get_current_song_data():
    """
    Handles the 'get_current_song_data' command.
    Performs a recognition cycle and prints song data as JSON to stdout.
    """
    global config, current_status_message, last_track_title, last_artist_name # Ensure globals are accessible

    logger.info("handle_get_current_song_data() called.")
    if not config:
        config = load_config() # Load config if not already loaded

    # Perform a synchronous recognition cycle
    # asyncio.run() is used to execute the async periodic_recognition_task
    try:
        recognition_data = asyncio.run(periodic_recognition_task(None)) # Pass None as stop_event for single run
    except Exception as e:
        logger.exception("Error running recognition task in handle_get_current_song_data")
        recognition_data = {"status": "error", "message": f"Recognition cycle error: {e}"}


    # Prepare data for JSON output
    output_data = {
        "title": last_track_title, # Updated by process_recognition_result via recognition_data
        "artist": last_artist_name, # Updated by process_recognition_result via recognition_data
        "status_message": current_status_message, # Updated by various functions
        "cover_art_base64": None,
        "raw_recognition_data": recognition_data # Include for debugging or richer client UI
    }

    # Update title and artist from the recognition data if successful
    if recognition_data and recognition_data.get('status') == 'success':
        output_data['title'] = recognition_data.get('title', last_track_title)
        output_data['artist'] = recognition_data.get('artist', last_artist_name)
    elif recognition_data and recognition_data.get('message'):
        output_data['status_message'] = recognition_data.get('message')


    # Encode cover art if available
    active_image_path_to_encode = IMAGE_PATH # This is the path updated by process_recognition_result
    if active_image_path_to_encode.is_file():
        try:
            with open(active_image_path_to_encode, "rb") as img_file:
                encoded_string = base64.b64encode(img_file.read()).decode('utf-8')
                output_data["cover_art_base64"] = f"data:image/jpeg;base64,{encoded_string}" # Assuming JPG
            logger.info(f"Encoded cover art from {active_image_path_to_encode}")
        except Exception as e:
            logger.error(f"Error encoding image {active_image_path_to_encode}: {e}")
            output_data["status_message"] = f"{output_data['status_message']} (Cover art encoding error)"
    else:
        logger.info(f"No cover art file found at {active_image_path_to_encode} to encode.")
        # Attempt to provide placeholder if main image is missing
        placeholder_path = APP_DATA_DIR / "placeholder_error.jpg" # Use APP_DATA_DIR
        if not placeholder_path.is_file(): # Create one if it doesn't exist
             create_placeholder_image(placeholder_path, 300,300, "No Image")
        if placeholder_path.is_file():
            try:
                with open(placeholder_path, "rb") as img_file:
                    encoded_string = base64.b64encode(img_file.read()).decode('utf-8')
                    output_data["cover_art_base64"] = f"data:image/jpeg;base64,{encoded_string}"
                logger.info(f"Encoded placeholder cover art from {placeholder_path}")
            except Exception as e:
                logger.error(f"Error encoding placeholder image {placeholder_path}: {e}")


    print(json.dumps(output_data))


if __name__ == "__main__":
    # This function must be called after APP_DATA_DIR is set.
    def _initialize_global_paths():
        global CONFIG_PATH, IMAGE_PATH, TEMP_IMAGE_PATH, HISTORY_IMAGE_DIR_PATH, \
               SONG_HISTORY_FILE_PATH, LAST_STATE_FILE_PATH, LOG_FILE_PATH, APP_DATA_DIR

        if APP_DATA_DIR is None:
            # This case should ideally be handled before calling this,
            # by setting APP_DATA_DIR from args or to a default.
            print(json.dumps({"status": "error", "message": "APP_DATA_DIR not initialized before paths."}))
            sys.exit(1)

        CONFIG_PATH = APP_DATA_DIR / CONFIG_FILENAME
        IMAGE_PATH = APP_DATA_DIR / IMAGE_FILENAME
        TEMP_IMAGE_PATH = APP_DATA_DIR / TEMP_IMAGE_FILENAME
        HISTORY_IMAGE_DIR_PATH = APP_DATA_DIR / HISTORY_IMAGE_DIR_NAME
        SONG_HISTORY_FILE_PATH = APP_DATA_DIR / SONG_HISTORY_FILENAME
        LAST_STATE_FILE_PATH = APP_DATA_DIR / LAST_STATE_FILENAME
        LOG_FILE_PATH = APP_DATA_DIR / LOG_FILENAME

    command_payload_str = None
    if len(sys.argv) > 1:
        command_payload_str = sys.argv[1]

    # Determine APP_DATA_DIR first
    # Must happen before _initialize_global_paths() and load_config() for logging
    app_data_dir_set = False
    if command_payload_str:
        try:
            payload = json.loads(command_payload_str)
            provided_data_path_str = payload.get('dataPath')
            if provided_data_path_str:
                APP_DATA_DIR = Path(provided_data_path_str) / 'SongPiData' # Use a subdirectory
                app_data_dir_set = True
        except json.JSONDecodeError:
            pass # Fall through to default APP_DATA_DIR

    if not app_data_dir_set:
        APP_DATA_DIR = DEFAULT_APP_DATA_PARENT_DIR / DEFAULT_APP_DATA_SUBDIR_NAME

    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Critical error: Could not create APP_DATA_DIR {APP_DATA_DIR}. Error: {e}", file=sys.stderr)
        APP_DATA_DIR = SCRIPT_DIR / "songpi_emergency_data"
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e2:
            print(f"Critical error: Could not create emergency data dir {APP_DATA_DIR}. Error: {e2}", file=sys.stderr)

    _initialize_global_paths()

    # global config # Not needed here; config is already global due to module-level annotation
    if not config:
        config = load_config()

    actual_command = None
    if command_payload_str:
        try:
            payload = json.loads(command_payload_str)
            actual_command = payload.get('command')
        except json.JSONDecodeError:
            actual_command = command_payload_str

    actual_command = str(actual_command).strip() if actual_command else None

    logger.info(f"Received payload string: '{command_payload_str}'")
    logger.info(f"Parsed command: '{actual_command}' (type: {type(actual_command)}), APP_DATA_DIR: {APP_DATA_DIR}")

    expected_command_stub = str("get_song_info_stub").strip()
    expected_command_data = str("handle_get_current_song_data").strip()

    if actual_command == expected_command_stub:
        get_song_info_stub_command()
    elif actual_command == expected_command_data:
        handle_get_current_song_data()
    elif actual_command is None and len(sys.argv) == 1 :
        logger.info("SongPi.py called without specific command. Defaulting to 'handle_get_current_song_data' for testing.")
        handle_get_current_song_data()
    else:
        logger.warning(f"SongPi.py called with unknown command or arguments: {sys.argv}")
        print(json.dumps({"status": "error", "message": f"Unknown command: {actual_command}"}))

# --- END OF FILE shazam.py ---
