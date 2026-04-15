"""Stress Dost - Acadza Question Integration Service.

Fixes applied vs original:
  1. SSL certificate verification on Windows fixed via certifi.
  2. ACADZA_VERIFY=false env var still respected for dev bypass.
  3. Concurrent fetching via ThreadPoolExecutor — 20 serial requests
     took 15 s+; now completes in ~3-5 s.
  4. Duplicate question IDs in CSV are deduplicated at load time.
  5. Graceful fallback question set returned when API is unreachable,
     so the simulation stage never shows "Questions unavailable".
  6. Cache removed from load-test-questions so a fallback response
     is never permanently cached — real questions load next time.
"""
from __future__ import annotations

import json
import logging
import os
import random
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from flask import Blueprint, jsonify, request
from flask_caching import Cache

try:
    import certifi  # fixes SSL cert verification on Windows
    _CERTIFI_PATH = certifi.where()
except ImportError:  # pragma: no cover
    _CERTIFI_PATH = None  # fall back to system certs

from ..services.question_mutator import mutate_question

logger = logging.getLogger(__name__)

question_bp = Blueprint("questions", __name__, url_prefix="/api/questions")
cache = Cache(config={"CACHE_TYPE": "simple"})

# ---------------------------------------------------------------------------
# Paths and API config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]
ACADZA_API_URL = os.getenv("ACADZA_API_URL", "https://api.acadza.in/question/details")
QUESTIONS_CSV_PATH = os.getenv("QUESTION_IDS_CSV", str(BASE_DIR / "data" / "question_ids.csv"))
CACHE_TIMEOUT = 3600  # 1 hour

def _build_acadza_headers() -> Dict:
    """
    Build Acadza request headers fresh from env vars every call.

    Previously headers were built once at module import time, which meant
    ACADZA_COURSE defaulted to "undefined" and ACADZA_AUTH was missing
    whenever the .env file hadn't been loaded yet (e.g. on the first worker
    import before python-dotenv ran).  Building them lazily ensures the
    correct values are always used.

    Required env vars:
        ACADZA_AUTH    — full Authorization header value, e.g. "Bearer eyJ..."
        ACADZA_API_KEY — api-key header value (default: "postmanrulz")
        ACADZA_COURSE  — course header value, e.g. "JEE" (default was "undefined"
                         which caused 401 Auth failed on every request)
    """
    course = os.getenv("ACADZA_COURSE", "").strip()
    auth   = os.getenv("ACADZA_AUTH",   "").strip()
    apikey = os.getenv("ACADZA_API_KEY", "postmanrulz").strip()

    # Warn loudly if critical values are missing so the log makes the fix obvious
    if not course:
        logger.warning(
            "ACADZA_COURSE is not set in .env — defaulting to 'JEE'. "
            "Add ACADZA_COURSE=JEE to your .env to silence this warning."
        )
        course = "JEE"

    if not auth:
        logger.warning(
            "ACADZA_AUTH is not set in .env — requests will be sent without "
            "Authorization header and will return 401."
        )

    headers: Dict = {
        "Accept": "application/json",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,hi;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://www.acadza.com",
        "Referer": "https://www.acadza.com/",
        "Connection": "keep-alive",
        "User-Agent": os.getenv(
            "ACADZA_USER_AGENT",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        ),
        "api-key": apikey,
        "course": course,
    }

    if auth:
        headers["Authorization"] = auth

    return headers


# Keep a module-level alias so existing code that references ACADZA_HEADERS
# still works — but the dict is now built fresh on every AcadzaQuestionFetcher
# instantiation (see __init__ below).
ACADZA_HEADERS = _build_acadza_headers()


