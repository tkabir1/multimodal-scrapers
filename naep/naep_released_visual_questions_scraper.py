import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps, UnidentifiedImageError


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT_DIR / "dataset/naep_released_visual_questions.json"
IMAGES_DIR = ROOT_DIR / "dataset/images/naep"
CACHE_DIR = ROOT_DIR / ".cache/naep"

BASE_URL = "https://www.nationsreportcard.gov/nqt"
API_URL = f"{BASE_URL}/api"
SUBJECTS = ("SCI", "GEO", "MAT", "TEL", "CIV", "HIS", "ECN", "ART", "RED", "WRI")
SUBJECT_LABELS = {
    "ART": "Arts",
    "CIV": "Civics",
    "ECN": "Economics",
    "GEO": "Geography",
    "HIS": "U.S. History",
    "MAT": "Mathematics",
    "RED": "Reading",
    "SCI": "Science",
    "TEL": "Technology and Engineering Literacy",
    "WRI": "Writing",
}

CONTACT_EMAIL = os.getenv("SCRAPER_CONTACT_EMAIL", "rohanarun@users.noreply.github.com").strip()
MAX_RETRIES = 4
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
REQUEST_TIMEOUT = 60

VISUAL_TERMS = re.compile(
    r"\b(?:diagram|graph|chart|map|table|figure|picture|photograph|photo|drawing|illustration|"
    r"number line|coordinate plane|grid|geometric|geometry|shape|angle|triangle|rectangle|circle|"
    r"polygon|solid|cube|prism|pyramid|clock|ruler|scale|thermometer|model|design|cartoon|poster|"
    r"banner|advertisement|timeline|scatterplot|histogram|bar graph|line graph|pie chart|floor plan|"
    r"blueprint|musical notation|sheet music|painting|self-portrait|portrait|print|logo|symbol|"
    r"pattern|array|matrix|tree diagram|circuit|food web|rock cycle|water cycle|solar system|"
    r"microscope|specimen|x-ray|satellite image|cross section|shown above|shown below|shown here|"
    r"pictured|look at the|based on the visual|use the visual)\b",
    re.IGNORECASE,
)
TEXT_SCREENSHOT_TERMS = re.compile(
    r"^(?:screen\s*shot|screenshot) of (?:an? )?(?:interactive )?question[.:\s]*",
    re.IGNORECASE,
)
RIGHTS_TERMS = re.compile(
    r"(?:©|\bcopyright\b|shutterstock|getty images?|alamy|associated press|photo courtesy|"
    r"courtesy of|used by permission|permission of|all rights reserved)",
    re.IGNORECASE,
)
THIRD_PARTY_RIGHTS_TERMS = re.compile(
    r"(?:©|copyright\s*\([cC]\)|shutterstock|getty images?|alamy|associated press|"
    r"photo courtesy|courtesy of|used by permission|reproduced with permission|"
    r"all rights reserved|further copying or distribution)",
    re.IGNORECASE,
)
PUBLIC_DOMAIN_TERMS = re.compile(r"\bpublic domain\b", re.IGNORECASE)
UNAVAILABLE_SCORE_TERMS = re.compile(
    r"scoring guide (?:is )?not available|no scoring guide|not available for this item",
    re.IGNORECASE,
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": f"NAEPVisualQuestionScraper/1.0 (contact: {CONTACT_EMAIL})",
        "Accept-Language": "en-US,en;q=0.9",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect public-domain, source-authored visual questions and scoring guides from NAEP."
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Stop after this many eligible items (default: collect every eligible item).",
    )
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--refresh", action="store_true", help="Ignore cached API responses.")
    parser.add_argument("--inventory-only", action="store_true", help="Report eligible candidates without downloading media.")
    return parser.parse_args()


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def cache_path(namespace: str, key: str, suffix: str = ".json") -> Path:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)
    return CACHE_DIR / namespace / f"{safe_key}{suffix}"


def request(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    expect_json: bool = False,
) -> Any:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.request(method, url, json=json_body, timeout=REQUEST_TIMEOUT)
            if response.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else attempt
                response.close()
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json() if expect_json else response.text
        except (requests.RequestException, ValueError) as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Request failed for {url}: {exc}") from exc
            time.sleep(attempt)
    raise RuntimeError(f"Request failed for {url}")


def cached_json(namespace: str, key: str, fetcher: Any, refresh: bool) -> Any:
    path = cache_path(namespace, key)
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    value = fetcher()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def cached_text(namespace: str, key: str, fetcher: Any, refresh: bool) -> str:
    path = cache_path(namespace, key, ".html")
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    value = str(fetcher())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


