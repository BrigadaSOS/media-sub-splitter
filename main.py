import random
import deepl
import re
import string
import os
import csv 
import moviepy.editor as mp
from datetime import datetime

auth_key = "66211300-a650-e14c-77d4-a26eb71afef9:fx" 

translator = deepl.Translator(auth_key)

def split_video_by_subtitles(video_file, subtitle_file):
    video = mp.VideoFileClip(video_file)
    subtitle_lines = parse_subtitles(subtitle_file)

    output_folder = './subclips'
    os.makedirs(output_folder, exist_ok=True)
    
    csv_filename = os.path.join(output_folder, 'data.csv')
    
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['ID', 'POSITION', 'START_TIME', 'END_TIME', 'NAME_AUDIO', 'NAME_SCREENSHOT', 'CONTENT', 'CONTENT_TRANSLATION_SPANISH', 'CONTENT_TRANSLATION_ENGLISH']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        
        filename = os.path.splitext(os.path.basename(video_file))[0]

        for i, line in enumerate(subtitle_lines):
            sentence = line['sentence']
            sentence = re.sub('\(\(.*?\)\)', '', line['sentence'])
            sentence = re.sub('\(.*?\)', '', sentence)
            sentence = re.sub('《', '', sentence)
            sentence = re.sub('》', '', sentence)
            sentence = re.sub('→', '', sentence)
            sentence = re.sub('\（.*?\）', '', sentence)
            sentence = re.sub('（', '', sentence)
            sentence = re.sub('）', '', sentence)

            if sentence.strip():
                start_time = line['start']
                end_time = line['end']
                
                sentence_spanish = translator.translate_text(sentence, source_lang="JA", target_lang="ES").text
                sentence_english = translator.translate_text(sentence, source_lang="JA", target_lang="EN-US").text

                #sentence_english = ''
                #sentence_spanish = ''

                letras = string.ascii_letters
                random_letters = filename
                
                start_seconds = time_to_seconds(start_time)
                end_seconds = time_to_seconds(end_time)
                
                subclip = video.subclip(start_seconds, end_seconds)
                #output_filename = f"{i+1:03d}_{random_letters}.mkv"
                #output_path = os.path.join(output_folder, output_filename)
                #subclip.write_videofile(output_path, codec='libx264', audio_codec='aac')
                #print(f"Video '{output_filename}' generado.")
                
                audio = subclip.audio
                audio_filename = f"{i+1:03d}_{random_letters}.mp3"
                audio_path = os.path.join(output_folder, audio_filename)
                try:
                    audio.write_audiofile(audio_path, codec="mp3")
                except:
                    print(f"Error en el audio '{audio_filename}'")
                    continue
                    
                #print(f"Audio '{audio_filename}' generado.")
                
                #text_filename = f"{i+1:03d}_{random_letters}.txt"
                #text_path = os.path.join(output_folder, text_filename)
                #with open(text_path, 'w', encoding="utf-8") as file:
                #    file.write(random_letters)
                #print(f"Archivo de texto '{text_filename}' generado.")
                
                print(sentence)
                print(start_time, start_seconds)
                print(end_time, end_seconds)

                screenshot_filename = f"{i+1:03d}_{random_letters}.webp"
                screenshot_path = os.path.join(output_folder, screenshot_filename)
                try:
                    video.save_frame(screenshot_path, t=start_seconds)
                except:
                    print(f"Error en el pantallazo '{screenshot_filename}'")
                    continue
                
                #print(f"Pantallazo '{screenshot_filename}' generado.")

                writer.writerow({
                    'ID': f"{i+1:03d}_{random_letters}",
                    'POSITION': f"{i+1}",
                    'START_TIME': start_time,
                    'END_TIME': end_time,
                    'NAME_AUDIO': audio_filename,
                    'NAME_SCREENSHOT': screenshot_filename,
                    'CONTENT': sentence,
                    'CONTENT_TRANSLATION_SPANISH': sentence_spanish,
                    'CONTENT_TRANSLATION_ENGLISH': sentence_english
                })
    
    print(f"Archivo CSV '{csv_filename}' generado.")
        
def parse_subtitles(subtitle_file):
    _, ext = os.path.splitext(subtitle_file)
    if ext == '.srt':
        return parse_srt(subtitle_file)
    elif ext == '.ass':
        return parse_ass(subtitle_file)
    else:
        raise ValueError("Formato de subtítulos no compatible.")
        
def parse_srt(subtitle_file):
    subtitle_lines = []
    
    with open(subtitle_file, 'r',  encoding='utf-8') as file:
        lines = file.read().split('\n\n')
        
        for line in lines:
            line = line.strip().split('\n')
            
            if len(line) >= 3:
                start, end = line[1].split(' --> ')
                sentence = ' '.join(line[2:])
                
                subtitle_lines.append({
                    'start': start,
                    'end': end,
                    'sentence': sentence
                })
    
    return subtitle_lines

def parse_ass(subtitle_file):
    subtitle_lines = []
    
    with open(subtitle_file, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        
        for line in lines:
            if line.startswith('Dialogue:'):
                parts = line.split(',')
                
                start = parts[1]
                end = parts[2]
                sentence = parts[9].strip()
                
                subtitle_lines.append({
                    'start': start,
                    'end': end,
                    'sentence': sentence
                })
                
    return subtitle_lines

def time_to_seconds(time_str):
    time = datetime.strptime(time_str, "%H:%M:%S,%f")
    total_seconds = (time.hour * 3600) + (time.minute * 60) + time.second + (time.microsecond / 1000000)
    return total_seconds

# Ruta del archivo de video MKV y archivo de subtítulos
video_file = 'C:/Users/Jonathan/Desktop/NadeDB/MEDIA-SUB-SPLITTER-JP/input/oshinoko1.mkv'
subtitle_file = 'C:/Users/Jonathan/Desktop/NadeDB/MEDIA-SUB-SPLITTER-JP/input/oshinoko1.srt' 

split_video_by_subtitles(video_file, subtitle_file)