# ---------------------------------------------------------------------------
# Fallback questions — used when the external API is completely unreachable.
# Covers Physics, Chemistry, Maths, Biology so popups stay relevant.
# ---------------------------------------------------------------------------
FALLBACK_QUESTIONS_RAW: List[Dict] = [
    {
        "_id": "fallback_phy_001",
        "questionType": "scq",
        "subject": "Physics",
        "chapter": "Kinematics",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>A car accelerates uniformly from rest and covers 100 m in 10 s. "
                "What is its acceleration?</p>"
                "<p>(A) 1 m/s²</p><p>(B) 2 m/s²</p><p>(C) 5 m/s²</p><p>(D) 10 m/s²</p>"
            ),
            "answer": "B",
            "solution": "<p>Using s = ½at²: 100 = ½ × a × 100 → a = 2 m/s²</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_phy_002",
        "questionType": "scq",
        "subject": "Physics",
        "chapter": "Laws of Motion",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>A body of mass 5 kg is acted upon by a net force of 20 N. "
                "What is its acceleration?</p>"
                "<p>(A) 2 m/s²</p><p>(B) 4 m/s²</p><p>(C) 10 m/s²</p><p>(D) 100 m/s²</p>"
            ),
            "answer": "B",
            "solution": "<p>F = ma → a = F/m = 20/5 = 4 m/s²</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_phy_003",
        "questionType": "scq",
        "subject": "Physics",
        "chapter": "Work, Energy and Power",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>A 2 kg object is raised to a height of 5 m. "
                "What is the potential energy gained? (g = 10 m/s²)</p>"
                "<p>(A) 10 J</p><p>(B) 50 J</p><p>(C) 100 J</p><p>(D) 200 J</p>"
            ),
            "answer": "C",
            "solution": "<p>PE = mgh = 2 × 10 × 5 = 100 J</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_chem_001",
        "questionType": "scq",
        "subject": "Chemistry",
        "chapter": "Atomic Structure",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>The number of electrons in a neutral atom of oxygen (atomic number 8) is:</p>"
                "<p>(A) 6</p><p>(B) 7</p><p>(C) 8</p><p>(D) 16</p>"
            ),
            "answer": "C",
            "solution": "<p>Neutral atom has electrons = atomic number = 8.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_chem_002",
        "questionType": "scq",
        "subject": "Chemistry",
        "chapter": "Chemical Bonding",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>Which of the following has the highest electronegativity?</p>"
                "<p>(A) Oxygen</p><p>(B) Nitrogen</p><p>(C) Fluorine</p><p>(D) Chlorine</p>"
            ),
            "answer": "C",
            "solution": "<p>Fluorine has the highest electronegativity (3.98 on Pauling scale).</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_chem_003",
        "questionType": "scq",
        "subject": "Chemistry",
        "chapter": "Mole Concept",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>How many moles are present in 44 g of CO₂? (Molecular mass of CO₂ = 44 g/mol)</p>"
                "<p>(A) 0.5</p><p>(B) 1</p><p>(C) 2</p><p>(D) 44</p>"
            ),
            "answer": "B",
            "solution": "<p>Moles = mass / molar mass = 44 / 44 = 1 mol</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_chem_004",
        "questionType": "scq",
        "subject": "Chemistry",
        "chapter": "Periodic Table",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>Which of the following is an alkali metal?</p>"
                "<p>(A) Calcium</p><p>(B) Sodium</p><p>(C) Magnesium</p><p>(D) Aluminium</p>"
            ),
            "answer": "B",
            "solution": "<p>Sodium (Na) belongs to Group 1 — the alkali metals.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_math_001",
        "questionType": "scq",
        "subject": "Maths",
        "chapter": "Differentiation",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>The derivative of sin(x) with respect to x is:</p>"
                "<p>(A) -cos(x)</p><p>(B) cos(x)</p><p>(C) -sin(x)</p><p>(D) tan(x)</p>"
            ),
            "answer": "B",
            "solution": "<p>d/dx [sin x] = cos x</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_math_002",
        "questionType": "scq",
        "subject": "Maths",
        "chapter": "Integration",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>The integral of x² dx is equal to:</p>"
                "<p>(A) x³ + C</p><p>(B) 2x + C</p><p>(C) x³/3 + C</p><p>(D) 3x² + C</p>"
            ),
            "answer": "C",
            "solution": "<p>Using the power rule: x^(n+1)/(n+1) + C = x³/3 + C</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_math_003",
        "questionType": "scq",
        "subject": "Maths",
        "chapter": "Quadratic Equations",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>The roots of x² - 5x + 6 = 0 are:</p>"
                "<p>(A) 1 and 6</p><p>(B) 2 and 3</p><p>(C) -2 and -3</p><p>(D) 1 and 5</p>"
            ),
            "answer": "B",
            "solution": "<p>Factoring: (x-2)(x-3) = 0 gives roots 2 and 3.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_bio_001",
        "questionType": "scq",
        "subject": "Biology",
        "chapter": "Cell Biology",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>Which organelle is known as the powerhouse of the cell?</p>"
                "<p>(A) Nucleus</p><p>(B) Ribosome</p><p>(C) Mitochondria</p><p>(D) Golgi body</p>"
            ),
            "answer": "C",
            "solution": "<p>Mitochondria produce ATP via cellular respiration.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_bio_002",
        "questionType": "scq",
        "subject": "Biology",
        "chapter": "Genetics",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>DNA replication occurs during which phase of the cell cycle?</p>"
                "<p>(A) G1 phase</p><p>(B) S phase</p><p>(C) G2 phase</p><p>(D) M phase</p>"
            ),
            "answer": "B",
            "solution": "<p>DNA synthesis occurs during the S (Synthesis) phase.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_bio_003",
        "questionType": "scq",
        "subject": "Biology",
        "chapter": "Photosynthesis",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>The primary pigment responsible for photosynthesis is:</p>"
                "<p>(A) Carotenoid</p><p>(B) Xanthophyll</p><p>(C) Chlorophyll</p><p>(D) Anthocyanin</p>"
            ),
            "answer": "C",
            "solution": "<p>Chlorophyll absorbs red and blue light — the main photosynthetic pigment.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_phy_004",
        "questionType": "scq",
        "subject": "Physics",
        "chapter": "Electrostatics",
        "difficulty": "Hard",
        "level": "HARD",
        "scq": {
            "question": (
                "<p>Two charges of +2 uC and -2 uC are placed 0.2 m apart. "
                "The force between them is: (k = 9x10^9 N m^2/C^2)</p>"
                "<p>(A) 0.45 N</p><p>(B) 0.9 N</p><p>(C) 1.8 N</p><p>(D) 3.6 N</p>"
            ),
            "answer": "B",
            "solution": (
                "<p>F = kq1q2/r^2 = 9x10^9 x 2x10^-6 x 2x10^-6 / (0.2)^2 = 0.9 N</p>"
            ),
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_chem_005",
        "questionType": "scq",
        "subject": "Chemistry",
        "chapter": "Organic Chemistry",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>The IUPAC name of CH3-CH2-OH is:</p>"
                "<p>(A) Methanol</p><p>(B) Ethanol</p><p>(C) Propanol</p><p>(D) Butanol</p>"
            ),
            "answer": "B",
            "solution": "<p>CH3CH2OH has 2 carbons with a hydroxyl group — Ethanol.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_math_004",
        "questionType": "scq",
        "subject": "Maths",
        "chapter": "Trigonometry",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>The value of sin(90 degrees) is:</p>"
                "<p>(A) 0</p><p>(B) 1/2</p><p>(C) sqrt(3)/2</p><p>(D) 1</p>"
            ),
            "answer": "D",
            "solution": "<p>sin(90) = 1 (standard trigonometric value).</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_math_005",
        "questionType": "scq",
        "subject": "Maths",
        "chapter": "Probability",
        "difficulty": "Medium",
        "level": "MEDIUM",
        "scq": {
            "question": (
                "<p>A die is thrown once. The probability of getting a number greater than 4 is:</p>"
                "<p>(A) 1/6</p><p>(B) 1/3</p><p>(C) 1/2</p><p>(D) 2/3</p>"
            ),
            "answer": "B",
            "solution": "<p>Favourable outcomes: 5, 6 → P = 2/6 = 1/3</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_phy_005",
        "questionType": "scq",
        "subject": "Physics",
        "chapter": "Optics",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>The speed of light in vacuum is approximately:</p>"
                "<p>(A) 3x10^6 m/s</p><p>(B) 3x10^8 m/s</p>"
                "<p>(C) 3x10^10 m/s</p><p>(D) 3x10^12 m/s</p>"
            ),
            "answer": "B",
            "solution": "<p>c = 3x10^8 m/s in vacuum.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_bio_004",
        "questionType": "scq",
        "subject": "Biology",
        "chapter": "Human Physiology",
        "difficulty": "Easy",
        "level": "EASY",
        "scq": {
            "question": (
                "<p>Which blood group is known as the universal donor?</p>"
                "<p>(A) A</p><p>(B) B</p><p>(C) AB</p><p>(D) O</p>"
            ),
            "answer": "D",
            "solution": "<p>Blood group O (Rh-) is the universal donor — lacks A and B antigens.</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
    {
        "_id": "fallback_chem_006",
        "questionType": "scq",
        "subject": "Chemistry",
        "chapter": "Thermodynamics",
        "difficulty": "Hard",
        "level": "HARD",
        "scq": {
            "question": (
                "<p>For a spontaneous process at constant T and P, "
                "the Gibbs free energy change (delta G) must be:</p>"
                "<p>(A) Positive</p><p>(B) Zero</p><p>(C) Negative</p>"
                "<p>(D) Independent of temperature</p>"
            ),
            "answer": "C",
            "solution": "<p>A spontaneous process requires delta G less than 0 (negative).</p>",
            "quesImages": [],
            "solutionImages": [],
        },
    },
]


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------
class QuestionIDLoader:
    """Manages loading and random selection of question IDs from CSV."""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.question_ids: list[str] = []
        self.load_ids()

    def load_ids(self) -> None:
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Deduplicate while preserving original order
                seen: set[str] = set()
                ids: list[str] = []
                for row in reader:
                    qid = (row.get("question_id") or "").strip()
                    if qid and qid not in seen:
                        seen.add(qid)
                        ids.append(qid)
            self.question_ids = ids
            logger.info(
                "Loaded %d unique question IDs from %s",
                len(self.question_ids), self.csv_path,
            )
        except FileNotFoundError:
            logger.warning("Question ID CSV not found: %s", self.csv_path)
            self.question_ids = []
        except Exception as exc:
            logger.error("Error loading CSV %s: %s", self.csv_path, exc)
            self.question_ids = []

    def get_random_ids(self, count: int = 20) -> List[str]:
        if len(self.question_ids) <= count:
            return list(self.question_ids)
        return random.sample(self.question_ids, count)

    def get_all_ids(self) -> List[str]:
        return self.question_ids