def selected_subject(subject: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(subject))
    copied["isSelected"] = True
    for grade in copied.get("gradeList", []):
        grade["isSelected"] = True
    return copied


def fetch_subject_items(subject: str, all_info: dict[str, Any], refresh: bool) -> list[dict[str, Any]]:
    subject_info = next(item for item in all_info["subjectGradeInfo"] if item["subject"] == subject)
    grades = ",".join(item["grade"] for item in subject_info["gradeList"])
    selector = {"SubjectCode": subject, "GradeStr": grades, "SystemID": "1", "SelectedYearSamples": []}
    filters = cached_json(
        "filters",
        subject,
        lambda: request("POST", f"{API_URL}/querypanel/subjectgradeinfo", json_body=selector, expect_json=True),
        refresh,
    )
    item_request = {
        "SubjectCode": subject,
        "GradeStr": grades,
        "SystemID": "1",
        "SubjectGradeInfo": [selected_subject(subject_info)],
        "YearsInfo": [{**item, "isSelected": True} for item in filters.get("yearsInfo", [])],
        "LimitToOnlineItems": False,
        "ContentClassifications": filters.get("contentClassifications"),
        "ItemTypes": filters.get("itemTypes", []),
        "DifficultyInfo": filters.get("difficultyInfo", []),
        "CalculatorInfo": None,
    }
    tabular = cached_json(
        "tabular",
        subject,
        lambda: request(
            "POST", f"{API_URL}/queryresults/getTabular", json_body=item_request, expect_json=True
        ),
        refresh,
    )
    return tabular.get("gridItemsList", [])


def fetch_item_detail(item_id: int, refresh: bool) -> dict[str, Any]:
    return cached_json(
        "items",
        str(item_id),
        lambda: request(
            "GET", f"{API_URL}/queryresults/GetItem?tableID={item_id}", expect_json=True
        ),
        refresh,
    )


def fetch_score_guide(item_id: int, refresh: bool) -> str:
    return cached_text(
        "scores",
        str(item_id),
        lambda: request("GET", f"{API_URL}/queryresults/GetItemScoreGuide?tableID={item_id}"),
        refresh,
    )


def has_disallowed_rights(markup: str) -> bool:
    soup = BeautifulSoup(markup, "html.parser")
    notices = [node.get_text(" ", strip=True) for node in soup.select(".copyright")]
    full_text = clean_text(soup.get_text(" ", strip=True))
    if THIRD_PARTY_RIGHTS_TERMS.search(full_text):
        return True
    suspicious = notices or RIGHTS_TERMS.search(full_text)
    if not suspicious:
        return False
    suspicious_text = " ".join(notices) if notices else full_text
    return not bool(PUBLIC_DOMAIN_TERMS.search(suspicious_text))


def resource_urls(markup: str) -> list[str]:
    soup = BeautifulSoup(markup, "html.parser")
    urls: list[str] = []
    for image in soup.find_all("img", src=True):
        url = image["src"].strip()
        if url.startswith("/"):
            url = f"https://www.nationsreportcard.gov{url}"
        if urlparse(url).scheme in {"http", "https"} and url not in urls:
            urls.append(url)
    return urls


def image_alt_texts(markup: str) -> list[str]:
    soup = BeautifulSoup(markup, "html.parser")
    return [clean_text(image.get("alt")) for image in soup.find_all("img") if clean_text(image.get("alt"))]


def visible_item_text(markup: str) -> str:
    soup = BeautifulSoup(markup, "html.parser")
    for node in soup.select("script, style, .copyright"):
        node.decompose()
    for image in soup.find_all("img"):
        image.decompose()
    return clean_text(soup.get_text(" ", strip=True))


def strip_accessibility_descriptions(value: str) -> str:
    value = re.sub(
        r"\[(?:an? |the )?(?:image|figure|diagram|photo|table|graph)[^\]]*\]",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:The )?(?:figure|image|diagram|table|graph) shows\b.*?\bEnd (?:of )?(?:the )?"
        r"(?:figure|image|diagram|table|graph) description\.?",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    description = re.search(
        r"\b(?:The )?(?:image|figure|diagram|table|graph) "
        r"(?:shows|is of|is shown|is labeled)\b",
        value,
        re.IGNORECASE,
    )
    if description:
        prefix = clean_text(value[: description.start()])
        if len(prefix) >= 20:
            value = prefix
        else:
            suffix = value[description.end() :]
            question = re.search(
                r"[.!?]\s+((?:Which|What|How|Why|According|Based|Select|Choose|Drag|Complete|"
                r"Determine|Identify|Explain)\b.*)",
                suffix,
            )
            value = clean_text(f"{prefix} {question.group(1) if question else ''}")
    return clean_text(value)


