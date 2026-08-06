import argparse
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import requests
from pdf2image import convert_from_path
from PIL import ImageOps


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT_DIR / "dataset/regents_science_visual_questions.json"
IMAGES_DIR = ROOT_DIR / "dataset/images/regents_science"
CACHE_DIR = ROOT_DIR / ".cache/regents"

REQUEST_TIMEOUT = 60
RENDER_DPI = 180
TERMS_URL = "https://www.nysed.gov/terms-of-use"
CONTACT_EMAIL = os.getenv("SCRAPER_CONTACT_EMAIL", "rohanarun@users.noreply.github.com").strip()
RIGHTS_NOTICE = re.compile(
    r"(?:©|\bcopyright\b|\bsource\s*:|\bcourtesy of\b|\bused by permission\b)",
    re.IGNORECASE,
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": f"RegentsScienceVisualScraper/1.0 (contact: {CONTACT_EMAIL})",
        "Accept-Language": "en-US,en;q=0.9",
    }
)


@dataclass(frozen=True)
class VisualQuestionSet:
    page: int
    questions: tuple[int, ...]
    reasoning_focus: str


@dataclass(frozen=True)
class Exam:
    slug: str
    subject: str
    administration: str
    exam_url: str
    scoring_guide_url: str
    question_sets: tuple[VisualQuestionSet, ...]


def visual_sets(
    values: tuple[tuple[int, tuple[int, ...]], ...],
    focus: str,
) -> tuple[VisualQuestionSet, ...]:
    return tuple(VisualQuestionSet(page, questions, focus) for page, questions in values)


