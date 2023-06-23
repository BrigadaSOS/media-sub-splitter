import re
import pathlib
import argparse
import string
import os
import csv
from datetime import datetime
from dotenv import load_dotenv

import moviepy.editor as mp
import deepl


def split_video_by_subtitles(translator, video_file, subtitle_file, output_folder):
    video = mp.VideoFileClip(video_file)
    subtitle_lines = parse_subtitles(subtitle_file)

    os.makedirs(output_folder, exist_ok=True)

    csv_filename = os.path.join(output_folder, 'data.csv')

    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['ID', 'POSITION', 'START_TIME', 'END_TIME', 'NAME_AUDIO', 'NAME_SCREENSHOT',
                      'CONTENT', 'CONTENT_TRANSLATION_SPANISH', 'CONTENT_TRANSLATION_ENGLISH']
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
            sentence = re.sub('【', '', sentence)
            sentence = re.sub('】', '', sentence)
            sentence = re.sub('＜', '', sentence)
            sentence = re.sub('＞', '', sentence)
            sentence = re.sub('［', '', sentence)
            sentence = re.sub('］', '', sentence)
            sentence = re.sub('⦅', '', sentence)
            sentence = re.sub('⦆', '', sentence)

            if sentence.strip():
                start_time = line['start']
                end_time = line['end']

                sentence_spanish = translator.translate_text(
                    sentence, source_lang="JA", target_lang="ES").text
                sentence_english = translator.translate_text(
                    sentence, source_lang="JA", target_lang="EN-US").text

                #sentence_english = ''
                #sentence_spanish = ''

                letras = string.ascii_letters
                random_letters = filename

                start_seconds = time_to_seconds(start_time)
                end_seconds = time_to_seconds(end_time)

                subclip = video.subclip(start_seconds, end_seconds)
                # output_filename = f"{i+1:03d}_{random_letters}.mkv"
                # output_path = os.path.join(output_folder, output_filename)
                # subclip.write_videofile(output_path, codec='libx264', audio_codec='aac')
                # print(f"Video '{output_filename}' generado.")

                audio = subclip.audio
                audio_filename = f"{i+1:03d}_{random_letters}.mp3"
                audio_path = os.path.join(output_folder, audio_filename)
                try:
                    audio.write_audiofile(audio_path, codec="mp3")
                except:
                    print(f"Error en el audio '{audio_filename}'")
                    continue

                # print(f"Audio '{audio_filename}' generado.")

                # text_filename = f"{i+1:03d}_{random_letters}.txt"
                # text_path = os.path.join(output_folder, text_filename)
                # with open(text_path, 'w', encoding="utf-8") as file:
                #    file.write(random_letters)
                # print(f"Archivo de texto '{text_filename}' generado.")

                print(sentence)
                print(start_time, start_seconds)
                print(end_time, end_seconds)

                screenshot_filename = f"{i+1:03d}_{random_letters}.webp"
                screenshot_path = os.path.join(
                    output_folder, screenshot_filename)
                try:
                    video.save_frame(screenshot_path, t=start_seconds)
                except:
                    print(f"Error en el pantallazo '{screenshot_filename}'")
                    continue

                # print(f"Pantallazo '{screenshot_filename}' generado.")

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
    time = datetime.strptime(time_str, "%H:%M:%S.%f")
    total_seconds = (time.hour * 3600) + (time.minute * 60) + \
        time.second + (time.microsecond / 1000000)
    return total_seconds


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Segmenta uno o varios archivos .mkv en varios trozos de audio" +
    "incluyendo subtítulos y una imágen correspondiente.")
    parser.add_argument('input', type=pathlib.Path, help="Archivo o carpeta de entrada" +
                        "process.")
    parser.add_argument('output', type=pathlib.Path, help="Carpeta donde guardar los" +
                        "archivos procesados.")
    parser.add_argument('-t', '--token', dest='token', type=str,
                        help="Token de DeepL API para traducir los subtítulos.")

    args = parser.parse_args()

    auth_key = os.getenv("AUTH_KEY") or args.token
    if not auth_key:
        raise Exception("Es necesario un token de DeepL para realizar la traducción.")

    translator = deepl.Translator(auth_key)

    # Ruta de la carpeta de entrada
    input_folder = args.input

    # Carpeta de salida para los archivos generados
    output_folder = args.output

    # Orden definido por el filesystem
    files = os.listdir(input_folder)
    video_files = [file for file in files if file.lower().endswith('.mkv')]
    subtitle_files = [file for file in files if file.lower().endswith('.ass') or
                      file.lower().endswith(".srt")]

    if len(video_files) != len(subtitle_files):
        raise Exception("La cantidad de archivos de vídeo y de subtítulos es" +
                        "diferente. Asegure que cada .mkv tenga sus archivo de" +
                        "subtítulos en japonés correspondiente.")

    for (video_file, subtitle_file) in zip(video_files, subtitle_files):
        if video_file.split('.')[0] != subtitle_file.split('.')[0]:
            raise Exception(f"El subtítulo {subtitle_file} no corresponde al archivo" +
                            "de vídeo {video_file}. Asegure que ambos tengan el" +
                            "mismo nombre")


        video_file_path = os.path.join(input_folder, video_file)
        subtitle_file_path = os.path.join(input_folder, subtitle_file)

        episode_number = re.findall(r'\d+|S\d+E\d+', video_file)[0]
        print(episode_number)
        output_folder_name = f'{os.path.splitext(video_file)[0]}'
        print(output_folder_name)
        episode_output_folder = os.path.join(output_folder, output_folder_name)
        print(episode_output_folder)

        split_video_by_subtitles(translator, video_file_path, subtitle_file_path,
                                 episode_output_folder)

        print(
            f"Archivos generados para el episodio {episode_number} en la carpeta '{output_folder_name}'.")


if __name__ == "__main__":
    main()