def question_from_alt(alt: str) -> str:
    value = clean_text(alt)
    value = TEXT_SCREENSHOT_TERMS.sub("", value)
    markers = list(re.finditer(r"\bquestion(?: text)?\s*[:.]\s*", value, re.IGNORECASE))
    if markers:
        value = value[markers[-1].end() :]
    value = re.sub(r"\[(?:image|figure|diagram|photo)[^\]]*\]", " ", value, flags=re.IGNORECASE)
    return strip_accessibility_descriptions(value)


def extract_question(markup: str) -> str:
    visible = visible_item_text(markup)
    alts = image_alt_texts(markup)
    marked_alts = [
        value
        for value in alts
        if re.search(r"\bquestion(?: text)?\s*[:.]", value, re.IGNORECASE)
    ]
    if marked_alts:
        questions = [question_from_alt(value) for value in marked_alts]
        questions = [value for value in questions if len(value) >= 20]
        if questions:
            return max(questions, key=len)
    if len(visible) >= 35 and re.search(r"[?.]", visible):
        return visible
    alt_questions = [question_from_alt(value) for value in alts]
    alt_questions = [value for value in alt_questions if len(value) >= 20]
    return max(alt_questions, key=len, default=visible)


def requires_visual(item: dict[str, Any], markup: str) -> bool:
    urls = resource_urls(markup)
    if not urls:
        return False
    soup = BeautifulSoup(markup, "html.parser")
    alts = image_alt_texts(markup)
    visible = visible_item_text(markup)
    image = soup.find("img")
    try:
        width = int(image.get("width") or 0) if image else 0
        height = int(image.get("height") or 0) if image else 0
    except ValueError:
        width = height = 0
    if (
        len(urls) == 1
        and item.get("subject") in {"TEL", "CIV", "HIS", "RED", "WRI", "ECN"}
        and width <= 32
        and height <= 32
    ):
        return False
    evidence = " ".join([str(item.get("description", "")), visible, *alts])
    if VISUAL_TERMS.search(evidence):
        return True
    if len(urls) >= 2:
        return True
    if image:
        # A lone screenshot containing only ordinary text is not multimodal.
        if width and height and width < 260 and height < 260:
            return True
    return False


def score_text(markup: str) -> str:
    soup = BeautifulSoup(markup, "html.parser")
    image_descriptions = [clean_text(image.get("alt")) for image in soup.find_all("img")]
    for image in soup.find_all("img"):
        image.replace_with(" " + clean_text(image.get("alt")) + " ")
    text = clean_text(soup.get_text(" ", strip=True))
    if image_descriptions and not text:
        text = clean_text(" ".join(image_descriptions))
    return text


