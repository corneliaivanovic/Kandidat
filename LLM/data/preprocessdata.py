from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

import pandas as pd

# =========================
# PATHS
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "surveys"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

LLM_DIR = PROCESSED_DIR / "llm"
BERT_DIR = PROCESSED_DIR / "bert"

RAW_JSON_PATH = PROCESSED_DIR / "raw_dataset.json"

LLM_TRAIN_PATH = LLM_DIR / "train.jsonl"
LLM_VAL_PATH = LLM_DIR / "val.jsonl"
LLM_TEST_PATH = LLM_DIR / "test.jsonl"

BERT_TRAIN_PATH = BERT_DIR / "train.csv"
BERT_VAL_PATH = BERT_DIR / "val.csv"
BERT_TEST_PATH = BERT_DIR / "test.csv"

TRAIN_SPLIT = 0.8
VAL_SPLIT = 0.15
TEST_SPLIT = 0.05

RANDOM_SEED = 42

# =========================
# HELPERS
# =========================
def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)

    return text.strip()


def parse_question_header(header_text: str) -> dict[str, str]:
    text = clean_text(header_text)

    profile_match = re.search(
        r"Profil:\s*(.*?)\nPlanerat pass:",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    planned_match = re.search(
        r"Planerat pass:\s*(.*?)\nStatus:",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    status_match = re.search(
        r"Status:\s*(.*?)(?:\nAlternativ:|\nA\)|$)",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    return {
        "profile": clean_text(profile_match.group(1)) if profile_match else "",
        "planned_session": clean_text(planned_match.group(1)) if planned_match else "",
        "status": clean_text(status_match.group(1)) if status_match else "",
    }


def is_timestamp_column(column_name: str) -> bool:
    name = clean_text(column_name).lower()
    return "tidstämpel" in name or "timestamp" in name


def is_motivation_column(column_name: str) -> bool:
    name = clean_text(column_name).lower()

    return any(
        k in name
        for k in ["motivering", "övrigt", "annat", "other"]
    )


def extract_motivation(answer_text: str) -> str:
    text = clean_text(answer_text)

    if not text:
        return ""

    match = re.match(
        r"^\s*([A-E])(?:[\)\.\:\-\s]|$)",
        text,
        flags=re.IGNORECASE
    )

    if match:
        remaining = text[match.end():].strip(" .:-\n")

        if remaining.lower().startswith("motivering:"):
            remaining = remaining[len("motivering:"):].strip(" .:-\n")

        return remaining

    return text


def build_user_content(
    profile: str,
    planned_session: str,
    status: str
) -> str:
    return (
        f"Profil: {profile}\n"
        f"Planerat pass: {planned_session}\n"
        f"Status: {status}\n\n"
        "Vilket beslut bör tränaren ta?"
    )


def build_assistant_content(motivation: str) -> str:
    return motivation


# =========================
# FILE HANDLING
# =========================
def validate_and_create_structure() -> None:
    if not RAW_DIR.exists():
        raise FileNotFoundError(
            f"Hittar inte mappen med rådata: {RAW_DIR}"
        )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    LLM_DIR.mkdir(parents=True, exist_ok=True)
    BERT_DIR.mkdir(parents=True, exist_ok=True)


def load_excel_files() -> list[Path]:
    files = sorted(RAW_DIR.glob("*.xlsx"))

    if not files:
        raise FileNotFoundError(
            f"Inga Excel-filer hittades i: {RAW_DIR}"
        )

    return files


# =========================
# CORE EXTRACTION
# =========================
def extract_records_from_excel(
    file_path: Path
) -> list[dict[str, Any]]:

    print(f"Läser: {file_path.name}")

    df = pd.read_excel(file_path)

    records: list[dict[str, Any]] = []

    question_columns = [
        col for col in df.columns
        if not is_timestamp_column(str(col))
        and not is_motivation_column(str(col))
    ]

    for row_idx, row in df.iterrows():

        for question_col in question_columns:

            question_header = clean_text(question_col)
            answer = clean_text(row.get(question_col, ""))

            if not answer:
                continue

            parsed = parse_question_header(question_header)

            if (
                not parsed["profile"]
                and not parsed["planned_session"]
                and not parsed["status"]
            ):
                continue

            motivation = extract_motivation(answer)

            records.append({
                "source_file": file_path.name,
                "row_index": int(row_idx) + 2,
                "question_header": question_header,
                "profile": parsed["profile"],
                "planned_session": parsed["planned_session"],
                "status": parsed["status"],
                "raw_answer": answer,
                "motivation": motivation,
            })

    return records


# =========================
# FORMAT CONVERTERS
# =========================
def convert_to_llm_format(
    raw_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    llm_records = []

    for record in raw_records:

        user_content = build_user_content(
            record["profile"],
            record["planned_session"],
            record["status"]
        )

        assistant_content = build_assistant_content(
            record["motivation"]
        )

        if assistant_content.strip():

            llm_records.append({
                "messages": [
                    {
                        "role": "user",
                        "content": user_content
                    },
                    {
                        "role": "assistant",
                        "content": assistant_content
                    },
                ],
                "metadata": {
                    "source_file": record["source_file"],
                    "row_index": record["row_index"]
                },
            })

    return llm_records


'''
def convert_to_bert_format(raw_records: list[dict[str, Any]]) -> pd.DataFrame:
    bert_records = []

    for record in raw_records:
        text_input = (
            f"Profil: {record['profile']} | "
            f"Planerat: {record['planned_session']} | "
            f"Status: {record['status']}"
        )

        label = record["decision"]

        if label:
            bert_records.append({
                "text": text_input,
                "label": label
            })

    return pd.DataFrame(bert_records)
'''


# =========================
# SAVING & SPLITTING
# =========================
def save_jsonl(
    path: Path,
    data: list[dict[str, Any]]
) -> None:

    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(
                json.dumps(item, ensure_ascii=False) + "\n"
            )


def split_raw_data(
    data: list[dict[str, Any]],
    train_fraction: float,
    val_fraction: float,
    test_fraction: float,
    seed: int
) -> tuple[list, list, list]:

    if not data:
        return [], [], []

    if abs(
        (train_fraction + val_fraction + test_fraction) - 1.0
    ) > 1e-6:
        raise ValueError(
            "Train, validation och test måste summera till 1.0"
        )

    rng = random.Random(seed)

    shuffled = data[:]
    rng.shuffle(shuffled)

    n_total = len(shuffled)

    n_train = int(n_total * train_fraction)
    n_val = int(n_total * val_fraction)

    train_data = shuffled[:n_train]

    val_data = shuffled[
        n_train:n_train + n_val
    ]

    test_data = shuffled[
        n_train + n_val:
    ]

    return train_data, val_data, test_data


# =========================
# MAIN
# =========================
def main() -> None:

    validate_and_create_structure()

    excel_files = load_excel_files()

    all_raw_records = []

    for file_path in excel_files:
        all_raw_records.extend(
            extract_records_from_excel(file_path)
        )

    print(
        f"Totalt antal datapunkter: "
        f"{len(all_raw_records)}"
    )

    with open(
        RAW_JSON_PATH,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            all_raw_records,
            f,
            ensure_ascii=False,
            indent=2
        )

    raw_train, raw_val, raw_test = split_raw_data(
        all_raw_records,
        TRAIN_SPLIT,
        VAL_SPLIT,
        TEST_SPLIT,
        RANDOM_SEED
    )

    llm_train = convert_to_llm_format(raw_train)
    llm_val = convert_to_llm_format(raw_val)
    llm_test = convert_to_llm_format(raw_test)

    save_jsonl(LLM_TRAIN_PATH, llm_train)
    save_jsonl(LLM_VAL_PATH, llm_val)
    save_jsonl(LLM_TEST_PATH, llm_test)

    '''
    bert_train_df = convert_to_bert_format(raw_train)
    bert_val_df = convert_to_bert_format(raw_val)
    bert_test_df = convert_to_bert_format(raw_test)

    bert_train_df.to_csv(
        BERT_TRAIN_PATH,
        index=False,
        encoding="utf-8"
    )

    bert_val_df.to_csv(
        BERT_VAL_PATH,
        index=False,
        encoding="utf-8"
    )

    bert_test_df.to_csv(
        BERT_TEST_PATH,
        index=False,
        encoding="utf-8"
    )
    '''

    print(f"LLM-filer (JSONL) sparade i: {LLM_DIR}")

    print(
        f"\nFördelning:\n"
        f"Träning: {len(raw_train)} st\n"
        f"Validering: {len(raw_val)} st\n"
        f"Test: {len(raw_test)} st"
    )


if __name__ == "__main__":
    main()