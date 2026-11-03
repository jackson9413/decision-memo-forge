# Decision Memo Forge

A local-first reviewer for decision documents: memos, RFCs, business proposals, one-pagers,
status updates and postmortems.

Paste the document you are about to send. Get back a decision-readiness score, the specific
gaps that will turn your memo into a meeting, and a rewrite scaffold that tells you what to
add and in what order.

Everything runs on your machine. No API keys, no network calls, no uploads, no telemetry.

---

## Why it matters

Most "decision documents" fail in the same five ways, and every one of them is invisible
until a reviewer asks about it in a meeting:

1. **No decision is stated.** The document describes a situation and leaves the reader to
   work out what is being decided. Different people answer different questions.
2. **No options are compared.** One path is presented, which is an announcement, not a decision.
3. **The comparison is rigged.** The preferred option gets a paragraph and every alternative
   gets five words. Nobody notices except the person who wrote it.
4. **No trade-offs, no risks, no reversal story.** A recommendation with no downside reads as
   advocacy, and reviewers discount the whole document.
5. **No ask, no owner, no date.** The document generates discussion instead of a decision.

Decision Memo Forge finds those five, plus about forty more, and tells you how to fix each
one. It also knows what *not* to complain about: a postmortem is not supposed to compare
options, and an exploratory note is not supposed to have a recommendation.

## What you get

```text
Score header      overall 0-100 and a verdict band
                  decision_ready / mostly_ready / needs_revision /
                  tight_but_usable / not_a_decision_doc
Axis pills        clarity, specificity, structure, decisiveness, actionability
                  each 0-100 with its components and its weight for this document
Findings          every finding carries the evidence that triggered it, why it
                  matters, and a concrete fix
Section coverage  which required sections are present, which are missing, and
                  whether each was found by heading or only inferred from prose
Options panel     the options table with a criteria-consistency check, a
                  description-balance check, and whether the recommendation
                  actually names one of them
Fix plan          findings ranked by severity and axis weight, with an estimated
                  score gain per fix
Rewrite scaffold  the outline your document should have had, and the order to
                  fill the gaps in
```

Reviews are stored in a local SQLite log with a 1-5 star self-rating and notes, and can be
exported as Markdown or JSON.

## The five axes

| Axis | What it measures |
| --- | --- |
| Clarity | Sentence length, passive voice, hedging, jargon, filler words, readability |
| Specificity | Numbers, dates, named owners, shared criteria, vague quantities |
| Structure | Section coverage, headings, block shape, a comparison device, length fit |
| Decisiveness | Decision stated, recommendation made, options compared, trade-offs explicit |
| Actionability | An explicit ask, next steps, owners, a timeline, a success measure |

Weights shift with the document: a high-stakes irreversible decision moves weight onto
decisiveness and specificity; a low-stakes reversible one moves it onto clarity. The
decisiveness axis itself changes meaning by archetype, because a postmortem is judged on
cause, actions and lessons while a memo is judged on decision, options and recommendation.

### Structural caps

A score you can game is not a score. The engine applies hard ceilings so a document cannot
look strong by skipping the hard part:

- no decision stated -> decisiveness capped at 35
- no recommendation -> decisiveness capped at 40
- no alternatives -> decisiveness capped at 45
- only one option -> decisiveness capped at 55
- no ask -> actionability capped at 50
- no owner -> actionability capped at 55
- no dates -> actionability capped at 55
- not a single number -> specificity capped at 45
- high stakes with no risks section -> specificity capped at 55
- irreversible decision with no rollback story -> structure capped at 60
- unbalanced option descriptions -> decisiveness capped at 55
- four or more high-severity findings -> structure capped at 60 (six or more -> 45)

Every cap that fires is listed in the report with the reason.

## Document archetypes

The tool detects what kind of document it is looking at, and each archetype has its own
required sections:

| Archetype | Required sections |
| --- | --- |
| Decision memo | context, decision, options, recommendation, risks, owners, ask |
| RFC / design doc | context, decision, options, recommendation, trade-offs, risks, reversibility, unknowns, impact, owners, timeline, ask |
| Business proposal | context, decision, options, recommendation, risks, impact, owners, timeline, ask |
| One-pager | context, decision, recommendation, impact, ask |
| Postmortem | context, recommendation, unknowns, impact, owners, timeline |
| Status update | context, recommendation, impact, owners, timeline |
| Exploratory note | context, options, unknowns, owners, timeline |

Detection uses headings, section vocabulary and document signals. You can override it.

## Run it

```bash
cd decision-memo-forge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Then open `http://127.0.0.1:8017`.

Set a different port with `PORT=8080 python3 app.py`.

## Run the tests

```bash
python3 -m unittest discover -s tests -v
```

55 tests cover parsing, archetype detection, section coverage, option extraction, every
structural cap, the scoring maths, the Markdown export, the six built-in samples and the
whole HTTP surface.

## HTTP API

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` | the single-page UI |
| GET | `/api/health` | liveness check |
| GET | `/api/options` | archetypes, stakes, reversibility, audiences |
| GET | `/api/samples` | the six built-in sample documents |
| GET | `/api/sample/<id>` | one sample document |
| POST | `/api/analyze` | analyse a document (add `"save": true` to store it) |
| GET | `/api/sessions` | the review log |
| GET | `/api/sessions/<id>` | one saved review with its full report |
| PATCH | `/api/sessions/<id>` | set `self_rating` (1-5) and `notes` |
| GET | `/api/export/<id>?fmt=md|json` | download the review |

Example:

```bash
curl -s localhost:8017/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"Decision\n\nWe need to decide whether to migrate.\n", "stakes":"high"}'
```

## Layout

```text
decision-memo-forge/
  app.py                  Flask routes and the SQLite session log
  engine.py               the analysis engine (standard library only)
  samples.py              six built-in sample documents
  templates/index.html    single-page UI
  static/styles.css       dark theme
  static/app.js           vanilla JS client, no build step
  tests/test_engine.py    engine tests
  tests/test_api.py       HTTP tests
  data/                   SQLite log (created on first run, gitignored)
```

## Tech stack

Python 3 standard library for the analysis engine (no pandas, no numpy, no LLM calls),
Flask for the HTTP layer, SQLite for the review log, and vanilla HTML/CSS/JS for the UI.
One dependency, listed in `requirements.txt`.

## Privacy

The document you paste never leaves the machine. There is no outbound request in the
application, no API key to configure, and no analytics. The only thing written to disk is
your review log in `data/dmf.db`.
