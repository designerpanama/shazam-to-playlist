import eel
import threading
import asyncio
import os
import io
import time
import json
import numpy as np
import soundcard as sc
import soundfile as sf
from shazamio import Shazam

# Состояния
is_capturing = False
is_paused = False

# Храним историю в AppData пользователя, чтобы .exe работал из любой папки без прав админа
APP_DIR = os.path.join(os.getenv('LOCALAPPDATA') or os.path.expanduser('~'), 'ShazamToPlaylist')
os.makedirs(APP_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(APP_DIR, "history.json")

history_data = {"tracks": [], "sessions": []}

def load_history():
    global history_data
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    history_data = {"tracks": data, "sessions": []}
                else:
                    history_data = data
        except Exception:
            pass

def save_history():
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

load_history()
eel.init('web')

@eel.expose
def remove_track(track_id):
    history_data['tracks'] = [t for t in history_data['tracks'] if t['id'] != track_id]
    save_history()

@eel.expose
def clear_tracks():
    history_data['tracks'].clear()
    save_history()

@eel.expose
def save_session(session_name, tracks_in_session):
    history_data['sessions'].insert(0, {"name": session_name, "tracks": tracks_in_session})
    save_history()

@eel.expose
def clear_sessions():
    history_data['sessions'].clear()
    save_history()

@eel.expose
def start_capture():
    global is_capturing, is_paused
    if not is_capturing:
        is_capturing = True
        is_paused = False
        threading.Thread(target=capture_loop, daemon=True).start()

@eel.expose
def pause_capture():
    global is_paused
    is_paused = True

@eel.expose
def resume_capture():
    global is_paused
    is_paused = False

@eel.expose
def stop_capture():
    global is_capturing, is_paused
    is_capturing = False
    is_paused = False

def capture_loop():
    global is_capturing, is_paused
    track_id_counter = int(time.time())
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    shazam = Shazam()

    while is_capturing:
        if is_paused:
            time.sleep(0.5)
            continue
            
        try:
            default_speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(id=str(default_speaker.id), include_loopback=True)
            
            with loopback_mic.recorder(samplerate=48000) as mic:
                data = mic.record(numframes=48000 * 7)
            
            # Пропускаем распознавание, если в системе полная тишина
            if np.max(np.abs(data)) < 0.005:
                time.sleep(2)
                continue

            # Пишем WAV в оперативную память вместо диска
            audio_buffer = io.BytesIO()
            sf.write(audio_buffer, data, 48000, format='WAV')
            audio_bytes = audio_buffer.getvalue()
            
            track_info = loop.run_until_complete(shazam.recognize(audio_bytes))
            if track_info and 'track' in track_info:
                title = track_info['track']['title']
                artist = track_info['track']['subtitle']
                
                if not any(t['title'].lower() == title.lower() and t['artist'].lower() == artist.lower() for t in history_data['tracks']):
                    new_track = {'id': track_id_counter, 'title': title, 'artist': artist}
                    history_data['tracks'].append(new_track)
                    track_id_counter += 1
                    save_history()
                    eel.addTrackFromPython(new_track['id'], new_track['title'], new_track['artist'])()
            
            for _ in range(50):
                if not is_capturing or is_paused:
                    break
                time.sleep(0.1)
                
        except Exception as e:
            eel.showToastFromPython(f"⚠️ Ошибка захвата: {str(e)[:35]}")()
            time.sleep(3)

@eel.expose
def get_history_data():
    return history_data

@eel.expose
def get_tracks_text():
    if not history_data['tracks']:
        return ""
    return "\n".join([f"{t['artist']} - {t['title']}" for t in history_data['tracks']])

if __name__ == '__main__':
    eel.start('index.html', size=(410, 680), position=(500, 200))