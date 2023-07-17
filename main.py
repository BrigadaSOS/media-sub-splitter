import pathlib
import shutil
import inquirer

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

from datetime import timedelta
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
        "ACTOR_JA",
        "ACTOR_ES",
        "ACTOR_EN",
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
                guessed_subtitle_info = guessit(
                    re.sub(r"\[.*?\]", "", subtitle_filepath)
                )
                guessed_subtitle_episode_number = guessed_subtitle_info["episode"]
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
            # * Get every subtitle and filter it by using a checkbox select
            # * Extract to /tmp
            # * Add subtitles to matching_subtitles
            tmp_output_folder = os.path.join(anime_folder_fullpath, "tmp")
            os.makedirs(tmp_output_folder, exist_ok=True)
            file_probe = ffmpeg.probe(episode_filepath)

            subtitles_dict = {}
            for stream in file_probe["streams"]:
                if stream["codec_type"] == "subtitle":
                    index = stream["index"]
                    title = stream.get("tags", {}).get("title")
                    language = stream.get("tags", {}).get("language")
                    if title and language:
                        subtitles_dict[index] = {"title": title, "language": language}

            subtitle_choices = [
                {"name": f"{details['title']} ({details['language']})", "value": index}
                for index, details in subtitles_dict.items()
            ]

            subtitle_questions = [
                inquirer.Checkbox(
                    "subtitle_streams",
                    message="What subtitles do you want to use?",
                    choices=subtitle_choices,
                ),
            ]

            selected_subtitles = inquirer.prompt(subtitle_questions)
            selected_indices = [
                subtitle["value"] for subtitle in selected_subtitles["subtitle_streams"]
            ]

            subtitle_streams = [
                stream
                for stream in file_probe["streams"]
                if stream["codec_type"] == "subtitle"
                and stream["index"] in selected_indices
            ]

            for subtitle_stream in subtitle_streams:
                index = subtitle_stream["index"]
                codec = subtitle_stream["codec_name"]
                tag_language = subtitle_stream["tags"]["language"]

                # Support for non-ISO 639-3 language tags
                tag_language_normalizer = {"fre": "fra", "ger": "deu"}

                if tag_language_normalizer.get(tag_language):
                    tag_language = tag_language_normalizer.get(tag_language)

                subtitle_language = babelfish.Language(tag_language).alpha2
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

                    if (
                        len(subtitle_data) > len(matching_subtitles[subtitle_language])
                        and matching_subtitles[subtitle_language].origin != "external"
                    ):
                        logging.info(
                            ">> Current subtitle internal file is longer than previous selected. Overriding..."
                        )
                    else:
                        continue

                logging.info(f"Saving subtitles: {subtitle_data}\n")
                output_sub_final_filepath = os.path.join(
                    tmp_output_folder,
                    f"{anime_folder_name} {season_number_pretty}{episode_number_pretty}.{subtitle_language}.{codec}",
                )
                subtitle_data.save(output_sub_final_filepath)
                matching_subtitles[subtitle_language] = MatchingSubtitle(
                    origin="internal",
                    filepath=output_sub_final_filepath,
                    data=subtitle_data,
                )

            logging.info(f"Matching subtitles: {matching_subtitles}\n")

            # Having matching JP subtitles is required
            if "ja" not in matching_subtitles:
                raise Exception("Could not find Japanese subtitles. Skipping...")

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
                args,
            )

            shutil.rmtree(tmp_output_folder, ignore_errors=True)
            logging.info(f"Finished")

        except Exception:
            logging.error(
                "Something happened processing the anime. Skipping...", exc_info=True
            )
            continue