def extract_answer(markup: str) -> str | None:
    soup = BeautifulSoup(markup, "html.parser")
    text = score_text(markup)
    if not text or UNAVAILABLE_SCORE_TERMS.search(text):
        return None
    patterns = (
        r"The correct answer is:\s*(.+?)(?=\s+(?:Score|Scoring|Additional)\b|$)",
        r"Correct (?:answer|selection|selections):\s*(.+?)"
        r"(?=\s+(?:Score|Scoring|Complete|Partial)\b|$)",
        r"Sample Correct Response:\s*(.+?)(?=\s+(?:Score and Description|Scoring Guide)\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            answer = clean_text(match.group(1))
            if answer and "no alt text" not in answer.lower():
                return answer[:2000]
            return None
    score_parts = soup.select_one(".scoreparts")
    if score_parts:
        header = score_parts.find("p", recursive=False)
        if header:
            parts = [clean_text(header.get_text(" ", strip=True))]
            for sibling in header.next_siblings:
                if getattr(sibling, "name", None) == "p":
                    break
                if hasattr(sibling, "get_text"):
                    value = clean_text(sibling.get_text(" ", strip=True))
                    if value:
                        parts.append(value)
            additional = soup.select_one(".addlCmts")
            if additional:
                value = clean_text(additional.get_text(" ", strip=True))
                if value:
                    parts.append(value)
            rubric_answer = clean_text(f"{parts[0]}: {' '.join(parts[1:])}")
            if rubric_answer and "no alt text" not in rubric_answer.lower():
                return rubric_answer[:2000]
            return None
    highest_category = re.search(
        r"Score and Description\s+(Excellent|Complete|Extended|Correct|Satisfactory)\s+(.+?)"
        r"(?=\s+(?:Skillful|Complete|Satisfactory|Partial|Essential|Acceptable|Uneven|"
        r"Insufficient|Unsatisfactory|Incorrect|Score \d)\b|$)",
        text,
        re.IGNORECASE,
    )
    if highest_category:
        return clean_text(f"{highest_category.group(1)}: {highest_category.group(2)}")[:2000]
    complete = re.search(
        r"\b(?:Complete|Correct)\b\s+(?:Response\s+)?(.+?)(?=\s+(?:Partial|Essential|Acceptable|"
        r"Unsatisfactory|Incorrect|Score \d|$))",
        text,
        re.IGNORECASE,
    )
    if complete:
        return clean_text(complete.group(1))[:2000]
    if clean_text(text).lower() in {"no alt text", "solution: no alt text"}:
        return None
    return text[:2000] if len(text) >= 15 else None


def candidate_from_item(item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any] | None:
    markup = str(detail.get("itemHTML") or "")
    if not markup or has_disallowed_rights(markup) or not requires_visual(item, markup):
        return None
    question = extract_question(markup)
    urls = resource_urls(markup)
    if len(question) < 20 or len(question) > 3000 or not urls:
        return None
    return {
        "item": item,
        "detail": detail,
        "question": question,
        "resource_urls": urls,
        "alt_texts": image_alt_texts(markup),
    }


def download_bytes(url: str) -> bytes:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                time.sleep(attempt)
                continue
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Could not download {url}: {exc}") from exc
            time.sleep(attempt)
    raise RuntimeError(f"Could not download {url}")


def load_raster(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.seek(0)
        image.load()
        return image.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"Unsupported NAEP image resource: {exc}") from exc


def localize_visual(urls: list[str], output_path: Path) -> None:
    images = [load_raster(download_bytes(url)) for url in urls]
    normalized: list[Image.Image] = []
    for image in images:
        min_dimension = max(1, min(image.width, image.height))
        max_dimension = max(image.width, image.height)
        upscale = min(8.0, max(1.0, 64 / min_dimension, 240 / max_dimension))
        if upscale > 1:
            image = image.resize(
                (max(1, round(image.width * upscale)), max(1, round(image.height * upscale))),
                Image.Resampling.LANCZOS,
            )
        if image.width > 1800:
            height = max(1, round(image.height * 1800 / image.width))
            image = image.resize((1800, height), Image.Resampling.LANCZOS)
        normalized.append(image)
    padding = 24 if len(normalized) > 1 else 0
    width = max(image.width for image in normalized)
    height = sum(image.height for image in normalized) + padding * max(0, len(normalized) - 1)
    canvas = Image.new("RGBA", (width, height), "white")
    y = 0
    for image in normalized:
        x = (width - image.width) // 2
        canvas.alpha_composite(image, (x, y))
        y += image.height + padding
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ImageOps.exif_transpose(canvas.convert("RGB")).save(output_path, format="PNG", optimize=True)


def balanced_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_subject: dict[str, list[dict[str, Any]]] = {subject: [] for subject in SUBJECTS}
    for candidate in candidates:
        by_subject[candidate["item"]["subject"]].append(candidate)
    for subject_candidates in by_subject.values():
        subject_candidates.sort(
            key=lambda candidate: (
                -int(candidate["item"].get("yearAsInt") or 0),
                int(candidate["item"].get("itemTableIDAsInt") or 0),
            )
        )
    ordered: list[dict[str, Any]] = []
    while any(by_subject.values()):
        for subject in SUBJECTS:
            if by_subject[subject]:
                ordered.append(by_subject[subject].pop(0))
    return ordered


def normalized_fingerprint(question: str, answer: str) -> str:
    normalized = re.sub(r"\W+", "", f"{question} {answer}".lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def prepare_candidate(
    candidate: dict[str, Any],
    refresh: bool,
) -> tuple[dict[str, Any], str, str, str] | None:
    item_id = int(candidate["item"]["itemTableIDAsInt"])
    try:
        score_markup = fetch_score_guide(item_id, refresh)
        if has_disallowed_rights(score_markup):
            return None
        answer = extract_answer(score_markup)
        if not answer:
            return None
        fingerprint = normalized_fingerprint(candidate["question"], answer)
        local_path = f"dataset/images/naep/naep_item_{item_id}.png"
        output_path = ROOT_DIR / local_path
        if not output_path.exists():
            localize_visual(candidate["resource_urls"], output_path)
        return candidate, answer, fingerprint, local_path
    except Exception as exc:
        print(f"Skipping candidate {item_id}: {exc}", file=sys.stderr, flush=True)
        return None


def record_from_candidate(
    candidate: dict[str, Any],
    answer: str,
    sequence: int,
    local_path: str,
) -> dict[str, Any]:
    item = candidate["item"]
    item_id = int(item["itemTableIDAsInt"])
    return {
        "id": f"naep_{sequence:04d}",
        "question": candidate["question"],
        "answer": answer,
        "image_url": local_path,
        "media_type": "image",
        "source": "naep_released_questions",
        "source_url": f"{API_URL}/queryresults/GetItem?tableID={item_id}",
        "source_image_urls": candidate["resource_urls"],
        "source_question_id": item.get("questionID"),
        "naep_id": item.get("naepId"),
        "subject": SUBJECT_LABELS.get(item["subject"], item["subject"]),
        "grade": item.get("grade"),
        "release_year": item.get("year"),
        "item_type": item.get("type"),
        "difficulty": item.get("difficulty"),
        "content_classification": item.get("mainClassification"),
        "description": item.get("description"),
        "license": "Public domain; items containing detected third-party copyright notices are excluded.",
        "rights_url": "https://www.nationsreportcard.gov/faq.asp",
        "reasoning_focus": "source_authored_visual_assessment",
    }


def remove_unreferenced_assets(records: list[dict[str, Any]]) -> int:
    referenced = {Path(record["image_url"]).name for record in records}
    removed = 0
    for path in IMAGES_DIR.glob("naep_item_*.png"):
        if path.name not in referenced:
            path.unlink()
            removed += 1
    return removed


def main() -> int:
    args = parse_args()
    if args.max_items is not None and args.max_items < 1:
        raise SystemExit("--max-items must be positive")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_info = cached_json(
        "metadata",
        "all_subject_grade_info",
        lambda: request("GET", f"{API_URL}/querypanel/allsubjectgradeinfo", expect_json=True),
        args.refresh,
    )

    all_items: list[dict[str, Any]] = []
    for subject in SUBJECTS:
        items = fetch_subject_items(subject, all_info, args.refresh)
        for item in items:
            item["subject"] = subject
        all_items.extend(items)
        print(f"Discovered {len(items):4d} released {SUBJECT_LABELS[subject]} items.", flush=True)

    candidates: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(fetch_item_detail, int(item["itemTableIDAsInt"]), args.refresh): item
            for item in all_items
        }
        completed = 0
        for future in as_completed(futures):
            item = futures[future]
            completed += 1
            try:
                candidate = candidate_from_item(item, future.result())
            except Exception as exc:
                print(f"Skipping item {item.get('itemTableID')}: {exc}", file=sys.stderr, flush=True)
                continue
            if candidate:
                candidates.append(candidate)
            if completed % 250 == 0:
                print(
                    f"Screened {completed:4d}/{len(all_items)} items; "
                    f"{len(candidates):4d} visual candidates.",
                    flush=True,
                )

    candidates = balanced_candidates(candidates)
    print(
        f"Found {len(candidates)} visual candidates without detected third-party rights notices.",
        flush=True,
    )
    if args.inventory_only:
        if args.max_items is not None and len(candidates) < args.max_items:
            return 2
        return 0

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    naep_ids: set[str] = set()
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        prepared_results = executor.map(
            lambda candidate: prepare_candidate(candidate, args.refresh),
            candidates,
        )
        for prepared in prepared_results:
            if args.max_items is not None and len(records) >= args.max_items:
                break
            if not prepared:
                continue
            candidate, answer, fingerprint, local_path = prepared
            naep_id = clean_text(candidate["item"].get("naepId"))
            if fingerprint in fingerprints or (naep_id and naep_id in naep_ids):
                continue
            sequence = len(records) + 1
            record = record_from_candidate(candidate, answer, sequence, local_path)
            records.append(record)
            fingerprints.add(fingerprint)
            if naep_id:
                naep_ids.add(naep_id)
            if len(records) % 50 == 0:
                target = str(args.max_items) if args.max_items is not None else "all eligible"
                print(
                    f"Accepted and localized {len(records):4d}/{target} records.",
                    flush=True,
                )

    OUTPUT_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    removed = remove_unreferenced_assets(records)
    print(f"Wrote {len(records)} records to {OUTPUT_JSON.relative_to(ROOT_DIR)}.")
    if removed:
        print(f"Removed {removed} unreferenced NAEP image assets.")
    if args.max_items is not None and len(records) != args.max_items:
        print(f"Required {args.max_items} records but only produced {len(records)}.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
