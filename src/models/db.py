"""SQLite schema and access — Phase 1.

Contract: creates and reads the tables requirements, sections, win_themes, proof_points,
provenance, assurance_findings and runs. One `runs` row per pipeline execution carrying
the automation rate and per-agent timings.

Design notes:
- No ORM. Plain sqlite3 keeps the schema readable and the dependency list honest.
- Enum columns carry CHECK constraints generated from the schemas module, so a typo in
  an agent fails at the database boundary rather than silently persisting.
- Every save_*/load_* pair takes and returns a pydantic contract. No loose dicts cross
  this boundary either.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.models.schemas import (
    AssuranceFinding,
    DeliverableForm,
    FindingType,
    OutlineMode,
    Priority,
    ProofPoint,
    ProvenanceKind,
    ProvenanceRecord,
    ReqType,
    Requirement,
    RunRecord,
    SectionStatus,
    Severity,
    WinTheme,
)


def _check(column: str, enum: type[Enum]) -> str:
    """Render a CHECK constraint listing every legal value of an enum."""
    values = ", ".join(f"'{m.value}'" for m in enum)
    return f"CHECK ({column} IN ({values}))"


SCHEMA_SQL = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id                  TEXT PRIMARY KEY,
    rfp_path            TEXT NOT NULL,
    mode                TEXT {_check('mode', OutlineMode)},
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL DEFAULT 'RUNNING',
    sections_total      INTEGER NOT NULL DEFAULT 0,
    sections_automated  INTEGER NOT NULL DEFAULT 0,
    automation_rate     REAL,
    timings_json        TEXT NOT NULL DEFAULT '{{}}',
    token_counts_json   TEXT NOT NULL DEFAULT '{{}}',
    CHECK (sections_automated <= sections_total)
);

CREATE TABLE IF NOT EXISTS requirements (
    id                TEXT NOT NULL,
    run_id            TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_section    TEXT NOT NULL,
    text              TEXT NOT NULL,
    req_type          TEXT NOT NULL {_check('req_type', ReqType)},
    priority          TEXT NOT NULL {_check('priority', Priority)},
    deliverable_form  TEXT NOT NULL {_check('deliverable_form', DeliverableForm)},
    cue_evidence      TEXT NOT NULL DEFAULT '',
    extracted_by      TEXT NOT NULL DEFAULT 'cue',
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS sections (
    id                   TEXT NOT NULL,
    run_id               TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    order_index          INTEGER NOT NULL,
    title                TEXT NOT NULL,
    purpose              TEXT NOT NULL DEFAULT '',
    deliverable_form     TEXT NOT NULL {_check('deliverable_form', DeliverableForm)},
    requirement_ids_json TEXT NOT NULL DEFAULT '[]',
    themes_json          TEXT NOT NULL DEFAULT '[]',
    target_words         INTEGER NOT NULL DEFAULT 0,
    content_md           TEXT NOT NULL DEFAULT '',
    asset_paths_json     TEXT NOT NULL DEFAULT '[]',
    status               TEXT NOT NULL {_check('status', SectionStatus)},
    retry_count          INTEGER NOT NULL DEFAULT 0 CHECK (retry_count BETWEEN 0 AND 2),
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS win_themes (
    id                   TEXT NOT NULL,
    run_id               TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    statement            TEXT NOT NULL,
    buyer_pain_addressed TEXT NOT NULL DEFAULT '',
    proof_ids_json       TEXT NOT NULL DEFAULT '[]',
    requirement_ids_json TEXT NOT NULL DEFAULT '[]',
    dropped              INTEGER NOT NULL DEFAULT 0,
    drop_reason          TEXT,
    PRIMARY KEY (run_id, id),
    CHECK (dropped = 0 OR drop_reason IS NOT NULL)
);

-- The proof library is corpus-level, not per-run: no run_id.
CREATE TABLE IF NOT EXISTS proof_points (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    text        TEXT NOT NULL,
    source_ref  TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS provenance (
    pk              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    section_id      TEXT NOT NULL,
    sentence_index  INTEGER NOT NULL,
    sentence        TEXT NOT NULL,
    kind            TEXT NOT NULL {_check('kind', ProvenanceKind)},
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    confidence      REAL,
    UNIQUE (run_id, section_id, sentence_index)
);

CREATE TABLE IF NOT EXISTS assurance_findings (
    pk             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    finding_type   TEXT NOT NULL {_check('finding_type', FindingType)},
    severity       TEXT NOT NULL {_check('severity', Severity)},
    detail         TEXT NOT NULL,
    section_id     TEXT,
    requirement_id TEXT,
    evidence       TEXT NOT NULL DEFAULT '',
    resolved       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_requirements_run ON requirements(run_id);
CREATE INDEX IF NOT EXISTS idx_sections_run     ON sections(run_id, order_index);
CREATE INDEX IF NOT EXISTS idx_provenance_sect  ON provenance(run_id, section_id);
CREATE INDEX IF NOT EXISTS idx_findings_run     ON assurance_findings(run_id);
"""