EXAMS = (
    Exam(
        slug="living_environment_2018_06",
        subject="Living Environment",
        administration="June 2018",
        exam_url="https://www.nysedregents.org/LivingEnvironment/618/lenv62018-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/LivingEnvironment/618/lenv62018-rg.pdf",
        question_sets=(
            VisualQuestionSet(3, (11,), "nutrient_cycle_diagram_reasoning"),
            VisualQuestionSet(4, (12,), "biological_process_diagram_reasoning"),
            VisualQuestionSet(6, (22,), "genetic_engineering_diagram_reasoning"),
            VisualQuestionSet(7, (24,), "food_web_reasoning"),
            VisualQuestionSet(8, (30,), "energy_pyramid_reasoning"),
            VisualQuestionSet(10, (33,), "microscope_field_reasoning"),
            VisualQuestionSet(12, (41, 42, 43), "cell_process_diagram_reasoning"),
            VisualQuestionSet(16, (49,), "evolutionary_tree_reasoning"),
            VisualQuestionSet(17, (50,), "trophic_level_diagram_reasoning"),
            VisualQuestionSet(25, (73,), "plant_transport_diagram_reasoning"),
            VisualQuestionSet(26, (76,), "osmosis_setup_reasoning"),
            VisualQuestionSet(30, (82,), "membrane_transport_diagram_reasoning"),
        ),
    ),
    Exam(
        slug="earth_science_2018_06",
        subject="Physical Setting/Earth Science",
        administration="June 2018",
        exam_url="https://www.nysedregents.org/EarthScience/618/esci62018-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/EarthScience/618/esci62018-rg.pdf",
        question_sets=(
            VisualQuestionSet(3, (9,), "lunar_orbit_diagram_reasoning"),
            VisualQuestionSet(4, (10,), "spectral_line_comparison"),
            VisualQuestionSet(5, (12, 13), "constellation_diagram_reasoning"),
            VisualQuestionSet(6, (18,), "topographic_cross_section_reasoning"),
            VisualQuestionSet(7, (20,), "water_cycle_diagram_reasoning"),
            VisualQuestionSet(8, (21,), "climate_table_reasoning"),
            VisualQuestionSet(9, (23, 24), "relative_geologic_age_reasoning"),
            VisualQuestionSet(10, (30,), "soil_profile_reasoning"),
            VisualQuestionSet(11, (32, 33), "landscape_and_map_reasoning"),
            VisualQuestionSet(12, (34, 35), "depositional_feature_reasoning"),
            VisualQuestionSet(13, (36, 37, 38, 39), "astronomical_diagram_reasoning"),
            VisualQuestionSet(14, (40, 41, 42), "stellar_evolution_diagram_reasoning"),
            VisualQuestionSet(15, (43, 44), "radioactive_decay_graph_reasoning"),
            VisualQuestionSet(16, (45, 46, 47), "weather_diagram_reasoning"),
            VisualQuestionSet(17, (48, 49, 50), "topographic_map_reasoning"),
        ),
    ),
    Exam(
        slug="living_environment_2018_08",
        subject="Living Environment",
        administration="August 2018",
        exam_url="https://www.nysedregents.org/LivingEnvironment/818/lenv82018-exampw.pdf",
        scoring_guide_url="https://www.nysedregents.org/LivingEnvironment/818/lenv82018-rg.pdf",
        question_sets=visual_sets(
            (
                (2, (1, 4, 5, 6)),
                (9, (33, 34)),
                (11, (37, 38, 39)),
                (12, (40,)),
                (13, (41, 42)),
                (14, (43,)),
                (16, (47, 49)),
                (25, (73,)),
                (26, (75, 76)),
                (30, (82,)),
            ),
            "regents_visual_science_reasoning",
        ),
    ),
    Exam(
        slug="living_environment_2018_01",
        subject="Living Environment",
        administration="January 2018",
        exam_url="https://www.nysedregents.org/LivingEnvironment/118/lenv12018-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/LivingEnvironment/118/lenv12018-rg.pdf",
        question_sets=visual_sets(
            (
                (2, (3,)),
                (3, (8,)),
                (4, (13, 18)),
                (7, (31, 32, 33)),
                (9, (37,)),
                (10, (39, 40)),
                (11, (42,)),
                (12, (47,)),
                (22, (74,)),
                (23, (75, 76)),
                (25, (81, 82)),
            ),
            "regents_visual_science_reasoning",
        ),
    ),
    Exam(
        slug="living_environment_2017_08",
        subject="Living Environment",
        administration="August 2017",
        exam_url="https://www.nysedregents.org/LivingEnvironment/817/lenv82017-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/LivingEnvironment/817/lenv82017-rg.pdf",
        question_sets=visual_sets(
            (
                (3, (10,)),
                (4, (15, 16, 17)),
                (5, (18, 22)),
                (6, (24, 27)),
                (9, (36, 37)),
                (10, (38, 39, 40)),
                (11, (41, 42, 43)),
                (12, (47,)),
                (14, (49,)),
                (15, (50,)),
                (24, (73,)),
                (25, (75,)),
                (26, (76,)),
            ),
            "regents_visual_science_reasoning",
        ),
    ),
    Exam(
        slug="living_environment_2017_06",
        subject="Living Environment",
        administration="June 2017",
        exam_url="https://www.nysedregents.org/LivingEnvironment/617/lenv62017-exampcw.pdf",
        scoring_guide_url="https://www.nysedregents.org/LivingEnvironment/617/lenv62017-rgc.pdf",
        question_sets=visual_sets(
            (
                (2, (1,)),
                (7, (31,)),
                (8, (33,)),
                (9, (37, 38, 39)),
                (10, (40, 41)),
                (11, (42,)),
                (12, (47,)),
                (14, (49, 50)),
                (22, (75, 76)),
                (24, (81, 82)),
            ),
            "regents_visual_science_reasoning",
        ),
    ),
    Exam(
        slug="living_environment_2017_01",
        subject="Living Environment",
        administration="January 2017",
        exam_url="https://www.nysedregents.org/LivingEnvironment/117/lenv12017-exam.pdf",
        scoring_guide_url="https://www.nysedregents.org/LivingEnvironment/117/lenv12017-rg.pdf",
        question_sets=visual_sets(
            (
                (4, (16, 17, 18)),
                (5, (20,)),
                (6, (26, 28)),
                (7, (29, 30)),
                (8, (31, 32)),
                (9, (36, 37, 38)),
                (10, (40, 41)),
                (11, (42, 43)),
                (12, (47,)),
                (15, (50,)),
                (23, (73,)),
                (24, (75,)),
                (26, (81,)),
                (27, (82,)),
            ),
            "regents_visual_science_reasoning",
        ),
    ),
    Exam(
        slug="earth_science_2018_08",
        subject="Physical Setting/Earth Science",
        administration="August 2018",
        exam_url="https://www.nysedregents.org/EarthScience/818/esci82018-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/EarthScience/818/esci82018-rg2.pdf",
        question_sets=visual_sets(
            (
                (2, (1,)),
                (3, (7, 14)),
                (4, (15,)),
                (5, (24,)),
                (6, (29,)),
                (7, (31, 32)),
                (8, (33, 34)),
                (10, (36, 37, 38)),
                (12, (39, 40, 41)),
                (13, (42, 43, 44)),
                (14, (45, 46, 47)),
                (16, (48, 49, 50)),
            ),
            "regents_visual_earth_science_reasoning",
        ),
    ),
    Exam(
        slug="earth_science_2018_01",
        subject="Physical Setting/Earth Science",
        administration="January 2018",
        exam_url="https://www.nysedregents.org/EarthScience/118/esci12018-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/EarthScience/118/esci12018-rg.pdf",
        question_sets=visual_sets(
            (
                (2, (1,)),
                (3, (8,)),
                (4, (10,)),
                (5, (19, 20)),
                (6, (24,)),
                (7, (30,)),
                (8, (32, 33)),
                (9, (34, 35)),
                (11, (38, 39, 40)),
                (13, (45, 46, 47)),
                (14, (48, 49, 50)),
            ),
            "regents_visual_earth_science_reasoning",
        ),
    ),
    Exam(
        slug="earth_science_2017_08",
        subject="Physical Setting/Earth Science",
        administration="August 2017",
        exam_url="https://www.nysedregents.org/EarthScience/817/esci82017-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/EarthScience/817/esci82017-rg.pdf",
        question_sets=visual_sets(
            (
                (2, (1, 2)),
                (3, (9, 12)),
                (4, (20, 23)),
                (5, (26, 27)),
                (6, (30,)),
                (7, (32, 33)),
                (8, (34, 35)),
                (9, (36, 37, 38)),
                (10, (39, 40, 41)),
                (11, (42, 43)),
                (12, (44, 45)),
                (13, (46,)),
                (14, (47, 48, 49, 50)),
            ),
            "regents_visual_earth_science_reasoning",
        ),
    ),
    Exam(
        slug="earth_science_2017_06",
        subject="Physical Setting/Earth Science",
        administration="June 2017",
        exam_url="https://www.nysedregents.org/EarthScience/617/esci62017-exampwr.pdf",
        scoring_guide_url="https://www.nysedregents.org/EarthScience/617/esci62017-rg.pdf",
        question_sets=visual_sets(
            (
                (2, (1,)),
                (3, (8, 11, 12)),
                (4, (14, 15, 16)),
                (5, (19, 25)),
                (6, (26, 27, 31)),
                (7, (33,)),
                (8, (34, 35)),
                (9, (36, 37, 38)),
                (10, (39, 40)),
                (12, (43, 44)),
                (14, (45, 46, 47, 48)),
                (16, (49, 50)),
            ),
            "regents_visual_earth_science_reasoning",
        ),
    ),
    Exam(
        slug="earth_science_2017_01",
        subject="Physical Setting/Earth Science",
        administration="January 2017",
        exam_url="https://www.nysedregents.org/EarthScience/117/esci12017-examw.pdf",
        scoring_guide_url="https://www.nysedregents.org/EarthScience/117/esci12017-rg.pdf",
        question_sets=visual_sets(
            (
                (2, (1,)),
                (3, (8, 11)),
                (4, (18, 19, 20)),
                (5, (25, 26)),
                (6, (33,)),
                (7, (34,)),
                (8, (35,)),
                (9, (36, 37, 38)),
                (10, (39, 40)),
                (11, (41, 42, 43, 44)),
                (13, (48, 49, 50)),
            ),
            "regents_visual_earth_science_reasoning",
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect visual question sets and official answers from archived NYSED Regents science exams."
    )
    parser.add_argument("--refresh", action="store_true", help="Redownload cached source PDFs.")
    parser.add_argument("--max-items", type=int, default=None)
    return parser.parse_args()


def download(url: str, path: Path, refresh: bool) -> Path:
    if path.exists() and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True) as response:
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            for chunk in response.iter_content(chunk_size=1024 * 128):
                handle.write(chunk)
    temporary_path.replace(path)
    return path


def clean_page_text(value: str) -> str:
    lines = []
    for line in value.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if re.search(r"(?:Living Environment|P\.S\./Earth Science).*\[\d+\]", line, re.IGNORECASE):
            continue
        if line in {"[OVER]", "GO ON TO THE NEXT PAGE", "➯"}:
            continue
        lines.append(line)
    return "\n".join(lines)


def parse_multiple_choice_answers(scoring_guide: Path) -> dict[int, str]:
    with pdfplumber.open(scoring_guide) as pdf:
        text = pdf.pages[0].extract_text() or ""
    answers = {
        int(question): choice
        for question, choice in re.findall(
            r"(?m)(\d{1,2})\s*\.\s*(?:\.\s*){2,}(\d)",
            text,
        )
    }
    if len(answers) < 40:
        raise RuntimeError(f"Could not parse the multiple-choice key from {scoring_guide}")
    return answers


def render_page(exam_pdf: Path, page: int, output_path: Path) -> None:
    rendered = convert_from_path(
        exam_pdf,
        dpi=RENDER_DPI,
        first_page=page,
        last_page=page,
        fmt="png",
        thread_count=1,
    )
    if len(rendered) != 1:
        raise RuntimeError(f"Expected one rendered page for page {page} of {exam_pdf}")
    image = rendered[0].convert("RGB")
    border = max(8, round(image.width * 0.018))
    image = ImageOps.crop(image, (border, border, border, border))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)


