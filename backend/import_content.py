"""Load the supplied Factish CSV files into independent facts and fakes tables."""

import csv
import sys
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .models import Fact, Fake


CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
# All files are imported together; append new parts to the end.
CONTENT_FILES = tuple(CONTENT_DIR / name for name in ("factish_100_facts_and_fakes.csv", "factish_new_part01.csv", "factish_new_part02.csv", "factish_new_part03.csv", "factish_new_part04.csv"))
COLUMNS = {"id", "сфера", "утверждение", "тип", "сложность_из_100", "пояснение_после_ответа"}


def parse(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if set(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"Unexpected CSV columns in {path.name}: {reader.fieldnames}")
        seen_ids: set[int] = set()
        seen_text: set[str] = set()
        rows = []
        for line, row in enumerate(reader, 2):
            source_id = int(row["id"])
            kind = row["тип"].strip().lower()
            difficulty = int(row["сложность_из_100"])
            statement = row["утверждение"].strip()
            category = row["сфера"].strip()
            explanation = row["пояснение_после_ответа"].strip()
            if kind not in {"факт", "фейк"} or not 0 <= difficulty <= 100 or not statement or not category or not explanation:
                raise ValueError(f"Invalid data in {path.name} on line {line}")
            if source_id in seen_ids or statement in seen_text:
                raise ValueError(f"Duplicate id or statement in {path.name} on line {line}")
            seen_ids.add(source_id)
            seen_text.add(statement)
            rows.append((Fact if kind == "факт" else Fake, path.name, source_id, category, statement, difficulty, explanation))
    return rows


def load(paths):
    rows = []
    origin: dict[str, str] = {}
    for path in paths:
        for row in parse(path):
            statement = row[4]
            if statement in origin:
                raise ValueError(f"Statement {row[2]} in {path.name} repeats one from {origin[statement]}")
            origin[statement] = path.name
            rows.append(row)
    if not any(item[0] is Fact for item in rows) or not any(item[0] is Fake for item in rows):
        raise ValueError("Content must contain facts and fakes")
    return rows


def import_files(paths=CONTENT_FILES):
    """Upsert records by statement text, so a statement never changes under past rounds."""
    rows = load(paths)
    with SessionLocal.begin() as db:
        imported: dict[type, set[str]] = {Fact: set(), Fake: set()}
        existing = {model: {record.statement: record for record in db.scalars(select(model))} for model in (Fact, Fake)}
        for model, source, source_id, category, statement, difficulty, explanation in rows:
            record = existing[model].get(statement)
            if record is None:
                record = model(statement=statement)
                db.add(record)
            record.source = source
            record.source_id = source_id
            record.category = category
            record.difficulty = difficulty
            record.explanation = explanation
            record.active = True
            imported[model].add(statement)
        for model, statements in imported.items():
            for statement, record in existing[model].items():
                if statement not in statements:
                    record.active = False
    return len(imported[Fact]), len(imported[Fake])


if __name__ == "__main__":
    result = import_files([Path(arg) for arg in sys.argv[1:]] or CONTENT_FILES)
    print(f"Imported {result[0]} facts and {result[1]} fakes")