def split_video_by_subtitles(
    translator, video_file, subtitles, episode_folder_output_path, args
):
    video = mp.VideoFileClip(video_file)

    # # TODO: Sync subtitles calling ffsubsync
    # Use first found internal sub as reference for timing since it should be 100% perfect

    # > From here on just assume all subtitles are perfectly synced
    synced_subtitles = subtitles

    sorted_lines = []
    not_useful_data = ["signs", "tipo tv", "block"]
    for language, subtitles in synced_subtitles.items():
        for line in subtitles.data:
            if line.style.lower() in not_useful_data:
                continue
            sentence = process_subtitle_line(line)
            if sentence:
                sorted_lines.append(
                    {
                        "start": line.start,
                        "end": line.end,
                        "language": language,
                        "sentence": sentence,
                        "actor": line.name,
                    }
                )

    sorted_lines = [dict(t) for t in {tuple(d.items()) for d in sorted_lines}]
    sorted_lines.sort(key=lambda x: x["start"])

    csv_filepath = os.path.join(episode_folder_output_path, "data.csv")
    with open(csv_filepath, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile, fieldnames=EpisodeCsvRow._fields, delimiter=";"
        )
        writer.writeheader()

        segment_start = sorted_lines[0]["start"] - 1
        segment_end = sorted_lines[0]["end"] + 1
        segment_sentences = {}
        for i, line in enumerate(sorted_lines):
            ln = line["language"]
            logging.info(f"[{ln}] Line: {line}")

            # New line when:
            #   * No overlap
            #   * Overlap, but gap is smaller than 500
            if not (segment_start < line["end"] and line["start"] < segment_end) or (
                (segment_start < line["end"] and line["start"] < segment_end)
                and abs(segment_end - line["start"]) < 500
            ):
                logging.info(f"No overlap: {segment_sentences}")
                if "ja" in segment_sentences and (
                    "en" in segment_sentences or "es" in segment_sentences
                ):
                    logging.info("Good match!")

                    generate_segment(
                        i,
                        segment_sentences,
                        segment_start,
                        segment_end,
                        episode_folder_output_path,
                        video,
                        translator,
                        writer,
                        args,
                    )

                segment_sentences = {ln: [line]}
                segment_start = line["start"]
                segment_end = line["end"]

            else:
                segment_sentences[ln] = segment_sentences.get(ln, [])

                # Sometimes when two characters are speaking the same line is repeated several times. Detect that
                # to avoid duplicating the same sentence
                eq_match = False
                for saved_line in segment_sentences[ln]:
                    if (
                        saved_line["sentence"] == line["sentence"]
                        and segment_sentences[ln][-1]["end"] == line["start"]
                    ):
                        eq_match = True

                if not eq_match:
                    segment_sentences[ln].append(line)

                segment_start = min(segment_start, line["start"])
                segment_end = max(segment_end, line["end"])

        logging.info(">> CSV File Completed!!")


def generate_segment(
    i,
    segment_sentences,
    segment_start,
    segment_end,
    output_path,
    video,
    translator,
    writer,
    args,
):
    sentence_japanese, actor_japanese = join_sentences_to_segment(
        segment_sentences["ja"], "ja"
    )
    sentence_english, actor_english = (
        join_sentences_to_segment(segment_sentences["en"], "en")
        if "en" in segment_sentences
        else (None, None)
    )
    sentence_spanish, actor_spanish = (
        join_sentences_to_segment(segment_sentences["es"], "es")
        if "es" in segment_sentences
        else (None, None)
    )

    sentence_spanish_is_mt = False if sentence_spanish else None
    sentence_english_is_mt = False if sentence_english else None

    if translator and not sentence_spanish:
        sentence_spanish = translator.translate_text(
            sentence_japanese, source_lang="JA", target_lang="ES"
        ).text
        sentence_spanish_is_mt = True
        logging.info(f"[DEEPL - SPANISH]: {sentence_spanish}")

    if translator and not sentence_english:
        sentence_english = translator.translate_text(
            sentence_japanese, source_lang="JA", target_lang="EN-US"
        ).text
        sentence_english_is_mt = True
        logging.info(f"[DEEPL - ENGLISH]: {sentence_english}")

    start_time_delta = timedelta(milliseconds=segment_start)
    start_time_seconds = start_time_delta.total_seconds()
    end_time_delta = timedelta(milliseconds=segment_end)
    end_time_seconds = end_time_delta.total_seconds()

    logging.info(f"({i + 1:03d}) {start_time_delta} - {end_time_delta}")
    logging.info(f"[JA] {sentence_japanese}")
    logging.info(f"[EN] {sentence_english}")
    logging.info(f"[ES] {sentence_spanish}")

    audio_filename = f"{i + 1:03d}.mp3"
    screenshot_filename = f"{i + 1:03d}.webp"

    # Audio
    if not args.dryrun:
        try:
            subclip = video.subclip(start_time_seconds, end_time_seconds)
            audio = subclip.audio
            audio_path = os.path.join(output_path, audio_filename)

            audio.write_audiofile(audio_path, codec="mp3")

        except Exception as err:
            logging.exception(f"Error creating audio '{audio_filename}'", err)
            return

        # Screenshot
        try:
            screenshot_path = os.path.join(output_path, screenshot_filename)

            # Take a screenshot on the middle of the dialog
            screenshot_time = (start_time_seconds + end_time_seconds) / 2
            video.save_frame(screenshot_path, t=screenshot_time)

        except Exception as err:
            logging.exception(f"Error creating screenshot '{screenshot_filename}'", err)
            return

    writer.writerow(
        EpisodeCsvRow(
            ID=f"{i + 1:03d}",
            POSITION=f"{i + 1}",
            START_TIME=str(start_time_delta),
            END_TIME=str(end_time_delta),
            NAME_AUDIO=audio_filename,
            NAME_SCREENSHOT=screenshot_filename,
            CONTENT=sentence_japanese,
            CONTENT_TRANSLATION_SPANISH=sentence_spanish,
            CONTENT_TRANSLATION_ENGLISH=sentence_english,
            CONTENT_SPANISH_MT=sentence_spanish_is_mt,
            CONTENT_ENGLISH_MT=sentence_english_is_mt,
            ACTOR_JA=actor_japanese,
            ACTOR_ES=actor_spanish,
            ACTOR_EN=actor_english,
        )._asdict()
    )
    logging.info("Segment saved!\n")


