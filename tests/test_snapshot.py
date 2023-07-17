import os
from media_sub_splitter.main import split_video_by_subtitles, MatchingSubtitle
import pysubs2


def test_subtitles_snapshots():
    # TODO: Eventually search and load subtitles dynamically.
    # For now just hardocde everything
    matching_subtitles = {}
    matching_subtitles["ja"] = MatchingSubtitle(
        origin="external",
        filepath="tests/snapshots/bocchi-the-rock/bocchi-the-rock-S01E01.jp.srt",
        data=pysubs2.load(
            "tests/snapshots/bocchi-the-rock/bocchi-the-rock-S01E01.jp.srt"
        ),
    )
    matching_subtitles["en"] = MatchingSubtitle(
        origin="external",
        filepath="tests/snapshots/bocchi-the-rock/bocchi-the-rock-S01E01.en.ass",
        data=pysubs2.load(
            "tests/snapshots/bocchi-the-rock/bocchi-the-rock-S01E01.en.ass"
        ),
    )
    matching_subtitles["es"] = MatchingSubtitle(
        origin="external",
        filepath="tests/snapshots/bocchi-the-rock/bocchi-the-rock-S01E01.es.ass",
        data=pysubs2.load(
            "tests/snapshots/bocchi-the-rock/bocchi-the-rock-S01E01.es.ass"
        ),
    )

    split_video_by_subtitles(
        translator=None,
        video_file=None,
        subtitles=matching_subtitles,
        episode_folder_output_path="tests/snapshots/bocchi-the-rock/",
        args={},
        output_csv_name="bocchi-the-rock-S01E01-data.csv",
    )

    assert True