def record_for_question(
    exam: Exam,
    question_set: VisualQuestionSet,
    question_number: int,
    page_text: str,
    answers: dict[int, str],
    sequence: int,
) -> dict:
    local_path = (
        f"dataset/images/regents_science/{exam.slug}_page_{question_set.page:02d}.png"
    )
    return {
        "id": f"regents_science_{sequence:04d}",
        "question": (
            f"Using the official source-authored exam page shown, answer Regents "
            f"question {question_number}."
        ),
        "answer": f"Choice {answers[question_number]}",
        "image_url": local_path,
        "media_type": "image",
        "source": "nysed_regents_science",
        "source_url": exam.exam_url,
        "source_scoring_guide_url": exam.scoring_guide_url,
        "source_page": question_set.page,
        "source_question_number": question_number,
        "source_page_text": page_text,
        "subject": exam.subject,
        "administration": exam.administration,
        "item_type": "multiple_choice",
        "license": (
            "NYSED permits copying, use, and distribution for personal, private, and "
            "educational purposes with attribution. Commercial use requires prior written permission."
        ),
        "rights_url": TERMS_URL,
        "attribution": (
            "New York State Education Department, archived Regents Examination, "
            f"{exam.subject}, {exam.administration}."
        ),
        "reasoning_focus": question_set.reasoning_focus,
    }


