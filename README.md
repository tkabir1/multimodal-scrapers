# Scrapers

Small Python scrapers for collecting multimodal image-question datasets from public science and education sources.

## Included scrapers

- `cdc/cdc_phil_scraper.py`: collects public-domain image records from the CDC Public Health Image Library.
- `jeopardy/jeopardy_scraper.py`: collects archived Jeopardy! clues and responses into a quiz dataset.
- `jeopardy/jeopardy_show_*_visual_scraper.py`: collect visual-only J-Archive clues from specific shows that include linked image media. The working Jeopardy batch includes shows 6911, 6921, 6929, 6947, 6979, 6983, 6998, 6999, 7000, 7002, and 7103 through 7357.
- `kensquiz/kensquiz_scraper.py`: collects Ken's Quiz road-sign handout questions and cropped image tiles.
- `kensquiz/kensquiz_archive_scraper.py`: collects text-only Ken's Quiz general-knowledge archive questions from 50 validated quiz pages.
- `kensquiz/kensquiz_handout_scraper.py`: collects Ken's Quiz pub quiz handout picture rounds and cropped image tiles.
- `nasa/nasa_apod_scraper.py`: collects Astronomy Picture of the Day image records from NASA into `dataset/images/nasa_apod/`.
- `nasa/nasa_spaceplace_scraper.py`: collects image-based records from NASA Space Place articles.
- `naep/naep_released_visual_questions_scraper.py`: collects all eligible public-domain released NAEP assessment questions with required visuals and official answers or scoring criteria (currently 1,155). It excludes detected third-party copyrighted stimuli and duplicate NAEP item IDs. Use `--max-items` to request a smaller deterministic prefix.
- `nih/niaid_bioart_scraper.py`: collects public NIH BioArt image records.
- `plos/plos_research_figure_scraper.py`: collects peer-reviewed PLOS article figures with questions that combine figure legends and abstracts.
- `quizbowl/quizbowl_picture_rounds_scraper.py`: collects image-based visual bonus questions from multiple real quizbowl packet archive PDFs.
- `quizbowl/quizbowl_tossups_scraper.py`: collects real quizbowl tossups from QB Reader packet data.
- `regents/regents_science_visual_questions_scraper.py`: collects more than 200 visual multiple-choice questions and official answers from archived New York State Regents Living Environment and Earth Science exams. Source pages with detected third-party rights notices are excluded, and records carry NYSED's educational-use restriction and required attribution.
- `sporcle/sporcle_scraper.py`: collects image-backed trivia prompts from a Sporcle slideshow quiz.
- `sporcle/sporcle_*_scraper.py`: collect specific Sporcle slideshow quizzes with image-backed prompts. The working Sporcle batch currently targets 13 quizzes, including the actor series plus `Broken Bones by X-Ray` and `Animals with David Attenborough`.
- `wikipedia/wikipedia_biology_scraper.py`: collects biology-related image records from Wikipedia.

## Output files

Each scraper writes JSON into `dataset/`. For image-backed sources, remote media is downloaded into `dataset/images/<source>/`, the main `image_url` or `media_url` field is rewritten to the local file path, and the original remote URL is preserved in `source_image_url` or `source_media_url`. Text-only sources such as the QB Reader tossup scraper are marked with `"media_type": "text"` and do not have an image directory. The quiz scrapers preserve imported prompt text from their sources, and the reasoning-oriented datasets are intended to require combining the prompt with the visual or source context rather than defaulting to simple "what is shown?" identification prompts.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 pdfplumber pdf2image pillow
```

2. Copy the example environment file and fill in any values you need:

```bash
cp .env.example .env
```

- `NASA_API_KEY` is optional. If it is not set, the APOD scraper falls back to NASA's `DEMO_KEY`, which has stricter rate limits.
- `SCRAPER_CONTACT_EMAIL` is optional but recommended for polite request headers.
- `kensquiz/kensquiz_scraper.py` requires Poppler so `pdf2image` can rasterize the handout PDFs.

## Running the scrapers

```bash
python3 cdc/cdc_phil_scraper.py
python3 jeopardy/jeopardy_scraper.py
python3 jeopardy/jeopardy_show_7124_visual_scraper.py
python3 kensquiz/kensquiz_archive_scraper.py
python3 kensquiz/kensquiz_scraper.py
python3 kensquiz/kensquiz_handout_scraper.py
python3 nasa/nasa_apod_scraper.py
python3 nasa/nasa_spaceplace_scraper.py
python3 naep/naep_released_visual_questions_scraper.py
python3 nih/niaid_bioart_scraper.py
python3 plos/plos_research_figure_scraper.py
python3 quizbowl/quizbowl_picture_rounds_scraper.py
python3 quizbowl/quizbowl_tossups_scraper.py
python3 regents/regents_science_visual_questions_scraper.py
python3 sporcle/sporcle_scraper.py
python3 wikipedia/wikipedia_biology_scraper.py
```

Use additional Jeopardy visual-clue scrapers by running the matching file in `jeopardy/`, for example `python3 jeopardy/jeopardy_show_7116_visual_scraper.py`.
Use additional Sporcle slideshow scrapers by running the matching file in `sporcle/`, for example `python3 sporcle/sporcle_actors_through_three_decades_on_tv_iv_scraper.py`.

## Validating local assets

Run this before pushing dataset changes:

```bash
python3 tools/validate_dataset_assets.py
```

The validator fails if an image-backed record points at a missing local file or a remote URL. Text-only datasets such as `dataset/quizbowl_tossups.json` pass when their records include `"media_type": "text"`.