TABLES = (
    "runs",
    "requirements",
    "sections",
    "win_themes",
    "proof_points",
    "provenance",
    "assurance_findings",
)


# --------------------------------------------------------------------------------------
# Connection lifecycle
# --------------------------------------------------------------------------------------


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and row access by name.

    Pass ":memory:" for tests. Defaults to the configured sqlite_path.
    """
    if path is None:
        from config import get_settings

        path = get_settings().sqlite_path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create every table. Idempotent."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# --------------------------------------------------------------------------------------
# Serialization helpers
# --------------------------------------------------------------------------------------


def _j(value: Any) -> str:
    return json.dumps(value, default=str)


def _unj(value: str | None) -> Any:
    return json.loads(value) if value else None


def _enum(value: Enum | None) -> str | None:
    return value.value if value is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# --------------------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------------------


def save_run(conn: sqlite3.Connection, run: RunRecord) -> None:
    conn.execute(
        """INSERT INTO runs (id, rfp_path, mode, started_at, finished_at, status,
                             sections_total, sections_automated, automation_rate,
                             timings_json, token_counts_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             finished_at=excluded.finished_at, status=excluded.status,
             mode=excluded.mode,
             sections_total=excluded.sections_total,
             sections_automated=excluded.sections_automated,
             automation_rate=excluded.automation_rate,
             timings_json=excluded.timings_json,
             token_counts_json=excluded.token_counts_json""",
        (
            run.id,
            run.rfp_path,
            _enum(run.mode),
            _iso(run.started_at),
            _iso(run.finished_at),
            run.status,
            run.sections_total,
            run.sections_automated,
            run.automation_rate,
            _j(run.timings),
            _j(run.token_counts),
        ),
    )
    conn.commit()


def load_run(conn: sqlite3.Connection, run_id: str) -> RunRecord | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return RunRecord(
        id=row["id"],
        rfp_path=row["rfp_path"],
        mode=OutlineMode(row["mode"]) if row["mode"] else None,
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=(
            datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
        ),
        status=row["status"],
        sections_total=row["sections_total"],
        sections_automated=row["sections_automated"],
        automation_rate=row["automation_rate"],
        timings=_unj(row["timings_json"]) or {},
        token_counts=_unj(row["token_counts_json"]) or {},
    )


# --------------------------------------------------------------------------------------
# requirements
# --------------------------------------------------------------------------------------


def save_requirements(
    conn: sqlite3.Connection, run_id: str, reqs: Iterable[Requirement]
) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO requirements
             (id, run_id, source_section, text, req_type, priority,
              deliverable_form, cue_evidence, extracted_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            (
                r.id,
                run_id,
                r.source_section,
                r.text,
                r.req_type.value,
                r.priority.value,
                r.deliverable_form.value,
                r.cue_evidence,
                r.extracted_by,
            )
            for r in reqs
        ],
    )
    conn.commit()


def load_requirements(conn: sqlite3.Connection, run_id: str) -> list[Requirement]:
    rows = conn.execute(
        "SELECT * FROM requirements WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    return [
        Requirement(
            id=r["id"],
            source_section=r["source_section"],
            text=r["text"],
            req_type=ReqType(r["req_type"]),
            priority=Priority(r["priority"]),
            deliverable_form=DeliverableForm(r["deliverable_form"]),
            cue_evidence=r["cue_evidence"],
            extracted_by=r["extracted_by"],
        )
        for r in rows
    ]


# --------------------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------------------


def save_section(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    id: str,
    order_index: int,
    title: str,
    deliverable_form: DeliverableForm,
    status: SectionStatus,
    purpose: str = "",
    requirement_ids: list[str] | None = None,
    themes: list[str] | None = None,
    target_words: int = 0,
    content_md: str = "",
    asset_paths: list[str] | None = None,
    retry_count: int = 0,
) -> None:
    """Persist one section.

    Kept as explicit keyword arguments because a section row is stitched together from
    an OutlineSection (plan) and a GeneratedSection (draft), which no single contract
    spans.
    """
    conn.execute(
        """INSERT OR REPLACE INTO sections
             (id, run_id, order_index, title, purpose, deliverable_form,
              requirement_ids_json, themes_json, target_words, content_md,
              asset_paths_json, status, retry_count)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            id,
            run_id,
            order_index,
            title,
            purpose,
            deliverable_form.value,
            _j(requirement_ids or []),
            _j(themes or []),
            target_words,
            content_md,
            _j(asset_paths or []),
            status.value,
            retry_count,
        ),
    )
    conn.commit()


