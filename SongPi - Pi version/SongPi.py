import pyaudio
import wave
import asyncio
import tkinter as tk
from shazamio import Shazam
import requests
from PIL import Image, ImageTk, ImageFilter, ImageStat
import io
import os
import json
from screeninfo import get_monitors
import threading

# Set environment variable for ALSA
os.environ['PA_ALSA_PLUGHW'] = '1'

# Load configuration from a JSON file
def load_config():
    dir_path = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(dir_path, 'config.json')
    with open(config_path, 'r') as config_file:
        return json.load(config_file)

config = load_config()

def list_audio_devices():
    audio = pyaudio.PyAudio()
    info = audio.get_host_api_info_by_index(0)
    num_devices = info.get('deviceCount')
    devices = []
    for i in range(num_devices):
        device_info = audio.get_device_info_by_host_api_device_index(0, i)
        devices.append((i, device_info['name'], device_info['maxInputChannels']))
    audio.terminate()
    return devices

def select_input_device():
    devices = list_audio_devices()
    if not devices:
        print("No audio devices found.")
        return None
    suitable_devices = [i for i, name, channels in devices if channels >= config['audio']['channels']]
    if suitable_devices:
        return suitable_devices[0]
    else:
        print("No suitable input device found with the required number of channels.")
        print("Available devices:")
        for i, name, channels in devices:
            print(f"Device {i}: {name}, Channels: {channels}")
        return None

def record_audio():
    form_1 = getattr(pyaudio, config['audio']['format'])
    chans = config['audio']['channels']
    samp_rate = config['audio']['sample_rate']
    chunk = config['audio']['chunk_size']
    record_secs = config['audio']['record_seconds']
    dev_index = config['audio']['device_index']
    
    if dev_index is None or not validate_device_channels(dev_index, chans):
        dev_index = select_input_device()
        if dev_index is None:
            return None

    script_dir = os.path.dirname(os.path.abspath(__file__))
    wav_output_filename = os.path.join(script_dir, 'shazam.wav')

    audio = pyaudio.PyAudio()
    try:
        stream = audio.open(format=form_1, rate=samp_rate, channels=chans,
                            input_device_index=dev_index, input=True,
                            frames_per_buffer=chunk)
    except OSError as e:
        print(f"Error opening audio stream: {e}")
        return None

    frames = []

    try:
        for _ in range(int((samp_rate / chunk) * record_secs)):
            data = stream.read(chunk)
            frames.append(data)
    except IOError as e:
        print(f"Error recording audio: {e}")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

    wavefile = wave.open(wav_output_filename, 'wb')
    wavefile.setnchannels(chans)
    wavefile.setsampwidth(audio.get_sample_size(form_1))
    wavefile.setframerate(samp_rate)
    wavefile.writeframes(b''.join(frames))
    wavefile.close()

    return wav_output_filename

def validate_device_channels(device_index, required_channels):
    audio = pyaudio.PyAudio()
    device_info = audio.get_device_info_by_index(device_index)
    audio.terminate()
    return device_info['maxInputChannels'] >= required_channels