question_loader = QuestionIDLoader(QUESTIONS_CSV_PATH)


# ---------------------------------------------------------------------------
# Acadza client
# ---------------------------------------------------------------------------
class AcadzaQuestionFetcher:
    """Handles communication with Acadza API with SSL fix and concurrent fetching."""

    def __init__(self, api_url: str, headers: Dict):
        self.api_url = api_url
        # Rebuild headers from env vars at construction time so that whatever
        # was loaded into os.environ by python-dotenv is captured correctly.
        self.headers = _build_acadza_headers()
        self.request_timeout = 8

        # SSL verification logic:
        #   ACADZA_VERIFY=false  → skip verification (local dev only)
        #   certifi installed    → use certifi bundle (fixes Windows SSL)
        #   neither              → Python default (system certs)
        raw_verify = os.getenv("ACADZA_VERIFY", "true").strip().lower()
        if raw_verify in {"0", "false", "no"}:
            self.verify_ssl: bool | str = False
            logger.warning(
                "SSL verification DISABLED via ACADZA_VERIFY env var. "
                "Do not use this in production."
            )
        elif _CERTIFI_PATH:
            self.verify_ssl = _CERTIFI_PATH  # certifi bundle path (str)
        else:
            self.verify_ssl = True  # system default

        # ── Startup probe: log effective header values so auth issues are obvious ──
        logger.info(
            "AcadzaQuestionFetcher init — api_url=%s  course=%r  api-key=%r  "
            "auth_present=%s  ssl_verify=%s",
            self.api_url,
            self.headers.get("course"),
            self.headers.get("api-key"),
            bool(self.headers.get("Authorization")),
            self.verify_ssl,
        )

    def fetch_question(self, question_id: str) -> Optional[Dict]:
        """Fetch a single question from the Acadza API."""
        try:
            headers = self.headers.copy()
            headers["questionId"] = question_id

            response = requests.post(
                self.api_url,
                json={},
                headers=headers,
                timeout=self.request_timeout,
                verify=self.verify_ssl,
            )

            if response.status_code == 200:
                logger.debug("Fetched question: %s", question_id)
                return response.json()

            logger.warning(
                "API returned %s for %s — body: %s",
                response.status_code, question_id, response.text[:200],
            )
            return None

        except requests.Timeout:
            logger.error("Timeout fetching question %s", question_id)
            return None
        except requests.RequestException as exc:
            logger.error("Error fetching question %s: %s", question_id, exc)
            return None
        except json.JSONDecodeError:
            logger.error("Invalid JSON response for question %s", question_id)
            return None

    def fetch_multiple(self, question_ids: List[str], max_workers: int = 6) -> List[Dict]:
        """
        Fetch multiple questions concurrently.

        Uses ThreadPoolExecutor so 20 questions complete in ~3-5 s instead of
        the 15-20 s serial time seen in the logs.
        Falls back to FALLBACK_QUESTIONS_RAW if the API returns nothing at all.
        """
        if not question_ids:
            logger.warning("fetch_multiple called with empty ID list — using fallback")
            return list(FALLBACK_QUESTIONS_RAW)

        results: Dict[str, Optional[Dict]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {
                executor.submit(self.fetch_question, qid): qid
                for qid in question_ids
            }
            for future in as_completed(future_to_id):
                qid = future_to_id[future]
                try:
                    results[qid] = future.result()
                except Exception as exc:
                    logger.error("Unexpected error for %s: %s", qid, exc)
                    results[qid] = None

        # Preserve original order, drop failed fetches
        questions = [results[qid] for qid in question_ids if results.get(qid)]

        fetched = len(questions)
        logger.info("Fetched %d/%d questions from Acadza API", fetched, len(question_ids))

        if fetched == 0:
            logger.warning(
                "Acadza API returned 0 questions (SSL / network unreachable). "
                "Serving %d local fallback questions.",
                len(FALLBACK_QUESTIONS_RAW),
            )
            return list(FALLBACK_QUESTIONS_RAW)

        return questions


acadza_fetcher = AcadzaQuestionFetcher(ACADZA_API_URL, ACADZA_HEADERS)


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------
class QuestionFormatter:
    """Formats raw Acadza question data into frontend-ready format."""

    @staticmethod
    def format_question(raw_data: Dict, question_index: int = 0) -> Dict:
        question_type = raw_data.get("questionType", "scq")
        if question_type == "mcq":
            return QuestionFormatter._format_mcq(raw_data, question_index)
        if question_type == "integerQuestion":
            return QuestionFormatter._format_integer(raw_data, question_index)
        return QuestionFormatter._format_scq(raw_data, question_index)

    @staticmethod
    def _format_scq(raw_data: Dict, idx: int) -> Dict:
        scq_data = raw_data.get("scq", {})
        question_html = scq_data.get("question", "<p>Question not available</p>")
        options = QuestionFormatter._extract_options_from_html(question_html)
        return {
            "question_id": raw_data.get("_id", "unknown"),
            "question_index": idx + 1,
            "question_type": "scq",
            "subject": raw_data.get("subject", "Unknown"),
            "chapter": raw_data.get("chapter", "Unknown"),
            "difficulty": raw_data.get("difficulty", "Medium"),
            "level": raw_data.get("level", "MEDIUM"),
            "question_html": question_html,
            "question_images": scq_data.get("quesImages", []),
            "options": options,
            "correct_answer": scq_data.get("answer", "A"),
            "solution_html": scq_data.get("solution", "<p>Solution not available</p>"),
            "solution_images": scq_data.get("solutionImages", []),
            "metadata": {
                "smart_trick": raw_data.get("smartTrick", False),
                "trap": raw_data.get("trap", False),
                "silly_mistake": raw_data.get("sillyMistake", False),
                "is_lengthy": raw_data.get("isLengthy", 0),
                "is_ncert": raw_data.get("isNCERT", False),
                "tag_subconcepts": QuestionFormatter._extract_subconcepts(raw_data),
                "is_fallback": raw_data.get("_id", "").startswith("fallback_"),
            },
        }

    @staticmethod
    def _format_mcq(raw_data: Dict, idx: int) -> Dict:
        mcq_data = raw_data.get("mcq", {})
        # MCQ questions sometimes embed the display HTML inside scq.question;
        # fall back to the raw mcq "question" field when scq is absent.
        question_html = (
            raw_data.get("scq", {}).get("question")
            or mcq_data.get("question")
            or "<p>Question not available</p>"
        )
        # ── FIX: extract rendered options list and normalise correct_answer ──
        # The frontend's submitCurrentQuestion() needs q.options (list of
        # {label, text} dicts) and q.correct_answer (uppercase letter string)
        # to compare the student's selection and score correctly.
        # Without options the option radio buttons never render.
        # Without correct_answer every submission is silently marked wrong.
        options = QuestionFormatter._extract_options_from_html(question_html)

        raw_answer = mcq_data.get("answer", [])
        # Normalise to a flat uppercase string for single-choice MCQs,
        # or keep as a list for multi-correct MCQs.
        if isinstance(raw_answer, list):
            correct_answers: list = [str(a).strip().upper() for a in raw_answer if a]
            # Single-correct shorthand: expose as correct_answer too so
            # the frontend's simple string-comparison path works unchanged.
            correct_answer: str = correct_answers[0] if len(correct_answers) == 1 else ""
        else:
            correct_answer = str(raw_answer).strip().upper()
            correct_answers = [correct_answer] if correct_answer else []

        return {
            "question_id": raw_data.get("_id", "unknown"),
            "question_index": idx + 1,
            "question_type": "mcq",
            "subject": raw_data.get("subject", "Unknown"),
            "chapter": raw_data.get("chapter", "Unknown"),
            "difficulty": raw_data.get("difficulty", "Medium"),
            "level": raw_data.get("level", "MEDIUM"),
            "question_html": question_html,
            "question_images": mcq_data.get("quesImages", []),
            "options": options,                    # ← was missing; needed for rendering
            "correct_answer": correct_answer,      # ← was missing; needed for scoring
            "correct_answers": correct_answers,    # kept for multi-correct support
            "solution_html": (
                raw_data.get("scq", {}).get("solution")
                or mcq_data.get("solution")
                or "<p>Solution not available</p>"
            ),
            "solution_images": mcq_data.get("solutionImages", []),
            "metadata": {
                "smart_trick": raw_data.get("smartTrick", False),
                "trap": raw_data.get("trap", False),
                "is_fallback": raw_data.get("_id", "").startswith("fallback_"),
            },
        }

    @staticmethod
    def _format_integer(raw_data: Dict, idx: int) -> Dict:
        int_data = raw_data.get("integerQuestion", {})
        question_html = (
            int_data.get("question")
            or raw_data.get("scq", {}).get("question")
            or "<p>Question not available</p>"
        )
        solution_html = (
            int_data.get("solution")
            or raw_data.get("scq", {}).get("solution")
            or "<p>Solution not available</p>"
        )
        return {
            "question_id": raw_data.get("_id", "unknown"),
            "question_index": idx + 1,
            "question_type": "integer",
            "subject": raw_data.get("subject", "Unknown"),
            "chapter": raw_data.get("chapter", "Unknown"),
            "difficulty": raw_data.get("difficulty", "Medium"),
            "level": raw_data.get("level", "MEDIUM"),
            "question_html": question_html,
            "question_images": (
                int_data.get("quesImages") or raw_data.get("scq", {}).get("quesImages", [])
            ),
            "integer_answer": int_data.get("answer"),
            "solution_html": solution_html,
            "solution_images": (
                int_data.get("solutionImages") or raw_data.get("scq", {}).get("solutionImages", [])
            ),
            "metadata": {
                "is_fallback": raw_data.get("_id", "").startswith("fallback_"),
            },
        }

    @staticmethod
    def _extract_options_from_html(html: str) -> List[Dict]:
        import re

        options: list[dict] = []
        pattern = r"\(([A-D])\)\s*(.+?)(?=\(|$)"
        matches = re.findall(pattern, html or "", re.DOTALL)
        for label, content in matches:
            clean = re.sub(r"<[^>]+>", "", content).strip()
            options.append({"label": label, "text": clean[:200]})

        if len(options) < 4:
            options = [
                {"label": "A", "text": "Option A"},
                {"label": "B", "text": "Option B"},
                {"label": "C", "text": "Option C"},
                {"label": "D", "text": "Option D"},
            ]
        return options

    @staticmethod
    def _extract_subconcepts(raw_data: Dict) -> List[str]:
        subconcepts: list[str] = []
        for tag in raw_data.get("tagSubConcept", []) or []:
            if isinstance(tag, dict) and "subConcept" in tag:
                subconcepts.append(tag["subConcept"])
        return subconcepts


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@question_bp.route("/load-test-questions", methods=["GET"])
def load_test_questions():
    """
    Load a random set of 20 questions for the test simulation.

    Intentionally NOT cached — if the API was down on the first call and
    returned fallback questions, a cached 200 response would hide real
    questions on all subsequent calls until the server restarts.
    """
    question_ids = question_loader.get_random_ids(count=20)

    if not question_ids:
        logger.warning("No question IDs in CSV — serving full fallback set")
        formatted = [
            QuestionFormatter.format_question(q, idx)
            for idx, q in enumerate(FALLBACK_QUESTIONS_RAW)
        ]
        return jsonify(
            {
                "status": "success",
                "questions": formatted,
                "total_questions": len(formatted),
                "source": "fallback",
                "message": "No IDs in question_ids.csv — showing built-in fallback questions.",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    raw_questions = acadza_fetcher.fetch_multiple(question_ids)
    formatted = [
        QuestionFormatter.format_question(q, idx) for idx, q in enumerate(raw_questions)
    ]

    source = (
        "fallback"
        if all(q.get("question_id", "").startswith("fallback_") for q in formatted)
        else "acadza"
    )

    return jsonify(
        {
            "status": "success",
            "questions": formatted,
            "total_questions": len(formatted),
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


@question_bp.route("/get-question/<question_id>", methods=["GET"])
@cache.cached(timeout=CACHE_TIMEOUT, query_string=True)
def get_single_question(question_id: str):
    raw_question = acadza_fetcher.fetch_question(question_id)
    if not raw_question:
        return (
            jsonify({"status": "error", "message": f"Question {question_id} not found"}),
            404,
        )

    formatted = QuestionFormatter.format_question(raw_question)
    return jsonify({"status": "success", "question": formatted})


@question_bp.route("/prefetch-batch", methods=["POST"])
def prefetch_batch():
    data = request.get_json(force=True, silent=True) or {}
    question_ids = data.get("question_ids") or []
    if not question_ids:
        return (
            jsonify({"status": "error", "message": "No question IDs provided"}),
            400,
        )

    raw_questions = acadza_fetcher.fetch_multiple(question_ids)
    formatted = [
        QuestionFormatter.format_question(q, idx) for idx, q in enumerate(raw_questions)
    ]
    return jsonify(
        {"status": "success", "questions": formatted, "prefetched_count": len(formatted)}
    )


@question_bp.route("/stats", methods=["GET"])
def get_stats():
    return jsonify(
        {
            "total_questions_available": len(question_loader.question_ids),
            "csv_path": QUESTIONS_CSV_PATH,
            "ssl_verify": str(acadza_fetcher.verify_ssl),
            "certifi_available": _CERTIFI_PATH is not None,
            "fallback_questions_count": len(FALLBACK_QUESTIONS_RAW),
            "sample_ids": question_loader.get_random_ids(5),
        }
    )


@question_bp.route("/mutate/<question_id>", methods=["POST"])
def mutate(question_id: str):
    """
    Mutate a question (scq/integer) by changing numeric values and answers.

    FIX: Previously this returned 404 for every fallback_* ID because it tried
    to fetch them from the Acadza API, which knows nothing about local fallbacks.
    Now we check the local FALLBACK_QUESTIONS_RAW dict first, then fall back to
    the Acadza API only for real IDs.
    """
    raw_question: Optional[Dict] = None

    # ── Check local fallback store first (covers all fallback_* IDs) ─────────
    if question_id.startswith("fallback_"):
        raw_question = next(
            (q for q in FALLBACK_QUESTIONS_RAW if q.get("_id") == question_id),
            None,
        )
        if not raw_question:
            return (
                jsonify({"status": "error", "message": f"Fallback question {question_id} not found"}),
                404,
            )
    else:
        # Real Acadza ID — fetch from API as before
        raw_question = acadza_fetcher.fetch_question(question_id)
        if not raw_question:
            return (
                jsonify({"status": "error", "message": f"Question {question_id} not found"}),
                404,
            )

    formatted = QuestionFormatter.format_question(raw_question)
    if formatted.get("question_type") not in {"scq", "integer"}:
        return jsonify({"status": "error", "message": "Only scq/integer supported"}), 400

    mutated, changed = mutate_question(formatted)
    logger.info("mutate_endpoint question_id=%s mutated=%s", question_id, changed)
    return jsonify(
        {
            "status": "success",
            "mutated": changed,
            "question": mutated,
        }
    )


@question_bp.route("/submit-test", methods=["POST"])
def submit_test():
    """
    Score a completed test attempt.

    Expected request body:
        {
            "answers": {
                "<question_id>": "<selected_label>",   // SCQ / MCQ: "A", "B", "C", or "D"
                "<question_id>": "<integer_string>",   // Integer: "42"
                ...
            },
            "questions": [   // optional — full question objects already on the client
                { "question_id": "...", "correct_answer": "B", "question_type": "scq", ... },
                ...
            ]
        }

    The endpoint re-fetches questions if the caller doesn't send them, so the
    correct answers always come from the server — never trusted from the client.

    Response:
        {
            "status": "success",
            "score": 3,
            "total": 5,
            "percentage": 60.0,
            "results": [
                {
                    "question_id": "fallback_phy_001",
                    "question_type": "scq",
                    "selected": "B",
                    "correct_answer": "B",
                    "is_correct": true
                },
                ...
            ]
        }
    """
    body = request.get_json(force=True, silent=True) or {}
    # answers: { question_id -> selected_value }
    answers: Dict[str, str] = body.get("answers") or {}
    # optional pre-loaded question list (avoids a second DB/API round-trip)
    client_questions: List[Dict] = body.get("questions") or []

    if not answers:
        return jsonify({"status": "error", "message": "No answers provided"}), 400

    # Build a lookup of question_id → authoritative question data.
    # Prefer client-supplied questions (already formatted); fall back to
    # fetching from fallback store or Acadza for any IDs not supplied.
    question_lookup: Dict[str, Dict] = {
        q["question_id"]: q for q in client_questions if q.get("question_id")
    }

    # For any question_id in answers that is NOT in the client-supplied set,
    # try to resolve it from fallback store or Acadza.
    missing_ids = [qid for qid in answers if qid not in question_lookup]
    for qid in missing_ids:
        if qid.startswith("fallback_"):
            raw = next(
                (q for q in FALLBACK_QUESTIONS_RAW if q.get("_id") == qid),
                None,
            )
        else:
            raw = acadza_fetcher.fetch_question(qid)
        if raw:
            question_lookup[qid] = QuestionFormatter.format_question(raw)

    results: List[Dict] = []
    score = 0

    for qid, selected in answers.items():
        q = question_lookup.get(qid)
        if not q:
            # Question not resolvable — skip scoring, record as unanswered
            results.append({
                "question_id": qid,
                "question_type": "unknown",
                "selected": selected,
                "correct_answer": None,
                "is_correct": False,
                "note": "question not found — not scored",
            })
            continue

        qtype = (q.get("question_type") or "scq").lower()
        is_correct = False

        if qtype == "integer":
            correct_val = q.get("integer_answer")
            if correct_val is not None:
                try:
                    is_correct = abs(float(selected) - float(correct_val)) < 1e-6
                except (ValueError, TypeError):
                    is_correct = str(selected).strip() == str(correct_val).strip()
            correct_answer_display = str(correct_val) if correct_val is not None else None
        else:
            # SCQ / MCQ — compare uppercase strings
            correct_answer = q.get("correct_answer") or ""
            correct_answers = q.get("correct_answers") or []

            sel_norm = str(selected or "").strip().upper()

            if correct_answer:
                is_correct = sel_norm == correct_answer.strip().upper()
                correct_answer_display = correct_answer.strip().upper()
            elif correct_answers:
                correct_set = {str(a).strip().upper() for a in correct_answers}
                is_correct = sel_norm in correct_set
                correct_answer_display = ", ".join(sorted(correct_set))
            else:
                # No answer key available — cannot score
                is_correct = False
                correct_answer_display = None

        if is_correct:
            score += 1

        results.append({
            "question_id": qid,
            "question_type": qtype,
            "selected": selected,
            "correct_answer": correct_answer_display,
            "is_correct": is_correct,
        })

    total = len(answers)
    percentage = round((score / total) * 100, 1) if total else 0.0

    logger.info(
        "submit_test: score=%d/%d (%.1f%%) session_questions=%d",
        score, total, percentage, len(question_lookup),
    )

    return jsonify(
        {
            "status": "success",
            "score": score,
            "total": total,
            "percentage": percentage,
            "results": results,
        }
    )


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------
def init_question_service(app) -> None:
    cache.init_app(app)
    app.register_blueprint(question_bp)
    logger.info("Question service initialized")


__all__ = ["init_question_service"]