def remove_unreferenced_assets(records: list[dict]) -> int:
    referenced = {Path(record["image_url"]).name for record in records}
    removed = 0
    for path in IMAGES_DIR.glob("*.png"):
        if path.name not in referenced:
            path.unlink()
            removed += 1
    return removed


def main() -> int:
    args = parse_args()
    if args.max_items is not None and args.max_items < 1:
        raise SystemExit("--max-items must be positive")

    records = []
    for exam in EXAMS:
        exam_pdf = download(
            exam.exam_url,
            CACHE_DIR / f"{exam.slug}_exam.pdf",
            args.refresh,
        )
        scoring_guide = download(
            exam.scoring_guide_url,
            CACHE_DIR / f"{exam.slug}_scoring_guide.pdf",
            args.refresh,
        )
        answers = parse_multiple_choice_answers(scoring_guide)
        with pdfplumber.open(exam_pdf) as pdf:
            for question_set in exam.question_sets:
                if args.max_items is not None and len(records) >= args.max_items:
                    break
                missing = [number for number in question_set.questions if number not in answers]
                if missing:
                    raise RuntimeError(f"Missing answers for {exam.slug}: {missing}")
                page_text = clean_page_text(pdf.pages[question_set.page - 1].extract_text() or "")
                if RIGHTS_NOTICE.search(page_text):
                    print(
                        f"Skipping {exam.slug} page {question_set.page}: detected a third-party rights notice."
                    )
                    continue
                local_path = (
                    f"dataset/images/regents_science/"
                    f"{exam.slug}_page_{question_set.page:02d}.png"
                )
                output_path = ROOT_DIR / local_path
                if not output_path.exists() or args.refresh:
                    render_page(exam_pdf, question_set.page, output_path)
                for question_number in question_set.questions:
                    if args.max_items is not None and len(records) >= args.max_items:
                        break
                    sequence = len(records) + 1
                    records.append(
                        record_for_question(
                            exam,
                            question_set,
                            question_number,
                            page_text,
                            answers,
                            sequence,
                        )
                    )
        if args.max_items is not None and len(records) >= args.max_items:
            break

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    removed = remove_unreferenced_assets(records)
    print(f"Wrote {len(records)} records to {OUTPUT_JSON.relative_to(ROOT_DIR)}.")
    if removed:
        print(f"Removed {removed} unreferenced Regents image assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
