# Media Sub Splitter

Split an input video onto separate audio segments with images.


## How to use

Create and activate a new Python environment:

```
python3 -m venv .venv && source .venv/bin/activate
```

Install dependencies:
```
pip3 install -r requirements.txt
```

Run with:
```
python3 main.py -t <DEEPL_TOKEN> <input_folder> <output_folder>
```

The DeepL token can also be set as an Environment Variable or on a `.env` file (see
`.env.example`)
