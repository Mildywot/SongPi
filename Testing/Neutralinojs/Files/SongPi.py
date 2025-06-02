# --- START OF FILE shazam.py ---

import pyaudio
import wave
import asyncio
import tkinter as tk
from tkinter import font as tkFont
from shazamio import Shazam
import requests
from PIL import Image, ImageTk, ImageFilter, ImageStat, ImageDraw, ImageFont
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

# --- Constants ---
# Get the directory containing this script (shazam.py) -> Files/
SCRIPT_DIR = Path(__file__).parent.resolve()
# Get the parent directory of the script's directory -> SongPi_Root_Folder/
APP_ROOT_DIR = SCRIPT_DIR.parent

CONFIG_FILENAME = 'config.json'
IMAGE_FILENAME = 'image.jpg'
TEMP_IMAGE_FILENAME = 'image_temp.jpg'
HISTORY_IMAGE_DIR = 'history_images'      # Relative name, base is APP_ROOT_DIR
LAST_STATE_FILENAME = 'last_state.json'
SONG_HISTORY_FILENAME = 'song_history.log' # Relative name, base is APP_ROOT_DIR

# Paths relative to the script's location (inside Files/)
CONFIG_PATH = SCRIPT_DIR / CONFIG_FILENAME
IMAGE_PATH = SCRIPT_DIR / IMAGE_FILENAME
TEMP_IMAGE_PATH = SCRIPT_DIR / TEMP_IMAGE_FILENAME # Keep temp file relative to script
LAST_STATE_FILE_PATH = SCRIPT_DIR / LAST_STATE_FILENAME

# Paths relative to the application root (one level up from script)
HISTORY_IMAGE_DIR_PATH = APP_ROOT_DIR / HISTORY_IMAGE_DIR
SONG_HISTORY_FILE_PATH = APP_ROOT_DIR / SONG_HISTORY_FILENAME

MIN_WINDOW_WIDTH = 250
MIN_WINDOW_HEIGHT = 200

# --- Global State ---
config: Dict[str, Any] = {}
root: Optional[tk.Tk] = None
canvas: Optional[tk.Canvas] = None
title_label_id: Optional[int] = None
artist_label_id: Optional[int] = None
status_label_id: Optional[int] = None
coverart_item_id: Optional[int] = None

bg_photo_ref: Optional[ImageTk.PhotoImage] = None
square_photo_ref: Optional[ImageTk.PhotoImage] = None
history_photo_refs: List[Dict[str, Any]] = []

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
    if not logging.getLogger().hasHandlers():
         logging.basicConfig(level=log_level,
                            format=log_cfg.get("format"),
                            datefmt=log_cfg.get("datefmt"),
                            stream=sys.stdout)
         logger.info(f"Logging configured at level {log_level_str}.")
    else:
         logging.getLogger().setLevel(log_level)
         logger.info(f"Logging level possibly updated to {log_level_str}.")


    try:
        # Use the globally defined HISTORY_IMAGE_DIR_PATH
        HISTORY_IMAGE_DIR_PATH.mkdir(parents=True, exist_ok=True)
        logger.info(f"History image directory checked/created: {HISTORY_IMAGE_DIR_PATH}")
    except OSError as e:
        logger.error(f"Could not create history image directory {HISTORY_IMAGE_DIR_PATH}: {e}")

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
    schedule_gui_update(set_status_message, "Listening...")
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
        schedule_gui_update(set_status_message, "Error: Invalid audio format")
        return None

    selected_device_index = dev_index
    if selected_device_index is None or not validate_device_channels(selected_device_index, chans):
        if selected_device_index is not None:
            logger.warning(f"Configured device index {selected_device_index} invalid/insufficient. Auto-selecting.")
        else:
            logger.info("No device index configured. Auto-selecting.")
        selected_device_index = select_input_device(chans)
        if selected_device_index is None:
            schedule_gui_update(set_status_message, "Error: No suitable audio device")
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
                schedule_gui_update(set_status_message, "Shutting down...")
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
                    schedule_gui_update(set_status_message, "Error: Audio input failed")
                    safe_remove(temp_wav_path, "temp WAV on IO read error")
                    return None
            except Exception as e:
                logger.exception(f"Unexpected error reading audio stream: {e}")
                schedule_gui_update(set_status_message, "Error: Audio read failed")
                safe_remove(temp_wav_path, "temp WAV on unexpected read error")
                return None
        logger.info(f"Recording finished ({len(frames)} chunks captured).")
    except OSError as e:
        logger.error(f"OSError opening stream on device {selected_device_index}: {e}")
        schedule_gui_update(set_status_message, f"Error: Cannot open device {selected_device_index}")
        safe_remove(temp_wav_path, "temp WAV on stream open error")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during recording: {e}")
        schedule_gui_update(set_status_message, "Error: Recording failed")
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
            schedule_gui_update(set_status_message, "Error: Could not save audio")
            safe_remove(temp_wav_path, "temp WAV on wave write error")
            return None
        except Exception as e:
             logger.exception(f"Unexpected error writing WAV file: {e}")
             schedule_gui_update(set_status_message, "Error: Saving audio failed")
             safe_remove(temp_wav_path, "temp WAV on unexpected write error")
             return None
        finally:
            if audio_instance_for_size:
                audio_instance_for_size.terminate()

    else:
        if not frames:
            logger.warning("No audio frames captured.")
            schedule_gui_update(set_status_message, "Error: No audio captured")
        safe_remove(temp_wav_path, "temp WAV when no frames recorded")
        return None