async def recognize_song(wav_file):
    shazam = Shazam()
    max_retries = config['network']['retry_count']
    for attempt in range(max_retries):
        try:
            return await shazam.recognize(wav_file)
        except Exception as e:
            print(f"Failed to recognize the song. Retrying... (Attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(config['network']['retry_delay'])
    print("Max retry attempts reached. Could not recognize the song.")
    return None

def create_blurred_background(image_path, screen_width, screen_height, blur_strength):
    original_image = Image.open(image_path)
    blurred_image = original_image.filter(ImageFilter.GaussianBlur(blur_strength))

    aspect_ratio = original_image.width / original_image.height
    if screen_width / screen_height > aspect_ratio:
        new_width = screen_width
        new_height = int(new_width / aspect_ratio)
    else:
        new_height = screen_height
        new_width = int(new_height * aspect_ratio)

    blurred_image = blurred_image.resize((new_width, new_height), Image.LANCZOS)

    left = (new_width - screen_width) // 2
    top = (new_height - screen_height) // 2
    right = (new_width + screen_width) // 2
    bottom = (new_height + screen_height) // 2
    blurred_image = blurred_image.crop((left, top, right, bottom))

    return blurred_image

def calculate_brightness(image):
    stat = ImageStat.Stat(image)
    r, g, b = stat.mean[:3]
    return (r * 0.299 + g * 0.587 + b * 0.114) / 255

def update_images():
    screen_width = root.winfo_width()
    screen_height = root.winfo_height()

    blurred_background = create_blurred_background(image_path, screen_width, screen_height, blur_strength)
    bg_image = ImageTk.PhotoImage(blurred_background)
    canvas.create_image(0, 0, anchor=tk.NW, image=bg_image)
    canvas.image = bg_image

    original_image = Image.open(image_path)
    border_size_relative = int(min(screen_width, screen_height) * border_size_ratio)
    square_size = min(screen_width, screen_height) - 2 * border_size_relative
    square_image = original_image.resize((square_size, square_size), Image.LANCZOS)
    square_photo = ImageTk.PhotoImage(square_image)

    img_item = canvas.create_image(screen_width // 2, screen_height // 2, anchor=tk.CENTER, image=square_photo)
    canvas.square_photo = square_photo

    # Calculate dynamic font size based on square image size and base font size from config
    base_font_size = config['gui']['base_font_size']
    font_size = max(10, int(square_size * 0.1 * (base_font_size / 25)))  # Adjust based on base_font_size
    title_font = ("Arial", font_size, "italic")
    artist_font = ("Arial", font_size, "bold")

    brightness = calculate_brightness(blurred_background)
    text_color = "black" if brightness > 0.5 else "white"

    # Ensure consistent spacing between text lines
    spacing = font_size * 1.2
    canvas.itemconfig(title_label, fill=text_color, font=title_font)
    canvas.itemconfig(artist_label, fill=text_color, font=artist_font)
    canvas.coords(title_label, screen_width // 2, (screen_height // 2) + square_size // 2 + spacing)
    canvas.coords(artist_label, screen_width // 2, (screen_height // 2) + square_size // 2 + spacing * 2)

    # Raise the text labels to ensure they are on top
    canvas.tag_raise(title_label)
    canvas.tag_raise(artist_label)

def update_gui(result):
    global last_track_title, last_artist_name, last_cover_art_url
    if 'track' in result:
        track_title = result['track']['title']
        artist_name = result['track']['subtitle']
        cover_art_url = result['track']['images']['coverarthq'] if 'images' in result['track'] else None
        if (track_title != last_track_title or artist_name != last_artist_name or cover_art_url != last_cover_art_url):
            last_track_title = track_title
            last_artist_name = artist_name
            last_cover_art_url = cover_art_url
            if cover_art_url:
                response = requests.get(cover_art_url, timeout=config['network']['timeout'])
                image_data = response.content
                with open('image.jpg', 'wb') as f:
                    f.write(image_data)

            update_images()
            canvas.itemconfig(title_label, text=track_title)
            canvas.itemconfig(artist_label, text=artist_name)
            canvas.tag_raise(title_label)
            canvas.tag_raise(artist_label)
        else:
            print("No changes detected, skipping GUI update.")
    else:
        print("Could not recognize the song.")

def toggle_fullscreen(event=None):
    if root.attributes("-fullscreen"):
        root.attributes("-fullscreen", False)
        root.geometry("800x600")
    else:
        monitor = get_monitor_for_window()
        if monitor:
            root.geometry(f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")
        root.attributes("-fullscreen", True)
    update_images()

def hide_cursor():
    root.config(cursor="none")

def show_cursor():
    root.config(cursor="")

def reset_cursor_hide_timer(event=None):
    global cursor_hide_timer
    root.after_cancel(cursor_hide_timer)
    show_cursor()
    cursor_hide_timer = root.after(5000, hide_cursor)

def get_monitor_for_window():
    window_x = root.winfo_rootx()
    window_y = root.winfo_rooty()
    for monitor in get_monitors():
        if (monitor.x <= window_x < monitor.x + monitor.width and
            monitor.y <= window_y < monitor.y + monitor.height):
            return monitor
    return None

def on_resize(event):
    global resize_job
    if resize_job:
        root.after_cancel(resize_job)
    resize_job = root.after(200, update_images)

def run_recognition_loop():
    while True:
        asyncio.run(update_song_information())

def start_recognition_thread():
    thread = threading.Thread(target=run_recognition_loop)
    thread.daemon = True
    thread.start()

async def update_song_information():
    wav_file = record_audio()
    if wav_file is not None:
        result = await recognize_song(wav_file)
        if result:
            update_gui(result)
    else:
        # Ensure the GUI updates even if audio recognition fails
        root.after(config['gui']['update_interval'], lambda: asyncio.run(update_song_information()))

# Initialize Tkinter root and GUI elements
root = tk.Tk()
root.title("Song Recognition")

resize_job = None

# Set initial fullscreen mode
monitor = get_monitor_for_window()
if monitor:
    root.geometry(f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")
root.attributes("-fullscreen", True)

root.bind("<Escape>", toggle_fullscreen)
root.bind("<Motion>", reset_cursor_hide_timer)
root.bind("<Configure>", on_resize)

cursor_hide_timer = root.after(5000, hide_cursor)

image_path = "image.jpg"
blur_strength = config['gui']['blur_strength']
border_size_ratio = config['gui']['border_size_ratio']

canvas = tk.Canvas(root, width=root.winfo_screenwidth(), height=root.winfo_screenheight())
canvas.pack(fill=tk.BOTH, expand=tk.YES)

title_label = canvas.create_text(0, 0, text="", font=("Arial", 25, "italic"), fill="white", anchor=tk.CENTER)
artist_label = canvas.create_text(0, 0, text="", font=("Arial", 25, "bold"), fill="white", anchor=tk.CENTER)

last_track_title = ""
last_artist_name = ""
last_cover_art_url = ""

start_recognition_thread()
root.mainloop()