def join_sentences_to_segment(sentences, ln):
    join_symbol = "　" if ln == "ja" else " "
    joined_sentence = join_symbol.join(map(lambda x: x["sentence"].strip(), sentences))

    # On certain cases it makes sense to not add a - since there is another symbol
    # Already indicating the end of the sentence
    remove_redundant_symbols = [
        r"(?<=\.\.\.)-",
        r"(?<=\?)-",
        r"(?<=!)-",
        r"(?<=\.)-",
        r"(?<=,)-",
        r"(?<=ー)-",
        r"(?<=-)-",
        r"^-",
        r"(?<=\s)+\s",
    ]

    # Sometimes japanese subs don't use the appropriate " symbol for quotes
    invalid_quotes = r"``|''"
    joined_sentence = re.sub(invalid_quotes, '"', joined_sentence)

    actor_sentence = ",".join(set(map(lambda x: x["actor"], sentences)))

    return (
        re.sub(rf"{'|'.join(remove_redundant_symbols)}", "", joined_sentence),
        actor_sentence,
    )


def process_subtitle_line(line):
    if line.type != "Dialogue" or (line.name and "sign" in line.name):
        return ""

    # *Top is usually used for background conversations with an ongoing
    # dialog
    if line.style and "top" in line.style.lower():
        return ""

    # Sometimes .ass subtitles include the signs subs on the main dialog
    # Skip all lines that have pos() or move() ass method as it is not a real dialog line
    if re.search(r"pos\(.*?\)|move\(.*?\)", line.text):
        return ""

    # Normaliza half-width (Hankaku) a full-width (Zenkaku) caracteres
    processed_sentence = (
        jaconvV2.normalize(line.plaintext, "NFKC").replace("\n", " ").replace("\r", "")
    )

    special_chars = [
        r"\《.*?\》",
        r"\（.*?\）",
        r"\(.*?\)",
        r"\[.*?\]",
        r"\{.*?\}",
        r"\【.*?\】",
        "●",
        "→",
        "ー?♪ー?",
    ]

    return re.sub(rf"{'|'.join(special_chars)}", "", processed_sentence).strip()


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
        r"\[.*?\]|1080p|720p|BDRip|Dual\s?Audio|x?26[4|5]-?|HEVC|10\sbits|EMBER",
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

        selected_index = 0
        if len(search_results) > 1:
            logging.info("Multiple animes found! Please select better match")
            for i, result in enumerate(search_results):
                try:
                    english_title = result.title.english
                except AttributeError:
                    english_title = "[English Title not available]"
                logging.info(f"[{i}]: {result.title.romaji} - {english_title}")

            selected_index = input("> Please select a number:")

        anime_id = search_results[int(selected_index)].id
        anime_result = self.client.get_anime(anime_id)
        self.cached_results[search_query] = anime_result

        return anime_result


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
    parser.add_argument(
        "-d",
        "--dry-run",
        dest="dryrun",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Execute and parse subtitles, but without generating the segments",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