def load_sections(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM sections WHERE run_id = ? ORDER BY order_index", (run_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["requirement_ids"] = _unj(d.pop("requirement_ids_json")) or []
        d["themes"] = _unj(d.pop("themes_json")) or []
        d["asset_paths"] = _unj(d.pop("asset_paths_json")) or []
        d["deliverable_form"] = DeliverableForm(d["deliverable_form"])
        d["status"] = SectionStatus(d["status"])
        out.append(d)
    return out


# --------------------------------------------------------------------------------------
# win_themes
# --------------------------------------------------------------------------------------


def save_win_themes(
    conn: sqlite3.Connection, run_id: str, themes: Iterable[WinTheme]
) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO win_themes
             (id, run_id, statement, buyer_pain_addressed, proof_ids_json,
              requirement_ids_json, dropped, drop_reason)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            (
                t.id,
                run_id,
                t.statement,
                t.buyer_pain_addressed,
                _j(t.proof_ids),
                _j(t.requirement_ids_covered),
                int(t.dropped),
                t.drop_reason,
            )
            for t in themes
        ],
    )
    conn.commit()


def load_win_themes(conn: sqlite3.Connection, run_id: str) -> list[WinTheme]:
    rows = conn.execute(
        "SELECT * FROM win_themes WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    return [
        WinTheme(
            id=r["id"],
            statement=r["statement"],
            buyer_pain_addressed=r["buyer_pain_addressed"],
            proof_ids=_unj(r["proof_ids_json"]) or [],
            requirement_ids_covered=_unj(r["requirement_ids_json"]) or [],
            dropped=bool(r["dropped"]),
            drop_reason=r["drop_reason"],
        )
        for r in rows
    ]


# --------------------------------------------------------------------------------------
# proof_points
# --------------------------------------------------------------------------------------


def save_proof_points(conn: sqlite3.Connection, proofs: Iterable[ProofPoint]) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO proof_points (id, title, text, source_ref, tags_json)
           VALUES (?,?,?,?,?)""",
        [(p.id, p.title, p.text, p.source_ref, _j(p.tags)) for p in proofs],
    )
    conn.commit()


def load_proof_points(conn: sqlite3.Connection) -> list[ProofPoint]:
    rows = conn.execute("SELECT * FROM proof_points ORDER BY id").fetchall()
    return [
        ProofPoint(
            id=r["id"],
            title=r["title"],
            text=r["text"],
            source_ref=r["source_ref"],
            tags=_unj(r["tags_json"]) or [],
        )
        for r in rows
    ]


# --------------------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------------------


def save_provenance(
    conn: sqlite3.Connection, run_id: str, records: Iterable[ProvenanceRecord]
) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO provenance
             (run_id, section_id, sentence_index, sentence, kind, source_ids_json,
              confidence)
           VALUES (?,?,?,?,?,?,?)""",
        [
            (
                run_id,
                p.section_id,
                p.sentence_index,
                p.sentence,
                p.kind.value,
                _j(p.source_ids),
                p.confidence,
            )
            for p in records
        ],
    )
    conn.commit()


def load_provenance(
    conn: sqlite3.Connection, run_id: str, section_id: str | None = None
) -> list[ProvenanceRecord]:
    if section_id is None:
        rows = conn.execute(
            "SELECT * FROM provenance WHERE run_id = ? ORDER BY section_id, sentence_index",
            (run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM provenance WHERE run_id = ? AND section_id = ?
               ORDER BY sentence_index""",
            (run_id, section_id),
        ).fetchall()
    return [
        ProvenanceRecord(
            section_id=r["section_id"],
            sentence_index=r["sentence_index"],
            sentence=r["sentence"],
            kind=ProvenanceKind(r["kind"]),
            source_ids=_unj(r["source_ids_json"]) or [],
            confidence=r["confidence"],
        )
        for r in rows
    ]


# --------------------------------------------------------------------------------------
# assurance_findings
# --------------------------------------------------------------------------------------


def save_findings(
    conn: sqlite3.Connection, run_id: str, findings: Iterable[AssuranceFinding]
) -> None:
    conn.executemany(
        """INSERT INTO assurance_findings
             (run_id, finding_type, severity, detail, section_id, requirement_id,
              evidence, resolved)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            (
                run_id,
                f.finding_type.value,
                f.severity.value,
                f.detail,
                f.section_id,
                f.requirement_id,
                f.evidence,
                int(f.resolved),
            )
            for f in findings
        ],
    )
    conn.commit()


def load_findings(conn: sqlite3.Connection, run_id: str) -> list[AssuranceFinding]:
    rows = conn.execute(
        "SELECT * FROM assurance_findings WHERE run_id = ? ORDER BY pk", (run_id,)
    ).fetchall()
    return [
        AssuranceFinding(
            finding_type=FindingType(r["finding_type"]),
            severity=Severity(r["severity"]),
            detail=r["detail"],
            section_id=r["section_id"],
            requirement_id=r["requirement_id"],
            evidence=r["evidence"],
            resolved=bool(r["resolved"]),
        )
        for r in rows
    ]