# --- Song Recognition ---
# ... (recognize_song function remains unchanged) ...
async def recognize_song(wav_file_path: str) -> Optional[Dict[str, Any]]:
    """Recognizes the song from a WAV file using Shazamio."""
    schedule_gui_update(set_status_message, "Recognizing...")
    shazam = Shazam()
    max_retries = config['network']['retry_count']
    retry_delay = config['network']['retry_delay']
    result = None
    for attempt in range(max_retries):
        if recognition_thread_stop_event.is_set():
            logger.info("Recognition cancelled by shutdown.")
            schedule_gui_update(set_status_message, "Shutting down...")
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
                 schedule_gui_update(set_status_message, f"Retrying ({attempt+2})...")
                 try:
                     await asyncio.sleep(retry_delay)
                 except asyncio.CancelledError:
                     logger.info("Asyncio sleep cancelled during retry.")
                     return None
            else:
                logger.error("Max retry attempts reached for recognition.")
                schedule_gui_update(set_status_message, "Error: Recognition failed")
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
                 schedule_gui_update(set_status_message, "Ready (Restored)")
            else:
                 schedule_gui_update(set_status_message, "Ready (Restored Text Only)")
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
    """Schedules a function to run safely on the main Tkinter thread."""
    if root and root.winfo_exists():
        try:
            root.after(0, func, *args)
        except tk.TclError as e:
             logger.warning(f"TclError scheduling GUI update ({func.__name__}): {e}")
        except RuntimeError as e:
             logger.warning(f"RuntimeError scheduling GUI update ({func.__name__}): {e}")
    else:
        logger.debug(f"Skipped scheduling GUI update ({func.__name__}): root gone or doesn't exist.")

def set_status_message(message: str):
    """ Safely update the global status message and trigger display update """
    global current_status_message
    if message != current_status_message:
         current_status_message = message
         logger.debug(f"Status updated: {message}")
         schedule_gui_update(update_status_display_text)

def update_status_display_text():
    """ Updates ONLY the text of the status label. Must run on Tk thread. """
    if canvas and status_label_id:
        try:
            canvas.itemconfigure(status_label_id, text=current_status_message)
            canvas.tag_raise(status_label_id)
        except tk.TclError:
             pass

