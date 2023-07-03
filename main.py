import pathlib
import babelfish
import re
import argparse
import os
import csv
import string
import subprocess

import moviepy.editor as mp
import jaconvV2
import logging
import deepl
import requests
import json
import pysubs2
import ffmpeg
from collections import namedtuple
from pathlib import Path
from anilist import Client

from datetime import datetime, timedelta
from dotenv import load_dotenv
from guessit import guessit

SUPPORTED_LANGUAGES = ["en", "ja", "es"]

EpisodeCsvRow = namedtuple(
    "Row",
    [
        "ID",
        "POSITION",
        "START_TIME",
        "END_TIME",
        "NAME_AUDIO",
        "NAME_SCREENSHOT",
        "CONTENT",
        "CONTENT_TRANSLATION_SPANISH",
        "CONTENT_TRANSLATION_ENGLISH",
        "CONTENT_SPANISH_MT",
        "CONTENT_ENGLISH_MT",
    ],
)

MatchingSubtitle = namedtuple("MatchingSubtitle", ["origin", "data", "filepath"])


def main():
    load_dotenv()
    args = command_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    deepl_token = os.getenv("TOKEN") or args.token
    if not deepl_token:
        logging.warning(
            " > IMPORTANT < DEEPL TOKEN has not been detected. Subtitles won't be translated to all supported languages"
        )

    translator = deepl.Translator(deepl_token) if deepl_token else None

    # Input and output folders
    input_folder = args.input
    output_folder = args.output

    episode_filepaths = [
        os.path.join(root, name)
        for root, dirs, files in os.walk(input_folder)
        for name in files
        if name.endswith(".mkv")
    ]

    if not episode_filepaths:
        logging.error(f"No .mkv files found in {input_folder}! Nothing else to do.")
        return

    logging.info(
        f"Found {len(episode_filepaths)} files to process in {input_folder}..."
    )

    anilist = CachedAnilist()

    for episode_filepath in episode_filepaths:
        try:
            logging.info(
                f"\n-------------------------------------------------------------\n"
            )
            logging.info(f"Filepath: {episode_filepath}\n")

            # Guessit
            guessit_query = extract_anime_title_for_guessit(episode_filepath)
            logging.info(f"> Query for Guessit: {guessit_query}")
            episode_info = guessit(guessit_query)

            guessed_anime_title = episode_info["title"]
            season_number_pretty = f"S{episode_info['season']:02d}"
            episode_number_pretty = f"E{episode_info['episode']:02d}"
            logging.info(
                f"Guessed information: {guessed_anime_title} {season_number_pretty}{episode_number_pretty}\n"
            )

            # Anilist
            anilist_query = extract_anime_title_for_anilist(guessed_anime_title)
            logging.info(f"Query for Anilist: {anilist_query}")
            anime_info = anilist.get_anime(anilist_query)
            name_romaji = anime_info.title.romaji
            logging.info(f"Anime found: {name_romaji}\n")

            # Create folder for saving info.json and segments
            anime_folder_name = map_anime_title_to_media_folder(name_romaji)
            anime_folder_fullpath = os.path.join(output_folder, anime_folder_name)
            os.makedirs(anime_folder_fullpath, exist_ok=True)
            logging.info(f"> Base anime folder: {anime_folder_fullpath}")

            info_json_fullpath = os.path.join(anime_folder_fullpath, "info.json")
            logging.info(f"Filepath for info.json: {info_json_fullpath}\n")

            if not os.path.exists(info_json_fullpath):
                logging.info("Creating new info.json file...")

                with open(info_json_fullpath, "wb") as f:
                    info_json = {
                        "version": "1",
                        "folder_media_anime": anime_folder_name,
                        "japanese_name": anime_info.title.native,
                        "english_name": anime_info.title.english,
                        "romaji_name": anime_info.title.romaji,
                        "airing_format": anime_info.format,
                        "airing_status": anime_info.status,
                        "genres": anime_info.genres,
                    }

                    if "cover" not in info_json:
                        cover_data = requests.get(anime_info.cover.extra_large).content
                        cover_filename = (
                            f"cover{os.path.splitext(anime_info.cover.extra_large)[1]}"
                        )
                        with open(
                            os.path.join(anime_folder_fullpath, cover_filename), "wb"
                        ) as handler:
                            handler.write(cover_data)
                        info_json["cover"] = os.path.join(
                            anime_folder_name, cover_filename
                        )

                    if "banner" not in info_json:
                        banner_data = requests.get(anime_info.banner).content
                        banner_filename = (
                            f"banner{os.path.splitext(anime_info.cover.extra_large)[1]}"
                        )
                        with open(
                            os.path.join(anime_folder_fullpath, banner_filename), "wb"
                        ) as handler:
                            handler.write(banner_data)
                        info_json["banner"] = os.path.join(
                            anime_folder_name, banner_filename
                        )

                    logging.info(f"Json Data: {info_json}\n")

                    # Use utf8 for writing Japanese characters correctly
                    json_data = json.dumps(
                        info_json, indent=2, ensure_ascii=False
                    ).encode("utf8")
                    f.write(json_data)

            # Get subtitles
            logging.info("> Finding matching subtitles...")
            matching_subtitles = {}

            # Part 1: Find subtitle files on same directory as episode, with same episode number
            input_episode_parent_folder = Path(episode_filepath).parent
            subtitle_filepaths = [
                os.path.join(input_episode_parent_folder, filename)
                for filename in os.listdir(input_episode_parent_folder)
                if filename.endswith(".ass") or filename.endswith(".srt")
            ]
            logging.debug(f"Subtitle filepaths: {subtitle_filepaths}")

            for subtitle_filepath in subtitle_filepaths:
                guessed_subtitle_info = guessit(subtitle_filepath)
                guessed_subtitle_episode_number = guessed_subtitle_info["episode"]
                print(guessed_subtitle_episode_number)
                if guessed_subtitle_episode_number == episode_info["episode"]:
                    logging.info(f"> Found external subtitle {subtitle_filepath}")

                    subtitle_language = None
                    if "subtitle_language" in guessed_subtitle_info:
                        subtitle_language = guessed_subtitle_info[
                            "subtitle_language"
                        ].alpha2
                    else:
                        # TODO: Try to infer language from subtitle content
                        pass

                    if not subtitle_language:
                        logging.error(
                            "Impossible to guess the language of the subtitle. Skipping..."
                        )
                        continue

                    if subtitle_language not in SUPPORTED_LANGUAGES:
                        logging.info(
                            f"Language {subtitle_language} is currently not supported. Skipping..."
                        )
                        continue

                    subtitle_data = pysubs2.load(subtitle_filepath)
                    logging.info(
                        f">Found [{subtitle_language}] subtitles: {subtitle_data}"
                    )

                    if subtitle_language in matching_subtitles and len(
                        subtitle_data
                    ) < len(matching_subtitles[subtitle_language]):
                        logging.info(
                            f"Already found better matching subtitles for this language. Skipping..."
                        )
                        continue

                    logging.info(f"Saving subtitles: {subtitle_data}\n")
                    matching_subtitles[subtitle_language] = MatchingSubtitle(
                        origin="external",
                        filepath=subtitle_filepath,
                        data=subtitle_data,
                    )

            # Part 2: extract srt/ass from mkv (WIP)
            # * Extract to /tmp
            # * Add subtitles to matching_subtitles
            tmp_output_folder = os.path.join(anime_folder_fullpath, "tmp")
            os.makedirs(tmp_output_folder, exist_ok=True)
            file_probe = ffmpeg.probe(episode_filepath)
            subtitle_streams = [
                stream
                for stream in file_probe["streams"]
                if stream["codec_type"] == "subtitle"
            ]

            for subtitle_stream in subtitle_streams:
                index = subtitle_stream["index"]
                codec = subtitle_stream["codec_name"]
                subtitle_language = babelfish.Language(
                    subtitle_stream["tags"]["language"]
                ).alpha2
                logging.info(
                    f"Found internal subtitle stream. Index: {index}. Codec: {codec}. Language: {subtitle_language}"
                )

                if subtitle_language not in SUPPORTED_LANGUAGES:
                    logging.info(
                        f"Language {subtitle_language} is currently not supported. Skipping..."
                    )
                    continue

                output_sub_tmp_filepath = os.path.join(
                    tmp_output_folder, f"tmp.{codec}"
                )

                subprocess.call(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        episode_filepath,
                        "-map",
                        f"0:{index}",
                        "-c",
                        "copy",
                        output_sub_tmp_filepath,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                logging.info(f"Exported subtitle to: {output_sub_tmp_filepath}")

                subtitle_data = pysubs2.load(output_sub_tmp_filepath)
                logging.info(f">Found [{subtitle_language}] subtitles: {subtitle_data}")

                if subtitle_language in matching_subtitles:
                    logging.info(f"> Already matched subtitles for this language!!")

                    if len(subtitle_data) > len(matching_subtitles[subtitle_language]):
                        logging.info(
                            ">> Current subtitle file is longer than previous selected. Overriding..."
                        )
                    else:
                        continue

                logging.info(f"Saving subtitles: {subtitle_data}\n")
                output_sub_final_filepath = os.path.join(
                    tmp_output_folder,
                    f"{name_romaji} {season_number_pretty}{episode_number_pretty}.{subtitle_language}.{codec}",
                )
                subtitle_data.save(output_sub_final_filepath)
                matching_subtitles[subtitle_language] = MatchingSubtitle(
                    origin="internal",
                    filepath=output_sub_final_filepath,
                    data=subtitle_data,
                )

            # TODO: Still Work In Progress

            logging.info(f"Matching subtitles: {matching_subtitles}\n")

            # Having matching JP subtitles is required
            if "ja" not in matching_subtitles:
                raise Exception(
                    "Could not find a file for Japanese subtitles. Skipping..."
                )

            # Start segmenting file
            logging.info("Start file segmentation...")

            episode_folder_output_path = os.path.join(
                anime_folder_fullpath, season_number_pretty, episode_number_pretty
            )
            os.makedirs(episode_folder_output_path, exist_ok=True)

            split_video_by_subtitles(
                translator,
                episode_filepath,
                matching_subtitles,
                episode_folder_output_path,
            )

            pathlib.Path(tmp_output_folder).rmdir()
            logging.info(f"Finished")

        except Exception:
            logging.error(
                "Something happened processing the anime. Skipping...", exc_info=True
            )
            continue


def split_video_by_subtitles(
    translator, video_file, subtitles, episode_folder_output_path
):
    video = mp.VideoFileClip(video_file)

    # TODO: Use the other subtitles
    subtitles_ja = subtitles["ja"].data

    csv_filepath = os.path.join(episode_folder_output_path, "data.csv")
    with open(csv_filepath, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile, fieldnames=EpisodeCsvRow._fields, delimiter=";"
        )
        writer.writeheader()

        for i, line in enumerate(subtitles_ja):
            sentence = process_subtitle_line(line)

            if not sentence:
                logging.debug(f"[SKIP]: {line.plaintext}")
                continue

            # Subtitles
            start_time = timedelta(milliseconds=line.start)
            start_seconds = start_time.total_seconds()

            end_time = timedelta(milliseconds=line.end)
            end_seconds = end_time.total_seconds()

            sentence_spanish = None
            sentence_spanish_is_mt = None

            sentence_english = None
            sentence_english_is_mt = None

            logging.info(f"\n\n({i}): {start_time} - {end_time}")
            logging.info(f"[JAPANESE]: {sentence}")

            if translator:
                usage = translator.get_usage()

                if usage.any_limit_reached:
                    logging.warning("Translation limit REACHED")
                else:
                    logging.info(
                        f"Character usage: {usage.character.count} of {usage.character.limit}"
                    )

                    if translator:
                        sentence_spanish = translator.translate_text(
                            sentence, source_lang="JA", target_lang="ES"
                        ).text
                        sentence_spanish_is_mt = True
                        logging.info(f"[SPANISH]: {sentence_spanish}")

                    if translator:
                        sentence_english = translator.translate_text(
                            sentence, source_lang="JA", target_lang="EN-US"
                        ).text
                        sentence_english_is_mt = True
                        logging.info(f"[ENGLISH]: {sentence_english}")

            # Audio
            try:
                subclip = video.subclip(start_seconds, end_seconds)
                audio = subclip.audio
                audio_filename = f"{i + 1:03d}.mp3"
                audio_path = os.path.join(episode_folder_output_path, audio_filename)

                audio.write_audiofile(audio_path, codec="mp3")

            except Exception as err:
                print(f"Error creating audio '{audio_filename}'", err)
                continue

            # Screenshot
            try:
                screenshot_filename = f"{i + 1:03d}.webp"
                screenshot_path = os.path.join(
                    episode_folder_output_path, screenshot_filename
                )

                video.save_frame(screenshot_path, t=start_seconds)

            except Exception as err:
                print(f"Error creating screenshot '{screenshot_filename}'", err)
                continue

            writer.writerow(
                EpisodeCsvRow(
                    ID=f"{i + 1:03d}",
                    POSITION=f"{i + 1}",
                    START_TIME=str(start_time),
                    END_TIME=str(end_time),
                    NAME_AUDIO=audio_filename,
                    NAME_SCREENSHOT=screenshot_filename,
                    CONTENT=sentence,
                    CONTENT_TRANSLATION_SPANISH=sentence_spanish,
                    CONTENT_TRANSLATION_ENGLISH=sentence_english,
                    CONTENT_SPANISH_MT=sentence_spanish_is_mt,
                    CONTENT_ENGLISH_MT=sentence_english_is_mt,
                )._asdict()
            )

        logging.info(">> CSV File Completed!!")


def process_subtitle_line(line):
    if line.type != "Dialogue" or isNonJapanese(line.plaintext):
        return ""

    # Normaliza half-width (Hankaku) a full-width (Zenkaku) caracteres
    processed_sentence = jaconvV2.normalize(line.plaintext, "NFKC")
    special_chars = [
        "\(\(.*?\)\)",
        "\（.*?\）",
        "《",
        "》",
        "●",
        "→",
        "\（.*?\）",
        "（",
        "）",
        "【",
        "】",
        "＜",
        "＞",
        "［",
        "］",
        "⦅",
        "⦆",
    ]
    return processed_sentence.translate(
        str.maketrans("", "", "".join(special_chars))
    ).strip()


def time_to_seconds(time_str):
    time = datetime.strptime(time_str.replace(",", "."), "%H:%M:%S.%f")
    return timedelta(
        hours=time.hour,
        minutes=time.minute,
        seconds=time.second,
        microseconds=time.microsecond,
    ).total_seconds()


class CachedAnilist:
    def __init__(self):
        self.client = Client()
        self.cached_results = {}

    def get_anime(self, search_query):
        if search_query in self.cached_results:
            return self.cached_results[search_query]

        # Also, have
        search_results = self.client.search(search_query)
        logging.debug("Search results", search_results)

        if not search_results:
            raise Exception(
                f"Anime with title {search_results} not found. Please check file name"
            )

        anime_id = search_results[0].id
        anime_result = self.client.get_anime(anime_id)
        self.cached_results[search_query] = anime_result

        return anime_result


def extract_anime_title_for_guessit(episode_filepath):
    """
    This method tries to parse the full episode path and get a coherent anime title. This methods does the following
    postprocessing:
      * Take only the episode name and the parent folder name
      * Remove everything between [ and ]. This is usually the encoder name or the file ID
      * Remove tags related to file quality and format (1080p/720p, Audio, HEVC, x265, BDRip...)

    Example:
      * Input:  Shingeki No Kyojin S01 1080p BDRip 10 bits x265-EMBER/S01E01- To You, in 2000 Years [14197707]
      * Output: Shingeki No Kyojin S01 -EMBER S01E01- To You, in 2000 Years

    This allows guessit to return "Shingeki No Kyojin" as the anime title, instead of returning the episode title
    """
    return re.sub(
        "[.*?]|1080p|720p|BDRip|Dual\s?Audio|x?26[4|5]-?|HEVC|10\sbits|EMBER",
        "",
        " ".join(episode_filepath.split("/")[-2:]),
    )


def extract_anime_title_for_anilist(guessed_anime_title):
    """
    After extracting the name from Guessit, we have to do a bit more of postprocessing because Anilist is really
    sensitive with the title search. Including extra information like season or episodoe number will case Anilist
    to return nothing:
        * Remove Season and Episode numbers
    """
    return re.sub(r"S\d.*?(\s|$)", "", guessed_anime_title).strip()


def map_anime_title_to_media_folder(anime_title):
    """
    Root folder for all the anime information (subfolders for seasons/episodes, info.json, etc) will be stored using
    lower case, kebab case, without any punctuation or invalid symbols

    Example:
        * Input: Mobile Suit Gundam: The Witch from Mercury
        * Ooutput: mobile-suit-gundam-the-witch-from-mercury
    """
    return "-".join(
        anime_title.lower().translate(str.maketrans("", "", string.punctuation)).split()
    )


def isNonJapanese(sentence):
    """
    Check if a string can be encoded only with ASCII characters, which is a nice way to filter
    sentences that have no CJK characters.
    """
    try:
        sentence.encode(encoding="utf-8").decode("ascii")
    except UnicodeDecodeError:
        return False
    else:
        return True


def command_args():
    parser = argparse.ArgumentParser(
        description="Split one or several .mkv files onto separate audio segments with images"
    )
    parser.add_argument(
        "input", type=pathlib.Path, help="Input folder with .mkv files and subtitles"
    )
    parser.add_argument(
        "output",
        type=pathlib.Path,
        help="Output folder",
    )
    parser.add_argument(
        "-t",
        "--token",
        dest="token",
        type=str,
        help="DeepL token for translating subtitles. If not provided, the only generated subtitles will be taken from "
        "existing subtitle files",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Add extra debug information to the execution",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
