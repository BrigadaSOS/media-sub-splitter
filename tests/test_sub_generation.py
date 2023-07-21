import os


import pytest

from media_sub_splitter.main import split_video_by_subtitles

from .conftest import read_subtitles_from_folders


@pytest.mark.parametrize(
    "matching_subtitles", read_subtitles_from_folders("tests/input/")
)
def test_subtitles_snapshots(snapshot, matching_subtitles):
    sample_subtitles_filepath = getattr(matching_subtitles["ja"], "filepath")

    snapshot.snapshot_dir = "tests/snapshots"
    tmp_output_folder = "tests/snapshots/tmp"
    filename = os.path.basename(sample_subtitles_filepath).split(".")[0]
    tmp_tsv_filename = f"{filename}.input.tsv"

    split_video_by_subtitles(
        translator=None,
        video_file=None,
        subtitles=matching_subtitles,
        episode_folder_output_path=tmp_output_folder,
        args={},
        output_tsv_name=tmp_tsv_filename,
    )

    with open(os.path.join(tmp_output_folder, tmp_tsv_filename)) as tsvfile:
        text = "".join(tsvfile.readlines())

        snapshot_filename = f"{filename}.snapshot.tsv"
        snapshot.assert_match(text, snapshot_filename)