def update_images() -> Dict[str, Any]:
    """ Redraws main elements (BG, Cover Art, Text), returns layout info. """
    global bg_photo_ref, square_photo_ref, coverart_item_id, title_label_id, artist_label_id, status_label_id

    layout_info = {'window_width': 0, 'window_height': 0, 'square_size': 0,
                   'square_x': 0, 'square_y': 0, 'title_y': 0, 'artist_y': 0, 'status_y': 0,
                   'main_font_size': 10, 'status_font_size': 8, 'history_font_size': 7,
                   'text_color': 'white', 'is_fullscreen': False} # Add default for is_fullscreen

    is_fullscreen = False
    if not root or not canvas or not root.winfo_exists():
        logger.warning("update_images: GUI not ready.")
        return layout_info

    # Get dimensions and state
    try:
        window_width = root.winfo_width()
        window_height = root.winfo_height()
        is_fullscreen = root.attributes("-fullscreen")
        logger.debug(f"Window dims: {window_width}x{window_height}, Fullscreen: {is_fullscreen}")
        if window_width < 1 or window_height < 1:
            logger.warning(f"Window dimensions too small ({window_width}x{window_height}). Using minimums.")
            window_width = max(MIN_WINDOW_WIDTH, window_width)
            window_height = max(MIN_WINDOW_HEIGHT, window_height)
    except tk.TclError:
        logger.warning("update_images: Error getting window dimensions or attributes.")
        return layout_info

    layout_info.update({'window_width': window_width, 'window_height': window_height, 'is_fullscreen': is_fullscreen}) # Store fullscreen state
    image_file_path = IMAGE_PATH
    gui_cfg = config['gui'] # Get GUI config section

    # --- Background ---
    brightness = 0.5
    try:
        if image_file_path.is_file():
            blurred_pil_image = create_blurred_background(
                image_file_path, window_width, window_height, gui_cfg['blur_strength']
            )
            if blurred_pil_image:
                brightness = calculate_brightness(blurred_pil_image)
                bg_photo_ref = ImageTk.PhotoImage(blurred_pil_image)
                canvas.delete("background")
                canvas.create_image(0, 0, anchor=tk.NW, image=bg_photo_ref, tags=("background",))
                canvas.tag_lower("background")
                logger.debug("Background image updated and lowered.")
            else:
                logger.warning("Failed to create blurred background image.")
                canvas.delete("background")
                bg_photo_ref = None
        else:
             logger.warning(f"Main image {image_file_path} not found for background.")
             canvas.delete("background")
             bg_photo_ref = None
             canvas.config(bg="black")
    except Exception as e:
        logger.exception(f"Error processing or setting background image: {e}")
        canvas.delete("background")
        bg_photo_ref = None
        canvas.config(bg="black")

    layout_info['text_color'] = "black" if brightness > 0.55 else "white"

    # --- Main Square Cover Art ---
    # Calculate square size first
    border_ratio = gui_cfg['border_size_ratio']
    border_px = int(min(window_width, window_height) * border_ratio)
    square_size = max(MIN_WINDOW_WIDTH * 0.2, min(window_width, window_height) - 2 * border_px)
    layout_info['square_size'] = square_size

    square_x = window_width // 2 # Always center horizontally

    # Adjust vertical position based on aspect ratio
    if window_height > window_width: # Portrait or tall window
        target_square_y = int(window_height * 0.35) # Target center higher up (35%)
        logger.debug("Portrait aspect ratio detected, targeting higher position.")
    else: # Landscape or square window
        target_square_y = int(window_height * 0.46) # Default slightly-above-center
        logger.debug("Landscape/Square aspect ratio detected, using standard positioning.")

    # Ensure minimum top padding
    min_top_padding = gui_cfg.get('history_y_offset', 20)
    min_allowed_square_y = min_top_padding + (square_size / 2)
    square_y = max(target_square_y, int(min_allowed_square_y))
    logger.debug(f"Target Y: {target_square_y}, Min Allowed Y: {min_allowed_square_y:.0f}, Final Y: {square_y}")

    # Now draw the image at the calculated position
    if image_file_path.is_file():
        try:
            with Image.open(image_file_path) as img_reopened:
                square_pil_image = img_reopened.resize((int(square_size), int(square_size)), Image.Resampling.LANCZOS)
                square_photo_ref = ImageTk.PhotoImage(square_pil_image)
                layout_info.update({'square_x': square_x, 'square_y': square_y}) # Store final calculated values

                if coverart_item_id:
                    canvas.itemconfig(coverart_item_id, image=square_photo_ref)
                    canvas.coords(coverart_item_id, square_x, square_y)
                else:
                    coverart_item_id = canvas.create_image(square_x, square_y, anchor=tk.CENTER, image=square_photo_ref, tags=("coverart",))

                canvas.tag_raise(coverart_item_id)
                logger.debug("Cover art updated.")
        except FileNotFoundError:
            logger.error(f"Image disappeared between check and open: {image_file_path}")
            if coverart_item_id: canvas.delete(coverart_item_id); coverart_item_id = None
            square_photo_ref = None
        except Exception as e:
            logger.exception(f"Error loading/processing main cover art image {image_file_path}: {e}")
            if coverart_item_id: canvas.delete(coverart_item_id); coverart_item_id = None
            square_photo_ref = None
    else:
         if coverart_item_id: canvas.delete(coverart_item_id); coverart_item_id = None
         square_photo_ref = None
         logger.debug("No main image file, cover art not displayed.")
         # square_size was already estimated above

    # --- Text Labels ---
    base_font_size = gui_cfg['base_font_size']
    scale_factor = 0.045
    upper_clamp = 32
    min_clamp = 8
    main_font_size = max(min_clamp, min(upper_clamp, int(square_size * scale_factor * (base_font_size / 10)))) if square_size > 0 else min_clamp + 2
    if not is_fullscreen and main_font_size > min_clamp + 1:
        main_font_size = max(min_clamp, main_font_size - 1)
        logger.debug(f"Windowed mode: Adjusted main font size down to {main_font_size}")
    status_font_ratio = gui_cfg['status_font_size_ratio']
    status_font_size = max(5, min(30, int(main_font_size * status_font_ratio * 0.5)))
    history_font_size = max(6, min(20, int(main_font_size * gui_cfg['history_font_size_ratio'])))
    logger.debug(f"Final Font sizes: Main={main_font_size}, Status={status_font_size}, History={history_font_size} (Square Size={square_size:.0f})")
    layout_info.update({'main_font_size': main_font_size, 'status_font_size': status_font_size, 'history_font_size': history_font_size})

    try:
        title_font_obj = tkFont.Font(family="Arial", size=main_font_size, slant="italic")
        artist_font_obj = tkFont.Font(family="Arial", size=main_font_size, weight="bold")
        status_font_obj = tkFont.Font(family="Arial", size=status_font_size)
        title_line_height = title_font_obj.metrics("linespace")
        artist_line_height = artist_font_obj.metrics("linespace")
        status_line_height = status_font_obj.metrics("linespace")
    except tk.TclError:
         logger.warning("tkFont.Font creation failed. Using tuple definitions.")
         title_font_obj = ("Arial", main_font_size, "italic")
         artist_font_obj = ("Arial", main_font_size, "bold")
         status_font_obj = ("Arial", status_font_size)
         title_line_height = main_font_size * 1.3
         artist_line_height = main_font_size * 1.3
         status_line_height = status_font_size * 1.3

    # Calculate text positions relative to the *final* calculated square_y
    base_y = square_y + square_size / 2
    title_y = base_y + title_line_height * 0.8
    artist_y = title_y + artist_line_height * 0.9
    status_y = artist_y + status_line_height * 2.0

    # Clamp status_y to prevent going off-screen bottom
    status_y = min(status_y, window_height - (status_line_height * 1.5))
    status_y = max(status_y, artist_y + status_line_height * 0.8) # Prevent overlap with artist

    layout_info.update({'title_y': title_y, 'artist_y': artist_y, 'status_y': status_y}) # Store the final status_y

    text_color = layout_info['text_color']
    item_config_options = {'fill': text_color, 'anchor': tk.CENTER}

    # --- Create / Update Text Items ---
    try:
        if title_label_id:
            canvas.coords(title_label_id, window_width // 2, title_y)
            canvas.itemconfigure(title_label_id, text=last_track_title, font=title_font_obj, fill=text_color)
        else:
            title_label_id = canvas.create_text(window_width // 2, title_y, text=last_track_title, font=title_font_obj, tags=("main_text",), **item_config_options)

        if artist_label_id:
            canvas.coords(artist_label_id, window_width // 2, artist_y)
            canvas.itemconfigure(artist_label_id, text=last_artist_name, font=artist_font_obj, fill=text_color)
        else:
            artist_label_id = canvas.create_text(window_width // 2, artist_y, text=last_artist_name, font=artist_font_obj, tags=("main_text",), **item_config_options)

        if status_label_id:
            canvas.coords(status_label_id, window_width // 2, status_y)
            canvas.itemconfigure(status_label_id, text=current_status_message, font=status_font_obj, fill=text_color)
        else:
            status_label_id = canvas.create_text(window_width // 2, status_y, text=current_status_message, font=status_font_obj, tags=("main_text",), **item_config_options)

        canvas.tag_raise("main_text")

    except tk.TclError as e:
         logger.warning(f"TclError updating text labels: {e}. IDs reset.")
         title_label_id = artist_label_id = status_label_id = None

    logger.debug("Main images and text updated.")
    return layout_info


def redraw_history_display(layout_info: Dict[str, Any]):
    """Redraws the song history panel based on available space and layout mode."""
    global history_photo_refs
    if not canvas or not root or not root.winfo_exists():
        logger.debug("redraw_history_display: Canvas or root not ready.")
        return

    logger.info("--- Redrawing History Display ---")
    canvas.delete("history_item")
    history_photo_refs.clear()

    if len(song_history_list) < 2:
        logger.info("Not enough history items (need >= 2) to display previous songs.")
        logger.info("--- History Redraw End (Not Enough Items) ---")
        return

    logger.info(f"Total songs in memory: {len(song_history_list)}. Attempting to display previous songs.")

    gui_cfg = config['gui']
    max_items = gui_cfg['history_max_items']
    art_size_config = gui_cfg['history_art_size'] # Original size from config
    padding = gui_cfg['history_item_padding']
    x_offset = gui_cfg['history_x_offset']
    y_offset = gui_cfg['history_y_offset']
    min_side_width_config = gui_cfg['history_min_side_width']
    side_buffer = gui_cfg['layout_side_min_buffer']
    below_buffer = gui_cfg['layout_below_min_buffer']
    win_w = layout_info['window_width']
    win_h = layout_info['window_height']
    sq_x = layout_info['square_x']
    sq_y = layout_info['square_y']
    sq_size = layout_info['square_size']
    history_font_size = layout_info['history_font_size']
    text_color = layout_info['text_color']
    is_fullscreen = layout_info.get('is_fullscreen', False)

    # Reduce History Font Size
    history_font_size_actual = max(5, history_font_size - 1)
    logger.debug(f"Base history font size: {history_font_size}, Actual used: {history_font_size_actual}")

    try:
        history_font_italic = tkFont.Font(family="Arial", size=history_font_size_actual, slant="italic")
        history_font_bold = tkFont.Font(family="Arial", size=history_font_size_actual, weight="bold")
        history_line_height = history_font_bold.metrics("linespace")
        # Height estimate for layout based on ~3 lines text (for spacing between items)
        text_block_height_for_spacing = (history_line_height * 2.8) + 4
    except tk.TclError:
        logger.warning("tkFont failed for history fonts.")
        history_font_italic = ("Arial", history_font_size_actual, "italic")
        history_font_bold = ("Arial", history_font_size_actual, "bold")
        history_line_height = history_font_size_actual * 1.3
        text_block_height_for_spacing = (history_line_height * 2.8) + 4

    # --- Determine Art Size and Entry Height ---
    current_art_size = art_size_config # Start with config size
    # Check conditions for Left mode *before* deciding final art size
    temp_available_width_left = max(0, (sq_x - sq_size // 2) - x_offset - side_buffer)
    temp_available_height_side = max(0, win_h - 2 * y_offset)
    temp_history_entry_height = max(art_size_config, text_block_height_for_spacing) + padding
    is_potentially_left_mode = (temp_available_width_left >= min_side_width_config and
                               temp_available_height_side >= temp_history_entry_height)

    if is_potentially_left_mode and is_fullscreen:
        current_art_size = int(text_block_height_for_spacing) # Use ~3 lines height
        logger.info(f"Fullscreen Left mode: Adjusting history art size to text height: {current_art_size}")
    else:
        logger.info(f"Not Fullscreen Left mode or Below Mode: Using config history art size: {current_art_size}")

    # Final entry height used for layout checks and vertical spacing between items
    history_entry_height = max(current_art_size, text_block_height_for_spacing) + padding
    logger.debug(f"Final History Entry Height for layout/spacing: {history_entry_height:.0f} (using art_size={current_art_size})")


    # --- Determine Layout Mode ---
    layout_mode: Literal["Hidden", "Left", "Below"] = "Hidden"
    available_width_left = max(0, (sq_x - sq_size // 2) - x_offset - side_buffer)
    available_height_side = max(0, win_h - 2 * y_offset)
    status_text_y = layout_info.get('status_y', win_h)
    available_height_below = max(0, win_h - status_text_y - (below_buffer * 2.0)) # Keep increased buffer

    logger.info(f"[Layout Check] Window: {win_w}x{win_h}, Square @({sq_x},{sq_y}) Size:{sq_size:.0f}, StatusY:{status_text_y:.0f}")
    logger.info(f"[Layout Check] Config: MinSideW={min_side_width_config}, EntryH={history_entry_height:.0f}, ArtSize={current_art_size}, TxtBlkH_Layout={text_block_height_for_spacing:.0f}")
    logger.info(f"[Layout Check] Available: W_Left={available_width_left:.0f}, H_Side={available_height_side:.0f}, H_Below={available_height_below:.0f}")

    # Check fit using the final calculated history_entry_height
    can_fit_vertically_side = available_height_side >= history_entry_height
    can_fit_vertically_below = available_height_below >= history_entry_height

    if available_width_left >= min_side_width_config and can_fit_vertically_side:
        layout_mode = "Left"
        logger.info(f"[Layout Decision] Mode set to 'Left' (W_Left >= MinSideW AND H_Side >= EntryH)")
    elif can_fit_vertically_below:
        layout_mode = "Below"
        logger.info(f"[Layout Decision] Mode set to 'Below' (H_Below >= EntryH)")
    else:
        layout_mode = "Hidden"
        logger.info(f"[Layout Decision] Mode set to 'Hidden' (Insufficient space)")

    if layout_mode == "Hidden":
        logger.info("--- History Redraw End (Hidden) ---")
        return

    # --- Prepare for Drawing ---
    items_to_draw = song_history_list[1 : max_items + 1]
    num_items_actually_drawing = 0
    initial_y_pos = y_offset
    estimated_max_text_width = max(150, min(win_w * 0.6, 500))

    # Calculate Vertical Centering / Max Items Fit for Left Mode
    if layout_mode == "Left":
        max_items_fit_height = int(available_height_side // history_entry_height) if history_entry_height > 0 else 0
        num_items_to_draw_actual = min(len(items_to_draw), max_items_fit_height)
        if num_items_to_draw_actual > 0:
            total_list_height = (history_entry_height * num_items_to_draw_actual) - padding
            available_draw_height = win_h - 2 * y_offset
            initial_y_pos = max(y_offset, (available_draw_height - total_list_height) // 2 + y_offset)
            logger.debug(f"Left Mode Centering: MaxFit={max_items_fit_height}, DrawActual={num_items_to_draw_actual}, ListH={total_list_height:.0f}, AvailH={available_draw_height:.0f}, StartY={initial_y_pos:.0f}")
        else:
            logger.warning("Left Mode: Calculated 0 items fit vertically.")
            layout_mode = "Hidden"

    # Calculate Max Items Fit for Below Mode
    elif layout_mode == "Below":
        max_items_fit_height = int(available_height_below // history_entry_height) if history_entry_height > 0 else 0
        num_items_to_draw_actual = min(len(items_to_draw), max_items_fit_height)
        initial_y_pos = status_text_y + (below_buffer * 2.0)
        if num_items_to_draw_actual <= 0:
             logger.warning("Below Mode: Calculated 0 items fit vertically.")
             layout_mode = "Hidden"

    if layout_mode == "Hidden":
        logger.info("--- History Redraw End (Hidden after fit check) ---")
        return

    # --- Draw History Items ---
    y_pos = initial_y_pos
    items_to_draw_fitting = items_to_draw[:num_items_to_draw_actual]
    logger.info(f"Attempting to draw {len(items_to_draw_fitting)} items in '{layout_mode}' mode...")


    for i, item in enumerate(items_to_draw_fitting):
        logger.debug(f"Processing history item index {i} (Overall index {i+1}): Title='{item.get('title')}'")
        img_path_str = item.get('image_path')
        canvas_img_id = None
        photo_ref = None
        canvas_title_id = None
        canvas_artist_id = None

        # --- Calculate Positions for this item ---
        img_y = y_pos # Top of the current item slot starts at current y_pos
        img_anchor = tk.NW
        text_anchor = tk.NW
        text_justify = tk.LEFT

        # Calculate starting X and wrap width based on mode
        if layout_mode == "Left":
            img_x = x_offset
            text_x = x_offset + current_art_size + 10
            text_wrap_width = max(10, available_width_left - (current_art_size + 10))
        elif layout_mode == "Below":
             item_text_width = estimated_max_text_width
             item_block_width = current_art_size + 10 + item_text_width
             item_block_start_x = max(x_offset, (win_w - item_block_width) // 2)
             img_x = item_block_start_x
             text_x = img_x + current_art_size + 10
             text_wrap_width = max(10, item_text_width)

        # Position title top aligned with image top
        title_y = y_pos

        # Estimate if title will wrap to adjust artist_y
        title_text = item.get('title', 'Unknown Title')
        try:
            estimated_title_width = history_font_italic.measure(title_text)
            title_likely_wrapped = estimated_title_width > text_wrap_width
        except tk.TclError:
            title_likely_wrapped = len(title_text) * history_font_size_actual * 0.6 > text_wrap_width
            logger.warning("tkFont.measure failed, using rough estimate for wrapping.")

        logger.debug(f"  Item index {i}: Estimated title width={estimated_title_width}, Wrap width={text_wrap_width:.0f}, Wrapped={title_likely_wrapped}")

        if title_likely_wrapped:
            # If title wraps, start artist text ~2 lines below title's start
            artist_y = title_y + (history_line_height * 1.9)
        else:
            # If title doesn't wrap, start artist text 1 line below title's start
            artist_y = title_y + history_line_height

        # Use the consistent entry height for vertical spacing to next item
        next_y_increment = history_entry_height

        logger.debug(f"  Item index {i} ({layout_mode}): Final Coords Img=({img_x:.0f},{img_y:.0f}, Size:{current_art_size}) Title=({text_x:.0f},{title_y:.0f}) Artist=({text_x:.0f},{artist_y:.0f})")

        # --- Create Image ---
        if img_path_str:
            img_path = Path(img_path_str)
            if img_path.is_file():
                try:
                    with Image.open(img_path) as img:
                        img = img.resize((current_art_size, current_art_size), Image.Resampling.LANCZOS) # Use potentially adjusted size
                        photo_ref = ImageTk.PhotoImage(img)
                        canvas_img_id = canvas.create_image(img_x, img_y,
                                                            anchor=img_anchor, image=photo_ref,
                                                            tags=("history_item", "history_image"))
                        logger.debug(f"  Item index {i} image created ID: {canvas_img_id}")
                except Exception as e:
                    logger.exception(f"  ERROR loading/drawing history image {img_path} for item index {i}: {e}")
                    photo_ref = None
            else:
                logger.warning(f"  History image file missing for item index {i}: {img_path}")
        else:
            logger.warning(f"  History item index {i} missing image path.")

        # --- Create Title Text (with wrapping) ---
        # title_text already retrieved
        try:
            canvas_title_id = canvas.create_text(text_x, title_y, text=title_text,
                                           anchor=text_anchor, justify=text_justify,
                                           font=history_font_italic, fill=text_color,
                                           width=text_wrap_width,
                                           tags=("history_item", "history_text", "history_title"))
            logger.debug(f"  Item index {i} title text created ID: {canvas_title_id}")
        except Exception as e:
             logger.exception(f"  ERROR creating history title text for item index {i}: {e}")

        # --- Create Artist Text (with wrapping) ---
        artist_text = item.get('artist', 'Unknown Artist')
        try:
            canvas_artist_id = canvas.create_text(text_x, artist_y, text=artist_text, # Use calculated artist_y
                                           anchor=text_anchor, justify=text_justify,
                                           font=history_font_bold, fill=text_color,
                                           width=text_wrap_width,
                                           tags=("history_item", "history_text", "history_artist"))
            logger.debug(f"  Item index {i} artist text created ID: {canvas_artist_id}")
        except Exception as e:
             logger.exception(f"  ERROR creating history artist text for item index {i}: {e}")


        history_photo_refs.append({
            'image_ref': photo_ref,
            'canvas_img_id': canvas_img_id,
            'canvas_title_id': canvas_title_id,
            'canvas_artist_id': canvas_artist_id
            })

        # Raise items within the loop
        if canvas_img_id: canvas.tag_raise(canvas_img_id)
        if canvas_title_id: canvas.tag_raise(canvas_title_id)
        if canvas_artist_id: canvas.tag_raise(canvas_artist_id)

        # Increment y_pos for the next item block
        y_pos += next_y_increment


    # --- Final Layering ---
    canvas.tag_lower("background")
    canvas.tag_raise("history_item")
    if coverart_item_id:
        canvas.tag_raise(coverart_item_id)
    canvas.tag_raise("main_text")

    logger.info(f"History display attempted draw of {len(history_photo_refs)} items in '{layout_mode}' mode. Layering adjusted.")
    logger.info("--- History Redraw End ---")


# ... (update_gui, trigger_full_redraw, Event Handlers, Async Task Runner, Main Execution functions remain unchanged) ...
def update_gui(update_data: Dict[str, Any]):
    """ Updates GUI based on processed data from background thread. Runs on main thread. """
    global last_track_title, last_artist_name, last_persistent_image_path
    status = update_data.get('status')
    title = update_data.get('title')
    artist = update_data.get('artist')
    persistent_path = update_data.get('persistent_path')
    image_updated = update_data.get('image_updated', False)
    error_message = update_data.get('message')

    redraw_needed = False
    status_to_set = current_status_message

    logger.debug(f"GUI Update Received: Status='{status}', Title='{title}', Artist='{artist}', ImgUpd={image_updated}, ErrMsg='{error_message}'")

    if status == 'success':
        is_new_song_text = (title != last_track_title or artist != last_artist_name)

        if is_new_song_text:
            logger.info(f"GUI update: New song '{title}' by {artist}.")
            last_track_title = title
            last_artist_name = artist
            last_persistent_image_path = persistent_path
            status_to_set = "Ready"
            redraw_needed = True
            if not image_updated and error_message and error_message != "Used Cache":
                 logger.warning(f"New song text displayed, but image update failed: {error_message}. Showing previous/placeholder image.")
                 status_to_set = f"Ready (Image Error: {error_message})"
            elif error_message == "Used Cache":
                status_to_set = "Ready (Used Cache)"


        else:
            logger.info("GUI update: Same song recognized.")
            status_to_set = "Ready (Same Song)"
            if image_updated and error_message != "Used Cache":
                logger.info("Image refreshed for the same song.")
                last_persistent_image_path = persistent_path
                redraw_needed = True
                status_to_set = "Ready (Image Refreshed)"
            elif error_message == "Used Cache":
                status_to_set = "Ready (Used Cache)"


    elif status == 'no_match':
        logger.info("GUI update: No match found.")
        status_to_set = "No Match Found"

    elif status == 'error':
        logger.error(f"GUI update: Received error status. Message: '{error_message}'")
        status_to_set = error_message or "Error: Unknown"

    else:
         logger.warning(f"GUI update: Received unknown status '{status}'")
         status_to_set = "Error: Internal State"

    set_status_message(status_to_set)

    if redraw_needed:
        logger.debug("Scheduling full redraw due to state change.")
        schedule_gui_update(trigger_full_redraw)


def trigger_full_redraw():
     """ Safely calls functions to redraw all main GUI elements. Must run on Tk thread. """
     if not root or not canvas or not root.winfo_exists():
          logger.debug("Skip redraw: GUI not ready.")
          return
     logger.debug("Triggering full redraw...")
     try:
         layout_info = update_images()
         redraw_history_display(layout_info)
         logger.debug("Full redraw complete.")
     except tk.TclError as e:
         logger.error(f"TclError during full redraw: {e}")
     except Exception as e:
         logger.exception(f"Unexpected error during full redraw: {e}")

def get_monitor_for_window() -> Optional[Any]:
    """Finds the screeninfo monitor object the window is currently on."""
    if not root or not root.winfo_exists(): return None
    try:
        root.update_idletasks()
        window_x = root.winfo_rootx()
        window_y = root.winfo_rooty()
        window_w = root.winfo_width()
        window_h = root.winfo_height()

        monitors = get_monitors()
        logger.debug(f"Win pos: ({window_x}, {window_y}), size: ({window_w}x{window_h}). Checking {len(monitors)} monitors.")

        best_match = None
        max_overlap = 0

        for i, monitor in enumerate(monitors):
            logger.debug(f"  Mon {i}: X={monitor.x},Y={monitor.y},W={monitor.width},H={monitor.height}")
            overlap_x1 = max(window_x, monitor.x)
            overlap_y1 = max(window_y, monitor.y)
            overlap_x2 = min(window_x + window_w, monitor.x + monitor.width)
            overlap_y2 = min(window_y + window_h, monitor.y + monitor.height)
            overlap_width = max(0, overlap_x2 - overlap_x1)
            overlap_height = max(0, overlap_y2 - overlap_y1)
            overlap_area = overlap_width * overlap_height

            if overlap_area > max_overlap:
                max_overlap = overlap_area
                best_match = monitor
                logger.debug(f"    Overlap found: {overlap_area}px^2 (New best match)")

        if best_match:
            logger.debug(f"Window has maximum overlap with monitor: {best_match}")
            return best_match
        elif monitors:
            logger.warning("Could not determine monitor based on overlap. Falling back to primary monitor.")
            return monitors[0]
        else:
            logger.error("screeninfo returned no monitors.")
            return None

    except tk.TclError as e:
        logger.warning(f"TclError getting window info for monitor check: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error getting monitor info: {e}")
        try:
            monitors = get_monitors()
            return monitors[0] if monitors else None
        except:
            return None


def toggle_fullscreen(event=None):
    """Toggles borderless fullscreen mode for the current monitor."""
    if not root or not root.winfo_exists(): return
    is_fullscreen = root.attributes("-fullscreen")
    logger.info(f"Toggling fullscreen: {'Disabling' if is_fullscreen else 'Enabling'}")

    if is_fullscreen:
        root.attributes("-fullscreen", False)
    else:
        monitor = get_monitor_for_window()
        if monitor:
            logger.debug(f"Setting fullscreen geometry for monitor: {monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")
            root.geometry(f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")
            root.attributes("-fullscreen", True)
        else:
             logger.warning("No monitor found for fullscreen toggle. Using default fullscreen.")
             root.attributes("-fullscreen", True)

    schedule_gui_update(lambda: root.after(150, trigger_full_redraw))

def hide_cursor():
    """Hides the mouse cursor."""
    if root and root.winfo_exists():
        try:
            root.config(cursor="none")
        except tk.TclError: pass

def show_cursor():
    """Shows the mouse cursor."""
    if root and root.winfo_exists():
        try:
            root.config(cursor="")
        except tk.TclError: pass

def reset_cursor_hide_timer(event=None):
    """Resets the timer to hide the cursor after inactivity."""
    global cursor_hide_timer_id
    if not root or not root.winfo_exists(): return

    if cursor_hide_timer_id:
        try:
            root.after_cancel(cursor_hide_timer_id)
        except ValueError: pass
        cursor_hide_timer_id = None

    show_cursor()
    try:
        cursor_hide_timer_id = root.after(5000, hide_cursor)
    except tk.TclError: pass

def on_resize(event=None):
    """Handles window resize events with debouncing."""
    global resize_job_id
    if not root or not root.winfo_exists(): return

    if event and hasattr(event, 'widget') and event.widget != root:
         return

    if resize_job_id:
        try:
            root.after_cancel(resize_job_id)
        except ValueError: pass
        resize_job_id = None

    try:
        resize_job_id = root.after(300, trigger_full_redraw)
    except tk.TclError: pass

def on_closing():
    """Handles the window closing event for graceful shutdown."""
    global recognition_thread, recognition_thread_stop_event, root
    logger.info("Shutdown requested via window close.")

    set_status_message("Shutting down...")

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

    safe_remove(TEMP_IMAGE_PATH, "temp image on closing")

    if root:
        logger.info("Destroying Tkinter window.")
        try:
             root.after_idle(root.destroy)
        except tk.TclError as e:
             logger.warning(f"TclError during root.destroy(): {e}")
        root = None

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


async def periodic_recognition_task(stop_event: threading.Event):
    """The main async loop: record -> recognize -> process -> schedule update -> wait."""
    interval_seconds = config['gui']['update_interval_ms'] / 1000.0
    wait_chunk = 0.1

    while not stop_event.is_set():
        logger.info("--- Starting New Recognition Cycle ---")
        update_data = {'status': 'error', 'message': 'Cycle Interrupted'}
        wav_file_path = None
        try:
            wav_file_path = record_audio()

            if wav_file_path and not stop_event.is_set():
                 shazam_result = await recognize_song(wav_file_path)

                 if shazam_result and not stop_event.is_set():
                      if 'track' in shazam_result and shazam_result.get('track'):
                           update_data = await process_recognition_result(shazam_result)
                      elif 'matches' in shazam_result and not shazam_result.get('matches'):
                           update_data = {'status': 'no_match', 'message': 'No Match Found'}
                      else:
                           logger.error(f"Unexpected Shazam result format or empty track: {shazam_result}")
                           update_data = {'status': 'error', 'message': 'Bad Shazam Result'}
                 elif not shazam_result and not stop_event.is_set():
                      update_data = {'status': 'error', 'message': current_status_message}
                 elif stop_event.is_set():
                      logger.info("Stop event detected after recognize_song.")
                      update_data = {'status': 'error', 'message': 'Shutdown'}


            elif not wav_file_path and not stop_event.is_set():
                 logger.warning("Recording failed or produced no file.")
                 update_data = {'status': 'error', 'message': current_status_message}
            elif stop_event.is_set():
                 logger.info("Stop event detected after record_audio.")
                 update_data = {'status': 'error', 'message': 'Shutdown'}

        except Exception as e:
             logger.exception(f"Unhandled error in recognition cycle: {e}")
             update_data = {'status': 'error', 'message': 'Cycle Failed Unexpectedly'}
        finally:
            safe_remove(wav_file_path, "temp WAV after cycle")

            if not stop_event.is_set():
                logger.debug(f"Scheduling GUI update with data: {update_data}")
                schedule_gui_update(update_gui, update_data)
            else:
                logger.info("Stop event set, skipping final GUI update for this cycle.")

        if not stop_event.is_set():
             logger.debug(f"Waiting {interval_seconds:.1f}s for next cycle...")
             start_wait = asyncio.get_event_loop().time()
             while (asyncio.get_event_loop().time() - start_wait) < interval_seconds:
                 if stop_event.is_set():
                     logger.info("Wait interrupted by stop event.")
                     break
                 try:
                     await asyncio.sleep(wait_chunk)
                 except asyncio.CancelledError:
                     logger.info("Waiting sleep cancelled.")
                     break
        else:
             logger.info("Stop event set, exiting recognition loop.")

    logger.info("Periodic recognition task finished.")


def recognition_loop_runner(stop_event: threading.Event):
    """Sets up and runs the asyncio event loop for the background thread."""
    logger.info("Recognition thread starting.")
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(periodic_recognition_task(stop_event))
    except Exception as e:
        logger.exception(f"Exception in recognition thread runner: {e}")
    finally:
        if loop and not loop.is_closed():
             logger.info("Closing asyncio loop in recognition thread.")
             try:
                  tasks = asyncio.all_tasks(loop)
                  if tasks:
                     logger.debug(f"Cancelling {len(tasks)} outstanding tasks...")
                     for task in tasks: task.cancel()
                     loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                     logger.debug("Outstanding tasks cancelled.")
                  logger.debug("Shutting down async generators...")
                  loop.run_until_complete(loop.shutdown_asyncgens())
                  logger.debug("Async generators shutdown.")
             except Exception as cleanup_e:
                  logger.error(f"Error during asyncio task cleanup: {cleanup_e}")
             finally:
                 try:
                     loop.close()
                     logger.info("Asyncio loop closed.")
                 except Exception as close_e:
                     logger.error(f"Error closing asyncio loop: {close_e}")
        logger.info("Recognition thread finished.")


def start_recognition_thread():
    """Creates and starts the background thread for song recognition."""
    global recognition_thread
    if recognition_thread and recognition_thread.is_alive():
        logger.warning("Recognition thread already running. Skipping start.")
        return
    recognition_thread_stop_event.clear()
    recognition_thread = threading.Thread(
        target=recognition_loop_runner,
        args=(recognition_thread_stop_event,),
        name="RecognitionThread",
        daemon=True
    )
    recognition_thread.start()
    logger.info("Recognition thread initiated.")


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
    global root, canvas, config, title_label_id, artist_label_id, status_label_id, coverart_item_id

    config = load_config()
    logger.info("--- Song Recognition Application Starting ---")
    write_history_separator()

    root = tk.Tk()
    root.title("Song Recognition")
    root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

    restored = load_last_state()
    if not restored:
         logger.info("Starting with empty state or failed restore.")
         if not IMAGE_PATH.is_file():
              create_placeholder_image(IMAGE_PATH, 500, 500, "Play a song!")
         if current_status_message == "Play a song!":
             set_status_message("Ready")

    initial_width = 800
    initial_height = 600
    start_fullscreen = False

    root.geometry(f"{initial_width}x{initial_height}")
    root.update_idletasks()

    if start_fullscreen:
        toggle_fullscreen()
        logger.info(f"Attempting to start fullscreen.")
    else:
        logger.info(f"Starting windowed: {initial_width}x{initial_height}")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=tk.YES)

    title_label_id = None
    artist_label_id = None
    status_label_id = None
    coverart_item_id = None

    root.bind("<Escape>", toggle_fullscreen)
    root.bind("<Motion>", reset_cursor_hide_timer)
    root.bind("<Configure>", on_resize)
    root.protocol("WM_DELETE_WINDOW", on_closing)

    root.update()
    root.after(100, trigger_full_redraw)
    root.after(100, reset_cursor_hide_timer)

    start_recognition_thread()

    logger.info("Starting Tkinter main loop.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected. Initiating shutdown.")
        on_closing()
    except Exception as e:
         logger.exception("Unhandled exception in Tkinter main loop.")
         on_closing()

    logger.info("--- Song Recognition Application Exited ---")

if __name__ == "__main__":
    main()
# --- END OF FILE shazam.py ---
