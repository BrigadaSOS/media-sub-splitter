# Media Sub Splitter

Split an input video onto separate audio segments with images.


## Setup

Create and activate a new Python environment:

```
python3 -m venv .venv && source .venv/bin/activate
```

Install dependencies:
```
pip3 install -r requirements.txt
```

(Optional) Install dev dependencies:
```
pip3 install -r requirements-dev.txt
```

## Use

Run with:
```
python3 -m media_sub_splitter -t <DEEPL_TOKEN> <input_folder> <output_folder>
```

Run the `--help` command for more information


The DeepL token can also be set as an Environment Variable or on a `.env` file (see
`.env.example`)


## Tests

The application uses snapshot tests to make sure that the generated subtitles stay
consistent between updates.

To run the tests:

```
pytest
```

To regenerate snapshots after a change:
```
pytest --snapshot-update
```
