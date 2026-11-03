"""Decision Memo Forge - local-first decision document reviewer.

A standard-library analysis engine for decision memos, RFCs, proposals,
one-pagers and postmortems. Deterministic, offline, no API keys.

Pipeline
--------
1. parse_document()      -> structure (headings, sections, tables, lists, sentences)
2. detect_archetype()    -> which kind of document is this?
3. detect_sections()     -> which required sections are present / missing?
4. analyze_options()     -> options list, criteria consistency, strawman detection
5. compute_metrics()     -> readability, hedging, jargon, numbers, owners, dates
6. run_rules()           -> 40+ findings, each with evidence, why and a fix
7. score_axes()          -> 5-axis 0-100 scorecard with structural caps
8. build_fix_plan()      -> prioritised plan + rewrite scaffold
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

CODE_FENCE = "\x60\x60\x60"

# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

HEDGE_TERMS = [
    "might", "could", "possibly", "perhaps", "probably", "arguably", "somewhat",
    "fairly", "rather", "maybe", "hopefully", "apparently", "seems", "seemingly",
    "i think", "we think", "we feel", "it seems", "kind of", "sort of", "a bit",
    "to some extent", "in theory", "i guess", "more or less",
    "generally speaking", "we might", "could potentially",
]

JARGON_TERMS = [
    "synergy", "synergies", "leverage", "circle back", "deep dive",
    "low-hanging fruit", "move the needle", "paradigm", "value-add", "value add",
    "ideate", "ideation", "deliverables", "operationalize", "operationalization",
    "holistic", "holistically", "core competency", "north star", "table stakes",
    "boil the ocean", "boil down", "drill down", "socialize", "unpack",
    "double-click", "loop in", "touch base", "best practices", "bandwidth",
    "empower", "empowerment", "ecosystem", "seamless", "seamlessly", "game changer",
    "win-win", "utilize", "incentivize", "traction", "expedite", "facilitate",
    "enablement", "reimagine", "thought leadership", "value proposition",
    "actionable insights", "stakeholder alignment", "quick win",
]

FILLER_TERMS = [
    "basically", "actually", "really", "very", "quite", "just", "literally",
    "essentially", "simply", "definitely", "absolutely", "totally", "obviously",
]

VAGUE_QUANTIFIERS = [
    "a lot of", "lots of", "a number of", "a few", "several", "many", "few",
    "significant", "substantially", "various", "multiple", "numerous", "certain",
    "reasonable", "appropriate", "sufficient", "adequate", "roughly", "approximately",
    "around", "soon", "shortly", "in the near term", "as needed", "et cetera",
    "etc.", "and so on", "a variety of", "plenty", "some",
]

PLACEHOLDER_PATTERNS = [
    (r"\bTBD\b", "TBD"),
    (r"\bTODO\b", "TODO"),
    (r"\bTK\b", "TK"),
    (r"\?{3,}", "???"),
    (r"\bXXX+\b", "XXX"),
    (r"\[\s*(insert|todo|name|date)[^\]]*\]", "[insert ...]"),
    (r"\bLorem ipsum\b", "Lorem ipsum"),
]

POSITIVE_OPTION_WORDS = [
    "robust", "scalable", "simple", "best", "modern", "fast", "cheap", "clean",
    "smart", "safe", "proven", "efficient", "flexible", "lightweight", "advanced",
    "optimal", "superior", "elegant", "solid", "reliable",
]

SEVERITY_PENALTY = {"high": 9.0, "medium": 4.5, "low": 1.5}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# ---------------------------------------------------------------------------
# Archetype definitions
# ---------------------------------------------------------------------------

ARCHETYPE_INFO: Dict[str, Dict[str, Any]] = {
    "memo": {
        "label": "Decision memo",
        "blurb": "A short memo that states a decision and asks for a yes or a no.",
        "signals": ["subject:", "to:", "from:", "memo", "recommendation", "we need to decide"],
        "sections": [
            ("context", "required"), ("decision", "required"), ("options", "required"),
            ("recommendation", "required"), ("tradeoffs", "optional"),
            ("risks", "required"), ("reversibility", "optional"),
            ("unknowns", "optional"), ("impact", "optional"),
            ("owners", "required"), ("timeline", "optional"), ("ask", "required"),
        ],
    },
    "rfc": {
        "label": "RFC / design doc",
        "blurb": "A longer technical proposal that a team reviews before work starts.",
        "signals": ["rfc", "design doc", "proposal", "abstract", "motivation", "alternatives"],
        "sections": [
            ("context", "required"), ("decision", "required"), ("options", "required"),
            ("recommendation", "required"), ("tradeoffs", "required"),
            ("risks", "required"), ("reversibility", "required"),
            ("unknowns", "required"), ("impact", "required"),
            ("owners", "required"), ("timeline", "required"), ("ask", "required"),
        ],
    },
    "proposal": {
        "label": "Business proposal",
        "blurb": "A business case: problem, options, costs, benefits, and an ask.",
        "signals": ["business case", "proposal", "roi", "benefit", "cost", "budget", "stakeholder"],
        "sections": [
            ("context", "required"), ("decision", "required"), ("options", "required"),
            ("recommendation", "required"), ("tradeoffs", "optional"),
            ("risks", "required"), ("reversibility", "optional"),
            ("unknowns", "optional"), ("impact", "required"),
            ("owners", "required"), ("timeline", "required"), ("ask", "required"),
        ],
    },
    "one_pager": {
        "label": "One-pager",
        "blurb": "One page: the situation, the choice, the cost, and the ask.",
        "signals": ["one-pager", "one pager", "tl;dr", "summary", "ask"],
        "sections": [
            ("context", "required"), ("decision", "required"),
            ("recommendation", "required"), ("impact", "required"), ("ask", "required"),
        ],
    },
    "postmortem": {
        "label": "Postmortem",
        "blurb": "What broke, what it cost, and what changes next.",
        "signals": ["postmortem", "post-mortem", "incident", "outage", "root cause", "timeline of events"],
        "sections": [
            ("context", "required"), ("decision", "optional"),
            ("recommendation", "required"), ("tradeoffs", "optional"),
            ("risks", "optional"), ("reversibility", "optional"),
            ("unknowns", "required"), ("impact", "required"),
            ("owners", "required"), ("timeline", "required"), ("ask", "optional"),
        ],
    },
    "status_update": {
        "label": "Status update",
        "blurb": "Where things stand, what is blocked, and what happens next.",
        "signals": ["status update", "weekly update", "progress", "this week", "next week", "blocked"],
        "sections": [
            ("context", "required"), ("decision", "optional"),
            ("recommendation", "required"), ("impact", "required"),
            ("owners", "required"), ("timeline", "required"), ("ask", "optional"),
        ],
    },
    "exploratory": {
        "label": "Exploratory note",
        "blurb": "Early thinking: options, unknowns, and a next experiment.",
        "signals": ["exploration", "spike", "brainstorm", "open questions", "we don't know yet"],
        "sections": [
            ("context", "required"), ("decision", "optional"),
            ("options", "required"), ("recommendation", "optional"),
            ("tradeoffs", "optional"), ("risks", "optional"),
            ("reversibility", "optional"), ("unknowns", "required"),
            ("impact", "optional"), ("owners", "required"),
            ("timeline", "required"), ("ask", "optional"),
        ],
    },
}

ARCHETYPE_ORDER = list(ARCHETYPE_INFO.keys())

# section key -> heading regexes, body regexes, guidance
SECTION_SPECS: Dict[str, Dict[str, Any]] = {
    "context": {
        "label": "Context / problem",
        "headings": [
            r"^\s*(context|background|problem|situation|overview|summary|current state|why now|introduction|intro|where we are|status)\b",
            r"^\s*\d+[\.\)]\s*(context|background|problem|overview|summary)\b",
        ],
        "body": [
            r"\b(currently|today|status quo|right now|as of today|we have been|the problem is|background is|at the moment)\b",
        ],
        "guidance": "Two or three sentences on how the world looks today and why this decision is on the table now.",
    },
    "decision": {
        "label": "Decision statement",
        "headings": [
            r"^\s*(decision|decision statement|question|the question|what we are deciding|decide|scope)\b",
            r"^\s*\d+[\.\)]\s*(decision|question)\b",
        ],
        "body": [
            r"\b(we need to decide|we must decide|we are deciding|the decision is|should we|whether to|do we want to)\b",
        ],
        "guidance": "One sentence: the exact question being answered, phrased so it can be answered yes or no.",
    },
    "options": {
        "label": "Options considered",
        "headings": [
            r"^\s*(options|option|alternatives|approaches|choices|candidate options|considered)\b",
            r"^\s*\d+[\.\)]\s*(options|alternatives|approaches)\b",
        ],
        "body": [
            r"\b(option [a-z0-9]|approach [a-z0-9]|alternative [a-z0-9]|we could|another option|options are)\b",
        ],
        "guidance": "List the realistic options, including doing nothing, with the criteria you will compare them on.",
    },
    "recommendation": {
        "label": "Recommendation",
        "headings": [
            r"^\s*(recommendation|recommended|proposal|proposed|plan of record|our plan|actions?|lessons?|lesson learned|takeaways?|next steps?|what's next|what we are changing)\b",
            r"^\s*\d+[\.\)]\s*(recommendation|proposal|actions?|lessons?)\b",
        ],
        "body": [
            r"\b(recommend|i recommend|we recommend|my recommendation|i propose|we propose|the plan is|we should go with|we will proceed|we are going with)\b",
        ],
        "guidance": "State the choice you want made, in one sentence, in the active voice.",
    },
    "tradeoffs": {
        "label": "Trade-offs / what we give up",
        "headings": [
            r"^\s*(trade-?offs?|what we give up|what we lose|costs?|downside|price we pay|consequences)\b",
        ],
        "body": [
            r"\b(trade-?off|in exchange|at the cost of|we give up|we lose|we accept|price we pay|downside|we sacrifice)\b",
        ],
        "guidance": "Name what the recommendation costs you: speed, money, features, or another team.",
    },
    "risks": {
        "label": "Risks and mitigations",
        "headings": [
            r"^\s*(risks?|risk and mitigation|threats?|concerns?|failure modes?|what could go wrong|mitigations?)\b",
        ],
        "body": [
            r"\b(risk of|risk that|the risk|mitigation|mitigate|if this fails|failure mode|worst case|threat)\b",
        ],
        "guidance": "For each real risk: what it is, how likely, and what you will do about it.",
    },
    "reversibility": {
        "label": "Reversibility / how we undo it",
        "headings": [
            r"^\s*(reversibility|reversible|rollback|roll back|undo|how we reverse|exit strategy|one-way|two-way)\b",
        ],
        "body": [
            r"\b(reversible|irreversible|rollback|roll back|undo|revert|back out|two-way door|one-way door|easy to undo)\b",
        ],
        "guidance": "Say whether this decision can be reversed, and if so, what reversing it would cost in time and money.",
    },
    "unknowns": {
        "label": "Open questions / unknowns",
        "headings": [
            r"^\s*(open questions?|unknowns?|tbd|to be determined|questions|assumptions|research needed|what we don't know)\b",
        ],
        "body": [
            r"\b(open question|unknown|unclear|we don't know|not sure|to be determined|needs research|assume that|assumption)\b",
        ],
        "guidance": "List what you do not know yet, and who will find out, by when.",
    },
    "impact": {
        "label": "Impact / effort / cost",
        "headings": [
            r"^\s*(impact|effort|cost|roi|benefits?|numbers|resources?|success metrics?|success criteria|outcomes?)\b",
        ],
        "body": [
            r"\b(costs? us|will cost|effort|estimate|per (day|week|month|quarter|year)|saves|roi|impact|success metric|we will know)\b",
        ],
        "guidance": "Put numbers on it: money, engineer-weeks, users, latency, or whatever your currency is.",
    },
    "owners": {
        "label": "Owners / who does what",
        "headings": [
            r"^\s*(owners?|responsibilities?|roles?|who does what|dri|assignees?|next steps?|action items?|tasks?)\b",
        ],
        "body": [
            r"\b(owner|dri|responsible for|assignee|action item|next step|will own|takes it)\b",
        ],
        "guidance": "Name one accountable person per action item. Teams are not owners.",
    },
    "timeline": {
        "label": "Timeline / milestones",
        "headings": [
            r"^\s*(timeline|milestones?|schedule|roadmap|phases?|when|dates?|rollout plan)\b",
        ],
        "body": [
            r"\b(timeline|milestone|by (monday|tuesday|wednesday|thursday|friday)|next week|next month|q[1-4] 20\d\d|phase \d|rollout)\b",
        ],
        "guidance": "Give real dates or weeks, not 'soon'. Include the decision date itself.",
    },
    "ask": {
        "label": "The ask",
        "headings": [
            r"^\s*(ask|request|approval|approvals?|decision required|next steps? for you|what i need)\b",
        ],
        "body": [
            r"\b(please approve|need your approval|requesting approval|sign-?off|looking for approval|we need a decision by|asking for|can you approve|we need your)\b",
        ],
        "guidance": "Say exactly what you want, from whom, and by when.",
    },
}

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z'\-]*", text or "")


def _term_pattern(term: str) -> str:
    return r"(?<![a-z])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![a-z])"


def _count_terms(text: str, terms: List[str]) -> int:
    return sum(len(re.findall(_term_pattern(t), text, flags=re.IGNORECASE)) for t in terms)


def _terms_present(text: str, terms: List[str]) -> List[str]:
    return [t for t in terms if re.search(_term_pattern(t), text, flags=re.IGNORECASE)]


_ABBREVS = ["e.g.", "i.e.", "etc.", "vs.", "Mr.", "Mrs.", "Dr.", "Prof.",
            "approx.", "Fig.", "Inc.", "St.", "No.", "U.S.", "a.m.", "p.m."]


def split_sentences(text: str) -> List[str]:
    """Split a block of prose into sentences, protecting common abbreviations."""
    protected = text
    for abbr in _ABBREVS:
        protected = protected.replace(abbr, abbr.replace(".", "\u0001"))
    parts = re.split(r"(?<=[.!?])\s+", protected)
    out = []
    for part in parts:
        cleaned = part.replace("\u0001", ".").strip()
        if cleaned:
            out.append(cleaned)
    return out


KNOWN_SECTION_STARTS = [
    "context", "background", "problem", "problem statement", "summary", "overview",
    "decision", "decision statement", "question", "the question", "options",
    "alternatives", "approaches", "recommendation", "proposal", "risks", "threats",
    "trade-offs", "tradeoffs", "what we give up", "impact", "cost", "costs", "effort",
    "timeline", "milestones", "schedule", "owners", "ownership", "next steps",
    "action items", "ask", "the ask", "unknowns", "open questions", "reversibility",
    "rollback", "success metrics", "benefits", "notes", "appendix", "why now",
    "current state", "situation", "motivation", "goals", "success criteria",
    "actions", "lessons", "lesson learned", "takeaways", "blocked", "blockers",
    "summary", "impact", "where we are", "status", "questions", "the problem",
    "what changed", "data", "evidence", "what we know",
]

_KNOWN_START_RE = re.compile(
    r"^\**(" + "|".join(re.escape(k) for k in KNOWN_SECTION_STARTS) + r")\b\s*:?\s*",
    flags=re.IGNORECASE)


def _is_known_section_line(stripped: str) -> bool:
    if not stripped or len(stripped) > 95:
        return False
    return bool(_KNOWN_START_RE.match(stripped))


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 70:
        return False
    if re.match(r"^#{1,6}\s+\S", stripped):
        return True
    if re.match(r"^\*\*[^*\n]+\*\*:?$", stripped):
        return True
    if re.match(r"^\d+[\.\)]\s+\S", stripped) and len(stripped.split()) <= 8:
        return True
    if stripped.endswith(":") and len(stripped.split()) <= 9:
        return True
    if stripped.isupper() and len(stripped) > 2 and len(stripped.split()) <= 7:
        return True
    if re.match(r"^(subject|to|from|date|re)\s*:", stripped, flags=re.IGNORECASE):
        return True
    if _is_known_section_line(stripped):
        return True
    return False


def _is_title_line(lines: List[str], idx: int) -> bool:
    """A short standalone title line such as 'Context' followed by a blank line."""
    stripped = lines[idx].strip()
    if not stripped or len(stripped) > 45:
        return False
    if len(stripped.split()) > 5:
        return False
    if stripped[-1] in ".,;:!?":
        return False
    if not stripped[0].isupper():
        return False
    nxt = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
    if not nxt:
        return True
    if nxt.startswith(("-", "*", "|", "#")) or re.match(r"^\d+[.)]\s", nxt):
        return True
    return False


def _strip_heading_markup(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r"^#{1,6}\s+", "", stripped)
    stripped = re.sub(r"^\*\*|\*\*$", "", stripped)
    stripped = re.sub(r"^\d+[\.\)]\s+", "", stripped)
    stripped = stripped.rstrip(":").strip()
    return stripped


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_document(text: str) -> Dict[str, Any]:
    raw = (text or "").replace("\r\n", "\n")
    lines = raw.split("\n")

    headings: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    current = {"title": "(preamble)", "body": []}
    in_code_fence = False
    for idx, line in enumerate(lines):
        if line.strip().startswith(CODE_FENCE):
            in_code_fence = not in_code_fence
            current["body"].append(line)
            continue
        is_head = (not in_code_fence) and (
            _looks_like_heading(line) or _is_title_line(lines, idx))
        if is_head:
            title = _strip_heading_markup(line)
            headings.append({"text": title, "raw": line.strip()})
            sections.append(current)
            current = {"title": title, "body": []}
        else:
            current["body"].append(line)
    sections.append(current)
    for sec in sections:
        sec["text"] = "\n".join(sec["body"]).strip()
        sec["words"] = len(_words(sec["text"]))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    sentences: List[str] = []
    for para in paragraphs:
        for sent in split_sentences(para):
            sentences.append(sent)

    tables = _parse_tables(raw)
    bullets = [ln.strip() for ln in lines if re.match(r"^\s*([-*+])\s+\S", ln)]
    numbered = [ln.strip() for ln in lines if re.match(r"^\s*\d+[\.\)]\s+\S", ln)]

    word_count = len(_words(raw))
    return {
        "raw": raw,
        "headings": headings,
        "sections": sections,
        "paragraphs": paragraphs,
        "sentences": sentences,
        "tables": tables,
        "bullets": bullets,
        "numbered": numbered,
        "word_count": word_count,
        "line_count": len([ln for ln in lines if ln.strip()]),
    }


def _parse_tables(raw: str) -> List[Dict[str, Any]]:
    tables = []
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.endswith("|") and "|" in line[1:-1]:
            block = []
            j = i
            while j < len(lines):
                cand = lines[j].strip()
                if cand.startswith("|") and cand.endswith("|"):
                    block.append(cand)
                    j += 1
                else:
                    break
            rows = [_split_row(b) for b in block]
            sep_rows = [r for r in rows
                        if r and all(re.match(r"^:?-{2,}:?$", c.strip()) for c in r if c.strip() != "")]
            rows = [r for r in rows if r not in sep_rows]
            if len(rows) >= 2:
                tables.append({"header": rows[0], "rows": rows[1:], "start_line": i})
            i = j
            continue
        i += 1
    return tables


def _split_row(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


# ---------------------------------------------------------------------------
# Archetype detection
# ---------------------------------------------------------------------------


def detect_archetype(doc: Dict[str, Any], hint: str = "auto") -> Dict[str, Any]:
    text = doc["raw"]
    scores: Dict[str, float] = {}
    evidence: Dict[str, List[str]] = {}

    for name, info in ARCHETYPE_INFO.items():
        score = 0.0
        ev: List[str] = []
        for sig in info["signals"]:
            if re.search(_term_pattern(sig), text, flags=re.IGNORECASE):
                score += 2.0
                ev.append(sig)
        for head in doc["headings"]:
            h = head["text"].lower()
            for sig in info["signals"]:
                if sig in h:
                    score += 3.0
                    ev.append("heading: " + head["text"][:48])
                    break
        scores[name] = score
        evidence[name] = ev[:6]

    if hint and hint in ARCHETYPE_INFO:
        scores[hint] += 100.0
        evidence.setdefault(hint, []).insert(0, "selected by the user")

    best = max(ARCHETYPE_ORDER, key=lambda k: (scores[k], -ARCHETYPE_ORDER.index(k)))
    total = sum(scores.values()) or 1.0
    confidence = scores[best] / total
    return {
        "key": best,
        "label": ARCHETYPE_INFO[best]["label"],
        "blurb": ARCHETYPE_INFO[best]["blurb"],
        "confidence": round(min(1.0, confidence * 1.6), 3),
        "scores": {k: round(v, 1) for k, v in scores.items()},
        "evidence": evidence.get(best, []),
        "detected": not (hint and hint in ARCHETYPE_INFO),
    }


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------


def detect_sections(doc: Dict[str, Any], archetype: str) -> Dict[str, Any]:
    required_map = dict(ARCHETYPE_INFO[archetype]["sections"])
    present: Dict[str, bool] = {}
    confidence: Dict[str, str] = {}
    evidence: Dict[str, str] = {}
    missing: List[str] = []

    for key in SECTION_SPECS:
        spec = SECTION_SPECS[key]
        found = False
        how = ""
        ev = ""
        for head in doc["headings"]:
            for pat in spec["headings"]:
                if re.search(pat, head["text"], flags=re.IGNORECASE):
                    found, how, ev = True, "heading", head["text"]
                    break
            if found:
                break
        if not found:
            for sec in doc["sections"]:
                for pat in spec["headings"]:
                    if re.search(pat, sec["title"], flags=re.IGNORECASE):
                        found, how, ev = True, "heading", sec["title"]
                        break
                if found:
                    break
        if not found:
            for pat in spec["body"]:
                m = re.search(pat, doc["raw"], flags=re.IGNORECASE)
                if m:
                    found, how = True, "inferred"
                    start = max(0, m.start() - 60)
                    ev = re.sub(r"\s+", " ", doc["raw"][start:m.end() + 60].replace("\n", " ")).strip()
                    break
        present[key] = found
        confidence[key] = how if found else "missing"
        if found:
            evidence[key] = ev[:200]
        elif required_map.get(key) == "required":
            missing.append(key)

    required_keys = [k for k, v in required_map.items() if v == "required"]
    covered = [k for k in required_keys if present.get(k)]
    coverage = len(covered) / len(required_keys) if required_keys else 1.0

    return {
        "present": present,
        "confidence": confidence,
        "evidence": evidence,
        "missing": missing,
        "required": required_keys,
        "optional": [k for k, v in required_map.items() if v == "optional"],
        "coverage": round(coverage, 3),
        "map": required_map,
    }


# ---------------------------------------------------------------------------
# Options analysis
# ---------------------------------------------------------------------------

OPTION_HEADING_PATTERNS = [
    r"^\s*(options?|alternatives?|approaches?|choices?|candidate options?|options? considered|we considered)\b",
    r"^\s*\d+[\.\)]\s*(options?|alternatives?|approaches?)\b",
]


def analyze_options(doc: Dict[str, Any], coverage: Dict[str, Any]) -> Dict[str, Any]:
    options: List[Dict[str, Any]] = []
    method = "none"
    table = None

    for sec in doc["sections"]:
        if any(re.search(p, sec["title"], flags=re.IGNORECASE) for p in OPTION_HEADING_PATTERNS):
            items: List[str] = []
            for line in sec["text"].split("\n"):
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^(?:[-*+]\s+|\d+[\.\)]\s+)(.+)$", line)
                if m:
                    items.append(m.group(1).strip())
                elif items:
                    items[-1] = items[-1] + " " + line
            if len(items) >= 2:
                options = [{"name": it, "detail": it, "source": "list"} for it in items]
                method = "list"
            break

    if not options:
        for cand in doc["tables"]:
            header, rows = cand["header"], cand["rows"]
            if len(header) >= 2 and len(rows) >= 2:
                names = [r[0] for r in rows if r and r[0]]
                if len(names) >= 2:
                    options = [{"name": r[0], "detail": " | ".join(r[1:]), "source": "table"}
                               for r in rows if r and r[0]]
                    table = cand
                    method = "table"
                    break

    if not options:
        inline = re.findall(
            r"^\s*((?:Option|Approach|Alternative)\s+[A-Z0-9][^\n.]{0,60})[:.]?\s*(.*)$",
            doc["raw"], flags=re.MULTILINE | re.IGNORECASE)
        if len(inline) >= 2:
            options = [{"name": n.strip(), "detail": (d or "").strip(), "source": "inline"}
                       for n, d in inline]
            method = "inline"

    criteria: List[str] = []
    criteria_consistent = True
    missing_cells: List[str] = []
    ragged_rows: List[str] = []

    if table is not None:
        criteria = table["header"][1:]
        width = len(table["header"])
        for row in table["rows"]:
            if len(row) != width:
                criteria_consistent = False
                ragged_rows.append(row[0] if row else "?")
            for idx, cell in enumerate(row[1:], start=1):
                if not cell.strip() and idx < len(criteria):
                    missing_cells.append(row[0] + " / " + criteria[idx])

    details = []
    for opt in options:
        details.append({
            "name": opt["name"],
            "words": len(_words(opt["detail"])),
            "numbers": len(re.findall(r"\d", opt["detail"])),
        })

    asymmetry = 0.0
    dominant = ""
    if len(details) >= 2:
        word_counts = sorted(d["words"] for d in details)
        median = statistics.median(word_counts)
        if median > 0:
            top = max(details, key=lambda d: d["words"])
            asymmetry = round(top["words"] / median, 2)
            if asymmetry >= 2.5:
                dominant = top["name"]

    loaded = []
    for opt in options:
        low = opt["name"].lower()
        for word in POSITIVE_OPTION_WORDS:
            if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", low):
                loaded.append({"option": opt["name"], "word": word})
                break

    recommendation_text = ""
    for sec in doc["sections"]:
        if re.search(r"^\s*(recommendation|recommended|proposal|proposed|our plan|plan of record)\b",
                     sec["title"], flags=re.IGNORECASE):
            recommendation_text = sec["text"]
            break
    if not recommendation_text:
        m = re.search(r"\b(recommend|i recommend|we recommend|i propose|we propose|the plan is|we should go with)\b",
                      doc["raw"], flags=re.IGNORECASE)
        if m:
            end = doc["raw"].find("\n", m.start())
            recommendation_text = doc["raw"][m.start(): (end if end != -1 else m.start() + 400)]

    traceable = None
    if options and recommendation_text:
        rec_words = set(w.lower() for w in _words(recommendation_text) if len(w) > 3)
        for opt in options:
            tokens = [w.lower() for w in _words(opt["name"]) if len(w) > 3]
            if tokens and any(tok in rec_words for tok in tokens):
                traceable = opt["name"]
                break
        if traceable is None:
            for opt in options:
                if opt["name"].lower() in recommendation_text.lower():
                    traceable = opt["name"]
                    break

    status_quo = None
    for opt in options:
        if re.search(r"status quo|do nothing|no change|current state|keep as is|continue as is|do not change",
                     opt["name"] + " " + opt["detail"], flags=re.IGNORECASE):
            status_quo = opt["name"]
            break

    return {
        "count": len(options),
        "options": options,
        "details": details,
        "method": method,
        "criteria": criteria,
        "criteria_consistent": criteria_consistent,
        "missing_cells": missing_cells,
        "ragged_rows": ragged_rows,
        "asymmetry": asymmetry,
        "dominant_option": dominant,
        "loaded_names": loaded,
        "recommendation_text": recommendation_text.strip(),
        "traceable_to": traceable,
        "status_quo_option": status_quo,
        "table": table,
    }


# ---------------------------------------------------------------------------
# Writing metrics
# ---------------------------------------------------------------------------


def compute_metrics(doc: Dict[str, Any]) -> Dict[str, Any]:
    text = doc["raw"]
    sentences = doc["sentences"]
    words = _words(text)
    n_words = len(words)
    n_sent = len(sentences)

    sent_lengths = [len(_words(s)) for s in sentences]
    avg_sent = statistics.mean(sent_lengths) if sent_lengths else 0.0
    long_sent = [s for s in sentences if len(_words(s)) > 30]
    very_long = [s for s in sentences if len(_words(s)) > 45]
    para_lengths = [len(_words(p)) for p in doc["paragraphs"]]

    passive_re = re.compile(
        r"\b(?:am|is|are|was|were|be|been|being|gets?|got|will be|would be|"
        r"has been|have been|had been)\s+(?:\w+ly\s+)?(?:\w+ed|\w+en|known|given|written|made|built|done|held|spent)\b",
        flags=re.IGNORECASE)
    passive_hits = passive_re.findall(text)
    passive_ratio = (len(passive_hits) / n_sent) if n_sent else 0.0

    hedge_hits = _terms_present(text, HEDGE_TERMS)
    hedge_count = _count_terms(text, hedge_hits)
    hedge_ratio = (hedge_count / n_sent) if n_sent else 0.0

    jargon_hits = _terms_present(text, JARGON_TERMS)
    jargon_count = _count_terms(text, jargon_hits)
    jargon_density = (jargon_count / max(n_words, 1)) * 100

    filler_hits = _terms_present(text, FILLER_TERMS)
    filler_count = _count_terms(text, filler_hits)
    filler_density = (filler_count / max(n_words, 1)) * 100

    vague_hits = _terms_present(text, VAGUE_QUANTIFIERS)
    vague_count = _count_terms(text, vague_hits)
    vague_density = (vague_count / max(n_words, 1)) * 100

    numbers = re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?\s*%?", text)
    currency = re.findall(r"\$\s?\d[\d,]*(?:[.,]\d+)?(?:\s?[kKmM])?", text)
    currency += re.findall(r"\b\d[\d,]*(?:\.\d+)?\s?(?:dollars?|usd|euros?|pounds?)\b",
                           text, flags=re.IGNORECASE)
    durations = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:engineer[- ]weeks?|weeks?|days?|months?|quarters?|years?|hours?|minutes?|people|engineers?|FTE|FTEs)\b",
        text, flags=re.IGNORECASE)

    date_iso = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    date_month = re.findall(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s*20\d{2})?\b", text)
    date_slash = re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text)
    date_quarter = re.findall(r"\bQ[1-4]\s*20\d{2}\b", text)
    dates = date_iso + date_month + date_slash + date_quarter

    owners = re.findall(r"\b(?:owner|dri|responsible|assignee|lead|reviewer)\s*[:\-]\s*([^\n.;|]{2,40})",
                        text, flags=re.IGNORECASE)

    placeholders = []
    for pat, label in PLACEHOLDER_PATTERNS:
        hits = re.findall(pat, text, flags=re.IGNORECASE)
        if hits:
            placeholders.append({"label": label, "count": len(hits)})

    acronyms = re.findall(r"\b[A-Z]{2,6}\b", text)
    defined = set(a.upper() for a in re.findall(r"\(([A-Z]{2,6})\)", text))
    heading_words = set()
    for h in doc["headings"]:
        heading_words.update(re.findall(r"\b[A-Z]{2,6}\b", h["text"]))
    common = {"OK", "AM", "PM", "ID", "IT", "QA", "US", "UK", "HR", "IO", "II"}
    unexpanded = sorted({a for a in acronyms
                         if a not in defined and a not in common and a not in heading_words})

    readability = 0.0
    if n_words and n_sent:
        syllables = 0
        for w in words:
            groups = len(re.findall(r"[aeiouy]+", w.lower()))
            if w.lower().endswith("e") and groups > 1:
                groups -= 1
            syllables += max(1, groups)
        readability = 206.835 - 1.015 * (n_words / n_sent) - 84.6 * (syllables / n_words)

    return {
        "word_count": n_words,
        "sentence_count": n_sent,
        "avg_sentence_words": round(avg_sent, 1),
        "long_sentences": long_sent,
        "very_long_sentences": very_long,
        "max_sentence_words": max(sent_lengths) if sent_lengths else 0,
        "avg_paragraph_words": round(statistics.mean(para_lengths), 1) if para_lengths else 0.0,
        "max_paragraph_words": max(para_lengths) if para_lengths else 0,
        "passive_count": len(passive_hits),
        "passive_ratio": round(passive_ratio, 4),
        "hedge_terms": hedge_hits,
        "hedge_count": hedge_count,
        "hedge_ratio": round(hedge_ratio, 4),
        "jargon_terms": jargon_hits,
        "jargon_count": jargon_count,
        "jargon_density": round(jargon_density, 3),
        "filler_terms": filler_hits,
        "filler_count": filler_count,
        "filler_density": round(filler_density, 3),
        "vague_terms": vague_hits,
        "vague_count": vague_count,
        "vague_density": round(vague_density, 3),
        "number_count": len(numbers),
        "currency_count": len(currency),
        "duration_count": len(durations),
        "dates": dates,
        "date_count": len(dates),
        "ambiguous_dates": date_slash,
        "owners": owners,
        "owner_count": len(owners),
        "placeholders": placeholders,
        "unexpanded_acronyms": unexpanded[:8],
        "readability": round(readability, 1),
        "heading_count": len(doc["headings"]),
        "bullet_count": len(doc["bullets"]),
        "numbered_count": len(doc["numbered"]),
        "table_count": len(doc["tables"]),
    }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _finding(fid: str, axis: str, severity: str, title: str, why: str,
             fix: str, evidence: str = "") -> Dict[str, Any]:
    return {
        "id": fid, "axis": axis, "severity": severity, "title": title,
        "why": why, "fix": fix, "evidence": (evidence or "").strip()[:280],
    }


def run_rules(doc: Dict[str, Any], archetype: str, coverage: Dict[str, Any],
              options: Dict[str, Any], metrics: Dict[str, Any],
              stakes: str, reversibility: str, audience: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    present = coverage["present"]
    present_map = coverage["confidence"]
    raw = doc["raw"]
    words = metrics["word_count"]
    decision_docs = ("memo", "rfc", "proposal", "one_pager")

    def add(*args, **kwargs):
        findings.append(_finding(*args, **kwargs))

    # --- structure -------------------------------------------------------
    if words < 40:
        add("doc_too_short", "structure", "high",
            "This is too short to be a decision document",
            "A decision memo needs enough room to state the situation, the options and the ask. "
            "Under forty words leaves the reader to reconstruct your thinking from scratch.",
            "Add the five blocks every memo needs: context, the decision, the options, "
            "your recommendation, and the ask.",
            "word count: %d" % words)
    elif words < 150:
        add("doc_very_short", "structure", "medium",
            "This document is thinner than a decision needs",
            "Fewer than 150 words rarely covers context, options and consequences. "
            "Readers will ask the same questions in the review thread.",
            "Expand the context and the options to roughly 300-500 words, "
            "and put the ask at the end.",
            "word count: %d" % words)

    if words > 2200 and metrics["heading_count"] < 4:
        add("wall_of_text", "structure", "high",
            "A long document with no headings",
            "Past a couple of thousand words with no structure, readers skim and miss the "
            "decision and the ask entirely.",
            "Add headings for context, options, recommendation, risks and next steps.",
            "%d words and only %d headings" % (words, metrics["heading_count"]))

    if metrics["heading_count"] == 0 and words > 120:
        add("no_headings", "structure", "medium",
            "No headings at all",
            "Headings are how a reader finds the decision in a document. Without them the memo "
            "reads like an email thread.",
            "Add five headings: Context, Decision, Options, Recommendation, Next steps.",
            "0 headings across %d words" % words)

    if metrics["max_paragraph_words"] > 160:
        add("run_on_paragraph", "structure", "medium",
            "A paragraph runs past 160 words",
            "Long unbroken paragraphs hide the argument. Readers give up and skim.",
            "Break the paragraph at each claim, or turn the list inside it into bullets.",
            "longest paragraph: %d words" % metrics["max_paragraph_words"])

    if metrics["bullet_count"] + metrics["numbered_count"] == 0 and words > 250:
        add("no_lists", "structure", "low",
            "No lists anywhere",
            "Options, risks and action items are scannable as lists and unreadable as prose.",
            "Turn the options, risks and next steps into bullet lists.",
            "%d words, 0 bullets" % words)

    if metrics["table_count"] == 0 and options["count"] >= 2:
        add("no_comparison_table", "structure", "medium",
            "Options are not compared on shared criteria",
            "Options described one after another in prose invite the reader to compare them on "
            "whatever criteria favour your choice.",
            "Add a table with one row per option and one column per criterion "
            "(cost, effort, risk, time).",
            "found %d options and no table" % options["count"])

    # --- decisiveness ----------------------------------------------------
    if archetype in decision_docs and not present.get("decision"):
        add("no_decision_stated", "decisiveness", "high",
            "The document never states what is being decided",
            "Without a decision statement the reader has to infer the question, and different "
            "people will answer different questions in the meeting.",
            "Add one line: 'Decision: should we X, or keep doing Y?'",
            "no decision heading or decision phrasing found")
    elif archetype in decision_docs and present_map.get("decision") == "inferred":
        add("decision_buried", "decisiveness", "medium",
            "The decision is implied rather than stated",
            "The decision is only inferable from the prose. In a review that costs a round trip.",
            "State the decision in its own line near the top.",
            coverage["evidence"].get("decision", ""))

    if archetype != "exploratory" and not present.get("recommendation"):
        add("no_recommendation", "decisiveness", "high",
            "There is no recommendation",
            "A document that lays out options but never says which one you want converts into a "
            "meeting instead of a decision.",
            "Add a 'Recommendation' line: which option, and in one sentence why.",
            "no recommendation heading or recommendation phrasing found")

    if archetype in decision_docs and not present.get("options"):
        add("no_options", "decisiveness", "high",
            "No alternatives are considered",
            "Presenting one path is not a decision, it is an announcement. Reviewers will ask "
            "what else you looked at.",
            "List at least two options plus doing nothing, and the criteria you compared them on.",
            "no options section found")
    elif archetype in decision_docs and options["count"] == 1:
        add("single_option", "decisiveness", "high",
            "Only one option is on the table",
            "With a single option the comparison is decorative, and the reader cannot tell "
            "whether you even looked at alternatives.",
            "Add the alternatives you rejected, with one line each on why they lost.",
            "options found: %d" % options["count"])
    elif archetype in decision_docs and options["count"] == 2 and stakes != "low":
        add("thin_options", "decisiveness", "low",
            "Only two options were considered",
            "Two options often means the real comparison was between your plan and the status quo.",
            "Add the cheapest credible alternative, or state why only these two were viable.",
            "options found: %d" % options["count"])

    if options["count"] >= 2 and options["traceable_to"] is None and present.get("recommendation"):
        add("recommendation_untraceable", "decisiveness", "medium",
            "The recommendation does not name one of the options",
            "Readers have to map your recommendation back to your own list, and may pick a "
            "different one.",
            "Repeat the option name verbatim in the recommendation line.",
            options["recommendation_text"][:160])

    if options["count"] >= 3 and options["asymmetry"] >= 2.5:
        add("strawman_options", "decisiveness", "high",
            "One option is described far more thoroughly than the rest",
            "Writing several times more about the option you prefer is the clearest way to make "
            "a comparison look like a decision without looking like one.",
            "Give every option the same treatment: same length, same criteria, same order.",
            "'%s' is %sx longer than the median option"
            % (options["dominant_option"], options["asymmetry"]))

    if options["loaded_names"]:
        add("loaded_option_names", "decisiveness", "low",
            "An option name carries a flattering adjective",
            "Names like 'scalable' or 'simple' smuggle the conclusion into the table of contents.",
            "Name options neutrally: Option A, Option B, or what they actually are.",
            "; ".join("%s (%s)" % (o["option"], o["word"]) for o in options["loaded_names"][:3]))

    if not options["criteria_consistent"]:
        add("inconsistent_criteria", "decisiveness", "high",
            "Rows in the options table do not use the same criteria",
            "When one option answers 'high cost, 8 weeks' and another answers only 'fast', the "
            "reader is being steered, not informed.",
            "Give every row a value for every column, or drop the columns you cannot fill "
            "honestly.",
            "ragged rows: " + ", ".join(options["ragged_rows"][:4]))

    if options["missing_cells"]:
        add("incomplete_criteria", "decisiveness", "medium",
            "Some criteria are blank for some options",
            "A blank cell reads as 'this option has no downside', which is rarely true.",
            "Fill the cell with a real value or write 'n/a - not applicable'.",
            "; ".join(options["missing_cells"][:4]))

    if options["count"] >= 2 and options["status_quo_option"] is None and reversibility == "one_way":
        add("no_status_quo_option", "decisiveness", "medium",
            "Doing nothing is not one of the options",
            "For a hard-to-reverse decision, the cost of doing nothing is the comparison readers "
            "will make in their head if you do not make it for them.",
            "Add 'Status quo: keep doing X, at a cost of Y' as an explicit option.",
            "options: " + ", ".join(o["name"][:30] for o in options["options"][:4]))

    if archetype in decision_docs and not present.get("tradeoffs") and present.get("recommendation"):
        add("no_tradeoffs", "decisiveness", "medium",
            "The recommendation has no stated downside",
            "A recommendation with no downside reads as advocacy, and reviewers discount the "
            "whole document.",
            "Add one line: 'The cost of this choice is ...'.",
            "no trade-offs or cost-of-the-choice language found")

    if re.search(r"\bon one hand\b", raw, flags=re.IGNORECASE) and not present.get("recommendation"):
        add("false_balance", "decisiveness", "medium",
            "The document weighs both sides without choosing",
            "Balanced framing with no recommendation reads as indecision, which stalls the decision.",
            "Pick a side, say why, and name what the other side would have to be right about.",
            "'on one hand ...' with no recommendation")

    dec_count = len(re.findall(r"\bdecision\s*:", raw, flags=re.IGNORECASE))
    if dec_count >= 4:
        add("decision_dumping", "decisiveness", "medium",
            "This document asks for several unrelated decisions",
            "Bundling decisions means the easy one gets approved with the hard one, or all of "
            "them get deferred.",
            "Split this into separate memos, or order them and ask only for the first.",
            "%d 'Decision:' lines found" % dec_count)

    # --- specificity -----------------------------------------------------
    if metrics["number_count"] == 0 and words > 120:
        add("no_numbers", "specificity", "high",
            "Not a single number in the document",
            "Without numbers nobody can tell whether the option is cheap, slow or risky. "
            "Every number is a claim someone can check.",
            "Add the numbers that matter: cost, duration, volume, headcount, latency, revenue.",
            "%d words with no numeric values" % words)
    elif metrics["number_count"] < 3 and words > 300:
        add("thin_numbers", "specificity", "medium",
            "Only %d numbers for %d words" % (metrics["number_count"], words),
            "One or two numbers scattered through a long memo give a false sense of rigour.",
            "Add numbers for each option: cost, effort, and the metric you expect to move.",
            "numeric values found: %d" % metrics["number_count"])

    if metrics["currency_count"] == 0 and stakes == "high" and words > 150:
        add("no_cost_figure", "specificity", "medium",
            "High-stakes decision with no cost figure",
            "Money is usually the thing that decides. Leaving it out pushes the argument to "
            "whoever asks first in the meeting.",
            "Add the cost of each option, even as a range.",
            "no currency amounts found")

    if metrics["duration_count"] == 0 and words > 150:
        add("no_duration_estimate", "specificity", "medium",
            "No time estimate",
            "Options without a duration cannot be compared and cannot be scheduled.",
            "Add an estimate for each option in weeks, months or quarters.",
            "no durations found")

    if metrics["vague_count"] >= 4:
        add("vague_quantifiers", "specificity", "medium",
            "Vague quantities replace real numbers",
            "'Several', 'significant' and 'roughly' hide the number you did not want to commit "
            "to, and reviewers read them as hand-waving.",
            "Replace each vague quantity with the number and its unit.",
            ", ".join(metrics["vague_terms"][:6]))

    if metrics["ambiguous_dates"]:
        add("ambiguous_dates", "specificity", "low",
            "A date could be read two ways",
            "Numeric dates like 03/04/2026 mean different things on different sides of the "
            "Atlantic.",
            "Use an unambiguous format such as 2026-04-03.",
            ", ".join(metrics["ambiguous_dates"][:3]))

    if not present.get("risks") and stakes in ("medium", "high"):
        add("no_risks", "specificity", "high" if stakes == "high" else "medium",
            "No risks section",
            "A decision memo without risks reads as naive, and reviewers will write the risk "
            "list for you in the thread.",
            "Add a short risks section: each risk, how likely, and the mitigation.",
            "no risks heading or risk language found")

    mitigation_verbs = re.search(r"\b(mitigat|avoid|reduce|limit|guard|monitor|prevent)\w*",
                                 raw, flags=re.IGNORECASE)
    if present.get("risks") and not mitigation_verbs:
        add("risks_without_mitigation", "specificity", "medium",
            "Risks are listed with no mitigation",
            "A risk without a mitigation is just anxiety on the page.",
            "Pair each risk with what you will do about it.",
            "risks section present, no mitigation verbs found")

    if reversibility == "one_way" and not present.get("reversibility"):
        add("no_reversibility", "specificity", "high",
            "A hard-to-reverse decision with no exit story",
            "If this decision cannot be undone, the cost of being wrong is permanent and belongs "
            "in the memo.",
            "Add a line on what happens if this is wrong, and what it costs to reverse it if it "
            "can be.",
            "reversibility set to one-way, no rollback language found")

    if present.get("unknowns") and metrics["owner_count"] == 0:
        add("unknowns_unowned", "specificity", "medium",
            "Open questions with nobody assigned to them",
            "An unowned unknown stays unknown. Open questions need a name and a date.",
            "Give every open question an owner and a due date.",
            "unknowns present, no owners named")

    if metrics["placeholders"]:
        labels = ", ".join("%s x%d" % (p["label"], p["count"]) for p in metrics["placeholders"])
        add("placeholder_text", "structure", "high",
            "Unfinished placeholder text is still in the document",
            "TBD and TODO in a document that is being reviewed say the work is not finished, and "
            "reviewers will not approve around them.",
            "Replace every placeholder with a real value or delete the line.",
            labels)

    # --- clarity ---------------------------------------------------------
    if metrics["sentence_count"] >= 5:
        long_share = len(metrics["long_sentences"]) / metrics["sentence_count"]
        if long_share > 0.4:
            add("long_sentences", "clarity", "medium",
                "Over 40% of sentences run past 30 words",
                "Long sentences hide the subject and the verb, and readers lose the thread.",
                "Split sentences at the first clause that could stand alone.",
                "longest sentence: %d words" % metrics["max_sentence_words"])
        if metrics["avg_sentence_words"] > 26:
            add("sentence_length", "clarity", "medium",
                "Average sentence length is %d words" % metrics["avg_sentence_words"],
                "Memo prose lands better at 15-20 words a sentence. Long averages are hard to "
                "read out loud, which is how the memo will be discussed.",
                "Break up the longest sentences until the average is under 22 words.",
                "average sentence length: %.1f words" % metrics["avg_sentence_words"])

    if metrics["passive_ratio"] > 0.18 and metrics["passive_count"] >= 3:
        add("passive_voice", "clarity", "medium",
            "Heavy passive voice hides who decides",
            "Passive constructions remove the actor, and in a decision document the actor is "
            "the point.",
            "Name the actor in the sentence: 'Finance will pay', not 'the cost will be borne'.",
            "%d passive constructions" % metrics["passive_count"])

    if metrics["hedge_ratio"] > 0.06 and metrics["hedge_count"] >= 4:
        add("hedging", "decisiveness", "high",
            "The document hedges every claim",
            "Hedging signals you are not sure, and a reader who is not sure will not approve "
            "anything.",
            "Keep the hedge where the uncertainty is real, and state the rest flatly.",
            ", ".join(metrics["hedge_terms"][:6]))

    if metrics["jargon_density"] > 0.8 and metrics["jargon_count"] >= 4:
        add("jargon", "clarity", "medium",
            "Business jargon is doing the work of an argument",
            "Terms like '%s' mean different things to different people and hide whether you have "
            "thought the problem through." % metrics["jargon_terms"][0],
            "Replace jargon with the plain word for what you actually mean.",
            ", ".join(metrics["jargon_terms"][:6]))

    if metrics["filler_density"] > 1.2 and metrics["filler_count"] >= 5:
        add("filler_words", "clarity", "low",
            "Filler words dilute the sentences",
            "'Basically', 'actually' and 'just' add nothing and make the memo sound like a "
            "meeting.",
            "Delete the fillers; they are never load-bearing.",
            ", ".join(metrics["filler_terms"][:6]))

    if audience == "exec" and metrics["jargon_count"] >= 6:
        add("audience_mismatch_exec", "clarity", "medium",
            "Too technical for an executive audience",
            "An exec reader wants the number, the cost and the risk, in that order.",
            "Lead with the metric and the ask, and move implementation detail to an appendix.",
            "%d jargon terms for an executive audience" % metrics["jargon_count"])
    elif audience == "technical" and metrics["number_count"] < 2 and words > 150:
        add("audience_mismatch_technical", "specificity", "medium",
            "Not concrete enough for a technical audience",
            "Technical reviewers judge specifics. Without them they will not sign off.",
            "Add the concrete artefacts: the table, the endpoint, the measured latency, the load.",
            "technical audience, %d numbers found" % metrics["number_count"])

    if metrics["unexpanded_acronyms"]:
        add("unexpanded_acronyms", "clarity", "low",
            "Acronyms used without being spelled out",
            "An acronym the reader does not know makes them feel behind, and stops them reading.",
            "Spell out the first use: 'continuous integration (CI)'.",
            ", ".join(metrics["unexpanded_acronyms"][:5]))

    # --- actionability ---------------------------------------------------
    if archetype in decision_docs and not present.get("ask"):
        add("no_ask", "actionability", "high",
            "The document never says what you want from the reader",
            "Without an explicit ask, the document generates discussion instead of a decision.",
            "Close with 'Ask: please approve X by <date>'.",
            "no ask or approval request found")
    elif archetype in decision_docs and present_map.get("ask") == "inferred":
        add("ask_soft", "actionability", "medium",
            "The ask is implied rather than explicit",
            "An implied ask gets treated as a discussion item.",
            "Add an explicit ask line with what, from whom, and by when.",
            coverage["evidence"].get("ask", ""))

    if not present.get("owners") and metrics["owner_count"] == 0:
        add("no_owners", "actionability", "high",
            "Nobody is named as an owner",
            "Decisions without a named owner decay into nothing. The owner is the person who "
            "moves when the plan slips.",
            "Name one accountable owner per action item.",
            "no owner or DRI named")

    if not present.get("timeline") and metrics["date_count"] == 0:
        add("no_timeline", "actionability", "high",
            "No dates anywhere in the document",
            "A decision without a date becomes a decision that nobody is waiting on.",
            "Add the decision date and the first two milestones.",
            "%d words with no dates" % words)
    elif metrics["date_count"] < 2 and words > 200:
        add("thin_timeline", "actionability", "medium",
            "Only %d date(s) in the document" % metrics["date_count"],
            "One date is rarely enough to schedule the work.",
            "Add the decision date, the start date, and the review date.",
            "dates found: %d" % metrics["date_count"])

    metric_signal = re.search(
        r"\b(metric|measure|success|goal|target|kpi|definition of done|we will know|baseline)\b",
        raw, flags=re.IGNORECASE)
    if not metric_signal and archetype not in ("postmortem", "status_update"):
        add("no_success_metric", "actionability", "medium",
            "Nothing says how you will know it worked",
            "Without a success measure, the decision can never be evaluated, and the work cannot "
            "be closed out.",
            "Add one measurable outcome and when you will check it.",
            "no metric, goal, target or baseline language found")

    next_steps_signal = re.search(
        r"\b(next steps?|action items?|upon approval|if approved|we will \w+ by|plan of record)\b",
        raw, flags=re.IGNORECASE)
    if present.get("recommendation") and not next_steps_signal:
        add("no_next_steps", "actionability", "medium",
            "No next steps after the recommendation",
            "A recommendation with no first action reads as an intention.",
            "Add 'Next steps: 1) ... 2) ...' with the first action owned and dated.",
            "recommendation present, no next-steps language found")

    vague_deadline = re.search(r"\b(soon|shortly|in the near term|asap|right away)\b",
                               raw, flags=re.IGNORECASE)
    if vague_deadline and metrics["date_count"] < 3:
        add("vague_deadlines", "actionability", "medium",
            "Deadlines are expressed as vague urgency",
            "'Soon' means different things to five people and it means nothing to a scheduler.",
            "Replace each vague deadline with a calendar date.",
            ", ".join(sorted(set(re.findall(
                r"\b(soon|shortly|in the near term|asap|right away)\b", raw, flags=re.IGNORECASE))))[:5])

    return findings


def compute_strengths(doc: Dict[str, Any], archetype: str, coverage: Dict[str, Any],
                      options: Dict[str, Any], metrics: Dict[str, Any]) -> List[str]:
    strengths: List[str] = []
    if coverage["present"].get("recommendation"):
        rec_idx = 0
        for sec in doc["sections"]:
            if re.search(r"recommend|propose|plan of record", sec["title"], flags=re.IGNORECASE):
                break
            rec_idx += 1
        if rec_idx <= 2:
            strengths.append("The recommendation appears early, before the reader has to dig for it.")
    if coverage["coverage"] >= 0.8:
        strengths.append("%d%% of the required sections for a %s are present."
                         % (round(coverage["coverage"] * 100),
                            ARCHETYPE_INFO[archetype]["label"].lower()))
    if options["count"] >= 3:
        strengths.append("%d options are on the table, so the choice is a real comparison."
                         % options["count"])
    if options["criteria"] and options["criteria_consistent"] and not options["missing_cells"]:
        strengths.append("Every option is scored on the same %d criteria: %s."
                         % (len(options["criteria"]),
                            ", ".join(c.lower() for c in options["criteria"][:5])))
    if metrics["owner_count"] >= 2:
        strengths.append("%d owners are named, so accountability is explicit."
                         % metrics["owner_count"])
    if metrics["date_count"] >= 3:
        strengths.append("%d concrete dates anchor the plan." % metrics["date_count"])
    if metrics["number_count"] >= 6:
        strengths.append("%d numbers make the claims checkable rather than rhetorical."
                         % metrics["number_count"])
    if metrics["passive_ratio"] < 0.08:
        strengths.append("The writing is mostly active voice, which keeps the actors visible.")
    if metrics["avg_sentence_words"] and metrics["avg_sentence_words"] <= 22:
        strengths.append("Sentences average %.0f words, which reads well."
                         % metrics["avg_sentence_words"])
    if options["status_quo_option"]:
        strengths.append("Doing nothing is included as an option, so the comparison is honest.")
    if options["traceable_to"]:
        strengths.append("The recommendation names one of the listed options ('%s')."
                         % options["traceable_to"])
    if metrics["readability"] >= 55:
        strengths.append("Readability score is %.0f, comfortable for a mixed audience."
                         % metrics["readability"])
    if not strengths:
        strengths.append("Every document is a starting point: name the decision, name the "
                         "options, name the ask.")
    return strengths


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def compute_weights(stakes: str, reversibility: str) -> Dict[str, float]:
    w = {"clarity": 0.22, "specificity": 0.18, "structure": 0.20,
         "decisiveness": 0.20, "actionability": 0.20}
    if stakes == "high":
        w["specificity"] += 0.04
        w["decisiveness"] += 0.06
        w["structure"] -= 0.04
        w["clarity"] -= 0.03
        w["actionability"] -= 0.03
    elif stakes == "low":
        w["clarity"] += 0.08
        w["specificity"] -= 0.04
        w["structure"] -= 0.02
        w["decisiveness"] -= 0.04
        w["actionability"] -= 0.02
    if reversibility == "one_way":
        w["decisiveness"] += 0.04
        w["actionability"] += 0.02
        w["clarity"] -= 0.03
        w["structure"] -= 0.03
    elif reversibility == "two_way":
        w["actionability"] += 0.06
        w["specificity"] -= 0.04
        w["decisiveness"] -= 0.02
    total = sum(w.values())
    return {k: round(v / total, 3) for k, v in w.items()}


def compute_axes(doc: Dict[str, Any], archetype: str, coverage: Dict[str, Any],
                 options: Dict[str, Any], metrics: Dict[str, Any],
                 findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    present = coverage["present"]
    components: Dict[str, List[Tuple[str, float, float]]] = {
        "clarity": [], "specificity": [], "structure": [],
        "decisiveness": [], "actionability": [],
    }

    avg = metrics["avg_sentence_words"]
    fit = clamp(100 - max(0.0, avg - 18.0) * 4.2) if avg else 0.0
    components["clarity"].append(("sentence fit", fit, 0.35))
    components["clarity"].append(("active voice", clamp(100 - metrics["passive_ratio"] * 260), 0.20))
    components["clarity"].append(("confidence", clamp(100 - metrics["hedge_ratio"] * 1400), 0.20))
    components["clarity"].append(("plain language", clamp(100 - metrics["jargon_density"] * 22), 0.15))
    components["clarity"].append(("no filler", clamp(100 - metrics["filler_density"] * 12), 0.10))

    quantified = 100.0 if metrics["number_count"] >= 5 else (
        100.0 * metrics["number_count"] / 5.0 if metrics["number_count"] else 0.0)
    components["specificity"].append(("quantified", quantified, 0.30))
    components["specificity"].append(("dated", clamp(metrics["date_count"] * 34.0), 0.20))
    components["specificity"].append(("owned", clamp(metrics["owner_count"] * 50.0), 0.20))
    criteria_score = 100.0 if (options["criteria"] and options["criteria_consistent"]) else (
        55.0 if options["criteria"] else (40.0 if options["count"] >= 2 else 10.0))
    components["specificity"].append(("shared criteria", criteria_score, 0.15))
    components["specificity"].append(("no vague quantities",
                                      clamp(100 - metrics["vague_density"] * 26), 0.15))

    components["structure"].append(("section coverage", coverage["coverage"] * 100, 0.30))
    components["structure"].append(("headings", clamp(metrics["heading_count"] * 16.0, 0, 100), 0.20))
    if metrics["max_paragraph_words"]:
        block = clamp(100 - max(0, metrics["max_paragraph_words"] - 90) * 0.55)
    else:
        block = 40.0
    components["structure"].append(("block shape", block, 0.20))
    device = 100.0 if metrics["table_count"] else (70.0 if options["method"] == "list" else 25.0)
    components["structure"].append(("comparison device", device, 0.15))
    wc = metrics["word_count"]
    if 250 <= wc <= 1500:
        length_fit = 100.0
    elif 150 <= wc < 250:
        length_fit = 65.0
    elif wc < 150:
        length_fit = 35.0
    else:
        length_fit = 70.0
    components["structure"].append(("length fit", length_fit, 0.15))

    if archetype == "postmortem":
        components["decisiveness"].append(
            ("cause identified", 100.0 if present.get("context") else 0.0, 0.25))
        components["decisiveness"].append(
            ("actions proposed", 100.0 if present.get("recommendation") else 0.0, 0.25))
        components["decisiveness"].append(
            ("contributing factors", 100.0 if present.get("risks") else 20.0, 0.20))
        components["decisiveness"].append(
            ("actions owned", clamp(metrics["owner_count"] * 50.0), 0.15))
        components["decisiveness"].append(
            ("lessons stated",
             100.0 if re.search(r"\blessons?\b", doc["raw"], flags=re.IGNORECASE) else 15.0, 0.15))
    elif archetype == "status_update":
        components["decisiveness"].append(
            ("status stated", 100.0 if present.get("context") else 0.0, 0.25))
        components["decisiveness"].append(
            ("next steps stated", 100.0 if present.get("recommendation") else 0.0, 0.25))
        components["decisiveness"].append(
            ("blockers named",
             100.0 if re.search(r"\bblocked?\b", doc["raw"], flags=re.IGNORECASE) else 20.0, 0.20))
        components["decisiveness"].append(
            ("owners named", clamp(metrics["owner_count"] * 50.0), 0.15))
        components["decisiveness"].append(
            ("impact stated", 100.0 if present.get("impact") else 15.0, 0.15))
    elif archetype == "exploratory":
        components["decisiveness"].append(
            ("question framed", 100.0 if present.get("context") else 0.0, 0.25))
        components["decisiveness"].append(
            ("next experiment", 100.0 if present.get("timeline") else 0.0, 0.25))
        components["decisiveness"].append(
            ("options listed", 100.0 if options["count"] >= 2 else 20.0, 0.20))
        components["decisiveness"].append(
            ("experiment owned", clamp(metrics["owner_count"] * 50.0), 0.15))
        components["decisiveness"].append(
            ("unknowns named", 100.0 if present.get("unknowns") else 10.0, 0.15))
    else:
        components["decisiveness"].append(("decision stated",
                                           100.0 if present.get("decision") else 0.0, 0.25))
        components["decisiveness"].append(("recommendation",
                                           100.0 if present.get("recommendation") else 0.0, 0.25))
        if options["count"] >= 2 and options["criteria_consistent"]:
            compared = 100.0
        elif options["count"] >= 2:
            compared = 55.0
        else:
            compared = 10.0
        components["decisiveness"].append(("options compared", compared, 0.20))
        trace = 100.0 if options["traceable_to"] else (55.0 if not options["count"] else 30.0)
        components["decisiveness"].append(("recommendation traceable", trace, 0.15))
        components["decisiveness"].append(("trade-offs explicit",
                                           100.0 if present.get("tradeoffs") else 15.0, 0.15))

    components["actionability"].append(("explicit ask",
                                        100.0 if present.get("ask") else 0.0, 0.25))
    steps = 100.0 if re.search(
        r"\b(next steps?|action items?|upon approval|if approved|we will \w+ by)\b",
        doc["raw"], flags=re.IGNORECASE) else 15.0
    components["actionability"].append(("next steps", steps, 0.25))
    components["actionability"].append(("owners named", clamp(metrics["owner_count"] * 50.0), 0.20))
    components["actionability"].append(("timeline", clamp(metrics["date_count"] * 34.0), 0.15))
    metric_signal = 100.0 if re.search(
        r"\b(metric|success|goal|target|kpi|baseline|definition of done)\b",
        doc["raw"], flags=re.IGNORECASE) else 10.0
    components["actionability"].append(("success measure", metric_signal, 0.15))

    axes: Dict[str, Any] = {}
    for axis, items in components.items():
        total_w = sum(w for _, _, w in items)
        base = sum(score * w for _, score, w in items) / total_w if total_w else 0.0
        penalty = 0.0
        for f in findings:
            if f["axis"] == axis:
                penalty += SEVERITY_PENALTY.get(f["severity"], 2.0)
        penalty = min(penalty, 38.0)
        value = clamp(base - penalty)
        axes[axis] = {
            "score": round(value, 1),
            "base": round(base, 1),
            "penalty": round(penalty, 1),
            "components": [{"name": n, "score": round(s, 1), "weight": w} for n, s, w in items],
        }
    return axes


def apply_caps(axes: Dict[str, Any], findings: List[Dict[str, Any]], archetype: str,
               coverage: Dict[str, Any], metrics: Dict[str, Any],
               stakes: str, reversibility: str) -> List[Dict[str, Any]]:
    caps: List[Dict[str, Any]] = []
    ids = {f["id"] for f in findings}
    present = coverage["present"]

    def cap(axis: str, ceiling: float, reason: str):
        current = axes[axis]["score"]
        if current > ceiling:
            axes[axis]["score"] = round(ceiling, 1)
            axes[axis]["capped_from"] = current
            caps.append({"axis": axis, "ceiling": ceiling, "reason": reason})

    if "doc_too_short" in ids:
        cap("structure", 40.0, "Document is too short to contain a decision.")
    if "no_decision_stated" in ids:
        cap("decisiveness", 35.0, "Nothing states what is being decided.")
    if "no_recommendation" in ids:
        cap("decisiveness", 40.0, "No recommendation is made.")
    if "no_options" in ids:
        cap("decisiveness", 45.0, "No alternatives are considered.")
    if "single_option" in ids:
        cap("decisiveness", 55.0, "Only one option is presented.")
    if "no_ask" in ids:
        cap("actionability", 50.0, "The reader is never asked for anything.")
    if "no_owners" in ids:
        cap("actionability", 55.0, "No accountable owner is named.")
    if "no_timeline" in ids:
        cap("actionability", 55.0, "No dates anchor the plan.")
    if "no_numbers" in ids:
        cap("specificity", 45.0, "No numbers make the claims checkable.")
    if stakes == "high" and "no_risks" in ids:
        cap("specificity", 55.0, "A high-stakes decision with no risks section.")
    if reversibility == "one_way" and "no_reversibility" in ids:
        cap("structure", 60.0, "An irreversible decision with no exit story.")
    if "strawman_options" in ids:
        cap("decisiveness", 55.0, "The options comparison is not balanced.")
    if "placeholder_text" in ids:
        cap("structure", 50.0, "Unfinished placeholder text remains.")
    if archetype in ("memo", "rfc", "proposal", "one_pager") and not present.get("recommendation"):
        cap("decisiveness", 40.0, "A decision document needs a recommendation.")

    high = [f for f in findings if f["severity"] == "high"]
    if len(high) >= 6:
        cap("structure", 45.0, "%d high-severity findings." % len(high))
    elif len(high) >= 4:
        cap("structure", 60.0, "%d high-severity findings." % len(high))
    return caps


VERDICTS = [
    (85.0, "decision_ready", "Ready to send. A reader can decide from this page alone."),
    (72.0, "mostly_ready", "Almost ready. A couple of gaps will come back as review comments."),
    (58.0, "needs_revision", "Not ready. Fix the high-severity findings before circulating."),
    (42.0, "tight_but_usable", "Weak. The bones are there but the argument is thin."),
    (0.0, "not_a_decision_doc", "This does not yet read as a decision document."),
]


def verdict_for(score: float) -> Dict[str, Any]:
    for threshold, key, blurb in VERDICTS:
        if score >= threshold:
            return {"key": key, "label": key.replace("_", " "), "blurb": blurb,
                    "threshold": threshold}
    return {"key": "not_a_decision_doc", "label": "not a decision doc",
            "blurb": VERDICTS[-1][2], "threshold": 0.0}


# ---------------------------------------------------------------------------
# Fix plan and rewrite scaffold
# ---------------------------------------------------------------------------


def build_fix_plan(findings: List[Dict[str, Any]], axes: Dict[str, Any],
                   weights: Dict[str, float], caps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cap_axes = {c["axis"] for c in caps}
    plan = []
    for f in findings:
        weight = weights.get(f["axis"], 0.2)
        sev = SEVERITY_PENALTY.get(f["severity"], 3.0)
        priority = sev * weight * 100
        if f["axis"] in cap_axes:
            priority *= 1.6
        if f["severity"] == "high":
            priority *= 1.25
        plan.append({
            "id": f["id"],
            "axis": f["axis"],
            "severity": f["severity"],
            "title": f["title"],
            "fix": f["fix"],
            "priority": round(priority, 1),
        })
    plan.sort(key=lambda p: (-p["priority"], SEVERITY_ORDER.get(p["severity"], 3)))
    for idx, item in enumerate(plan, start=1):
        item["rank"] = idx
        item["estimated_gain"] = round(min(9.0, item["priority"] * 0.35), 1)
    return plan


def build_scaffold(archetype: str, coverage: Dict[str, Any],
                   options: Dict[str, Any]) -> Dict[str, Any]:
    present = coverage["present"]
    req = coverage["map"]
    outline = []
    for key, requirement in req.items():
        spec = SECTION_SPECS[key]
        outline.append({
            "key": key,
            "label": spec["label"],
            "requirement": requirement,
            "present": bool(present.get(key)),
            "guidance": spec["guidance"],
        })
    missing = [o for o in outline if o["requirement"] == "required" and not o["present"]]
    return {
        "outline": outline,
        "missing_required": [o["label"] for o in missing],
        "prompt": "Rewrite this as a %s with these headings: %s. Keep the strongest version of "
                  "each existing section, and fill the missing ones in this order: %s." % (
                      ARCHETYPE_INFO[archetype]["label"].lower(),
                      ", ".join(o["label"] for o in outline),
                      ", ".join(o["label"] for o in missing) if missing else "none, all present"),
    }


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


def analyze(text: str, doc_type: str = "auto", stakes: str = "medium",
            reversibility: str = "unknown", audience: str = "mixed") -> Dict[str, Any]:
    doc = parse_document(text)
    archetype_info = detect_archetype(doc, doc_type)
    archetype = archetype_info["key"]
    coverage = detect_sections(doc, archetype)
    options = analyze_options(doc, coverage)
    metrics = compute_metrics(doc)
    findings = run_rules(doc, archetype, coverage, options, metrics,
                         stakes, reversibility, audience)
    weights = compute_weights(stakes, reversibility)
    axes = compute_axes(doc, archetype, coverage, options, metrics, findings)
    caps = apply_caps(axes, findings, archetype, coverage, metrics, stakes, reversibility)
    overall = round(sum(axes[a]["score"] * weights[a] for a in axes), 1)
    verdict = verdict_for(overall)
    strengths = compute_strengths(doc, archetype, coverage, options, metrics)
    fix_plan = build_fix_plan(findings, axes, weights, caps)
    scaffold = build_scaffold(archetype, coverage, options)

    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f["severity"]] += 1

    return {
        "meta": {
            "doc_type": archetype,
            "doc_type_label": archetype_info["label"],
            "doc_type_detected": archetype_info["detected"],
            "doc_type_confidence": archetype_info["confidence"],
            "doc_type_evidence": archetype_info["evidence"],
            "stakes": stakes,
            "reversibility": reversibility,
            "audience": audience,
            "weights": weights,
        },
        "score": overall,
        "verdict": verdict,
        "axes": axes,
        "caps": caps,
        "coverage": coverage,
        "options": options,
        "metrics": metrics,
        "findings": findings,
        "finding_counts": counts,
        "strengths": strengths,
        "fix_plan": fix_plan,
        "scaffold": scaffold,
        "input_words": doc["word_count"],
    }


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

BACKTICK = chr(96)


def to_markdown(report: Dict[str, Any]) -> str:
    m = report["meta"]
    v = report["verdict"]
    out = []
    out.append("# Decision Memo Review")
    out.append("")
    out.append("**Score: %.1f / 100 - %s**" % (report["score"], v["label"].upper()))
    out.append("")
    out.append(v["blurb"])
    out.append("")
    out.append("- Document type: %s (%s)" % (m["doc_type_label"],
               "detected" if m["doc_type_detected"] else "selected"))
    out.append("- Stakes: %s | Reversibility: %s | Audience: %s"
               % (m["stakes"], m["reversibility"], m["audience"]))
    out.append("- Words: %d | Sentences: %d | Findings: %d high, %d medium, %d low"
               % (report["input_words"], report["metrics"]["sentence_count"],
                  report["finding_counts"]["high"], report["finding_counts"]["medium"],
                  report["finding_counts"]["low"]))
    out.append("")
    out.append("## Scorecard")
    out.append("")
    out.append("| Axis | Score | Weight | Components |")
    out.append("| --- | --- | --- | --- |")
    for axis, data in report["axes"].items():
        comps = ", ".join("%s %d" % (c["name"], c["score"]) for c in data["components"])
        out.append("| %s | %.1f | %.2f | %s |"
                   % (axis.capitalize(), data["score"], m["weights"][axis], comps))
    out.append("")
    if report["caps"]:
        out.append("### Score caps applied")
        out.append("")
        for c in report["caps"]:
            out.append("- %s capped at %.0f - %s"
                       % (c["axis"].capitalize(), c["ceiling"], c["reason"]))
        out.append("")
    out.append("## Strengths")
    out.append("")
    for s in report["strengths"]:
        out.append("- %s" % s)
    out.append("")
    out.append("## Findings")
    out.append("")
    if not report["findings"]:
        out.append("No findings. This document is in good shape.")
    else:
        for f in report["findings"]:
            out.append("### [%s] %s" % (f["severity"].upper(), f["title"]))
            out.append("")
            out.append("- Axis: %s" % f["axis"])
            if f["evidence"]:
                out.append("- Evidence: %s" % f["evidence"].replace(BACKTICK, "'"))
            out.append("- Why it matters: %s" % f["why"])
            out.append("- Fix: %s" % f["fix"])
            out.append("")
    out.append("## Options analysis")
    out.append("")
    opts = report["options"]
    if opts["count"]:
        out.append("Options found: %d (source: %s)" % (opts["count"], opts["method"]))
        out.append("")
        if opts["criteria"]:
            out.append("| Option | %s |" % " | ".join(opts["criteria"]))
            out.append("| --- | %s |" % " | ".join("---" for _ in opts["criteria"]))
            for row in opts["options"]:
                cells = row["detail"].split(" | ") if row["source"] == "table" else [row["detail"]]
                padded = (cells + [""] * len(opts["criteria"]))[:len(opts["criteria"])]
                out.append("| %s | %s |" % (row["name"], " | ".join(padded)))
            out.append("")
        else:
            for o in opts["options"]:
                out.append("- **%s** - %s" % (o["name"], o["detail"][:180]))
            out.append("")
        out.append("- Status quo option: %s" % (opts["status_quo_option"] or "not present"))
        out.append("- Description balance: %sx spread between the longest and median option"
                   % opts["asymmetry"])
        out.append("- Recommendation traces to: %s" % (opts["traceable_to"] or "no named option"))
    else:
        out.append("No options were found in the document.")
    out.append("")
    out.append("## Section coverage")
    out.append("")
    for item in report["scaffold"]["outline"]:
        out.append("- %s (%s, %s)" % (item["label"], item["requirement"],
                    "present" if item["present"] else "MISSING"))
    out.append("")
    out.append("## Prioritised fix plan")
    out.append("")
    for item in report["fix_plan"][:12]:
        out.append("%d. **[%s] %s** - %s"
                   % (item["rank"], item["severity"], item["title"], item["fix"]))
    out.append("")
    out.append("## Rewrite scaffold")
    out.append("")
    out.append(report["scaffold"]["prompt"])
    out.append("")
    return "\n".join(out)



