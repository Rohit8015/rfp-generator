"""A13 Voice Harmonizer + Risk Reviewer — Phase 9. DETERMINISTIC: zero LLM calls.

Single pass over the assembled document for register consistency. Flags absolute
guarantees, unbounded commitments and overclaiming language as RISK_LANGUAGE, and
register outliers as VOICE_DRIFT.

Risk language is caught by pattern, not by judgement. "We guarantee 100% uptime" is
dangerous because of what it says, not because of how it reads, and the phrases that
create unbounded contractual exposure are a small, well-known set. A model asked to spot
overclaiming will miss some and invent others; a pattern list is auditable and a lawyer
can extend it.

Voice drift uses a readability spread rather than an opinion about tone. Sections
written by different writers diverge measurably in sentence length and word length, and
an outlier is worth a human glance even when its prose is fine.
"""

from __future__ import annotations

import re
import statistics

from src.models.schemas import (
    AssuranceFinding,
    FindingType,
    GeneratedSection,
    ProvenanceKind,
    Severity,
)
from src.utils import docparse

#: Language creating absolute or unbounded commitments. Each entry is a liability, not
#: a style preference. Severity reflects contractual exposure, not tone.
RISK_PATTERNS: list[tuple[str, str, Severity]] = [
    (r"\b(?:we\s+)?guarantee\w*\b(?![^.]{0,40}\bsubject to\b)",
     "unqualified guarantee", Severity.BLOCKER),
    (r"\b100\s*%\s*(?:uptime|availability|accuracy|success|satisfaction)",
     "absolute performance claim", Severity.BLOCKER),
    (r"\bunlimited\s+(?:liability|indemnit\w+|coverage|support)",
     "unbounded liability", Severity.BLOCKER),
    (r"\bfull\s+and\s+unlimited\b", "unbounded commitment", Severity.BLOCKER),
    (r"\bzero\s+(?:bugs?|defects?|downtime|risk|errors?)\b",
     "absolute quality claim", Severity.BLOCKER),
    (r"\bnever\s+(?:fail\w*|make\w*\s+mistakes?|experience\s+downtime)\b",
     "absolute reliability claim", Severity.BLOCKER),
    (r"\b(?:all|every)\s+(?:our\s+)?(?:clients?|implementations?|projects?)\s+"
     r"(?:have\s+)?(?:achiev\w+|deliver\w+|complet\w+)", "universal claim", Severity.WARN),
    (r"\bwe\s+accept\s+full\s+responsibility\b", "unbounded responsibility",
     Severity.BLOCKER),
    (r"\bno\s+exceptions?\b", "absolute commitment", Severity.WARN),
    (r"\bat\s+least\s+\d+\s*%\s+under\s+budget\b", "unqualified financial promise",
     Severity.BLOCKER),
    (r"\bwill\s+never\b", "absolute negative commitment", Severity.WARN),
    (r"\b(?:always|invariably)\s+(?:deliver|achiev|exceed)\w*", "absolute claim",
     Severity.WARN),
]

_COMPILED = [(re.compile(p, re.I), label, sev) for p, label, sev in RISK_PATTERNS]

#: A section this far from the document's mean readability is a register outlier.
VOICE_DRIFT_SIGMA = 1.8
MIN_SECTIONS_FOR_DRIFT = 4
MIN_WORDS_FOR_DRIFT = 60


class VoicePolisher:
    """Reviews register and risk language. One public method: review()."""

    def review(self, sections: list[GeneratedSection]) -> list[AssuranceFinding]:
        findings = self._risk_language(sections)
        findings.extend(self._voice_drift(sections))
        return findings

    # --- risk language --------------------------------------------------------------

    @staticmethod
    def _risk_language(sections: list[GeneratedSection]) -> list[AssuranceFinding]:
        findings: list[AssuranceFinding] = []
        for section in sections:
            # Stakeholder briefs describe what a human must write; they are not claims.
            if section.sentences and all(
                r.kind is ProvenanceKind.STAKEHOLDER for r in section.sentences
            ):
                continue
            seen: set[tuple[str, str]] = set()
            for pattern, label, severity in _COMPILED:
                for match in pattern.finditer(section.content_md):
                    phrase = match.group(0).strip()
                    key = (label, phrase.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(AssuranceFinding(
                        finding_type=FindingType.RISK_LANGUAGE,
                        severity=severity,
                        detail=f"{label}: '{phrase}'",
                        section_id=section.section_id,
                        evidence=VoicePolisher._context(section.content_md, match.start()),
                    ))
        return findings

    @staticmethod
    def _context(text: str, position: int, width: int = 160) -> str:
        start = max(0, position - width // 3)
        return re.sub(r"\s+", " ", text[start : position + width]).strip()

    # --- register -------------------------------------------------------------------

    def _voice_drift(self, sections: list[GeneratedSection]) -> list[AssuranceFinding]:
        scored = [
            (s, self.readability(s.content_md)) for s in sections
            if len(s.content_md.split()) >= MIN_WORDS_FOR_DRIFT
        ]
        if len(scored) < MIN_SECTIONS_FOR_DRIFT:
            return []

        values = [score for _, score in scored]
        mean = statistics.mean(values)
        spread = statistics.pstdev(values)
        if spread < 1e-6:
            return []

        findings: list[AssuranceFinding] = []
        for section, score in scored:
            deviation = abs(score - mean) / spread
            if deviation < VOICE_DRIFT_SIGMA:
                continue
            findings.append(AssuranceFinding(
                finding_type=FindingType.VOICE_DRIFT,
                severity=Severity.INFO,
                detail=(
                    f"register differs from the rest of the document "
                    f"(readability {score:.1f} against a document mean of {mean:.1f}, "
                    f"{deviation:.1f} standard deviations out)"
                ),
                section_id=section.section_id,
                evidence=section.content_md[:160].replace("\n", " "),
            ))
        return findings

    @staticmethod
    def readability(markdown: str) -> float:
        """Flesch reading ease. Higher is plainer.

        Used only comparatively, to find sections out of step with their neighbours.
        The absolute value is not a quality judgement.
        """
        sentences = docparse.split_sentences(re.sub(r"^#+\s.*$", "", markdown,
                                                    flags=re.MULTILINE))
        words = re.findall(r"[A-Za-z']+", markdown)
        if not sentences or not words:
            return 0.0
        syllables = sum(VoicePolisher._syllables(w) for w in words)
        words_per_sentence = len(words) / len(sentences)
        syllables_per_word = syllables / len(words)
        return round(
            206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word, 2
        )

    @staticmethod
    def _syllables(word: str) -> int:
        word = word.lower().strip("'")
        if not word:
            return 0
        groups = re.findall(r"[aeiouy]+", word)
        count = len(groups)
        if word.endswith("e") and count > 1 and not word.endswith(("le", "ee")):
            count -= 1
        return max(1, count)


def blocking_findings(findings: list[AssuranceFinding]) -> list[AssuranceFinding]:
    """Findings that must be resolved before a document is sent."""
    return [f for f in findings if f.severity is Severity.BLOCKER]
