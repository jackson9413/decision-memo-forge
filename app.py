"""Decision Memo Forge - Flask application.

Local-first decision document reviewer. Everything runs on this machine:
no API keys, no network calls, no telemetry. The only persistence is a
small SQLite log of reviewed documents with a self-rating and notes.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request, Response

import engine
import samples

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "dmf.db")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

DOC_TYPES = ["auto"] + engine.ARCHETYPE_ORDER
STAKES = ["low", "medium", "high"]
REVERSIBILITY = ["two_way", "one_way", "unknown"]
AUDIENCES = ["exec", "technical", "peer", "mixed"]


def db() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               created_at TEXT NOT NULL,
               title TEXT,
               doc_type TEXT,
               stakes TEXT,
               reversibility TEXT,
               audience TEXT,
               score REAL,
               verdict TEXT,
               finding_counts TEXT,
               payload TEXT NOT NULL,
               self_rating INTEGER,
               notes TEXT
           )"""
    )
    conn.commit()
    conn.close()


init_db()


def row_to_session(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        counts = json.loads(row["finding_counts"] or "{}")
    except (ValueError, TypeError):
        counts = {}
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "title": row["title"],
        "doc_type": row["doc_type"],
        "stakes": row["stakes"],
        "reversibility": row["reversibility"],
        "audience": row["audience"],
        "score": row["score"],
        "verdict": row["verdict"],
        "finding_counts": counts,
        "self_rating": row["self_rating"],
        "notes": row["notes"],
    }


def save_session(report: Dict[str, Any], source: str) -> int:
    meta = report["meta"]
    conn = db()
    cur = conn.execute(
        """INSERT INTO sessions
               (created_at, title, doc_type, stakes, reversibility, audience,
                score, verdict, finding_counts, payload, self_rating, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source,
            meta["doc_type_label"],
            meta["stakes"],
            meta["reversibility"],
            meta["audience"],
            report["score"],
            report["verdict"]["key"],
            json.dumps(report["finding_counts"]),
            json.dumps(report),
            None,
            None,
        ),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


@app.route("/")
def index():
    return render_template("index.html", doc_types=DOC_TYPES, stakes=STAKES,
                            reversibility=REVERSIBILITY, audiences=AUDIENCES)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "decision-memo-forge",
                    "archetypes": engine.ARCHETYPE_ORDER})


@app.route("/api/options")
def options():
    return jsonify({
        "doc_types": [{"key": k, "label": engine.ARCHETYPE_INFO[k]["label"],
                       "blurb": engine.ARCHETYPE_INFO[k]["blurb"],
                       "sections": engine.ARCHETYPE_INFO[k]["sections"]}
                      for k in engine.ARCHETYPE_ORDER],
        "stakes": STAKES,
        "reversibility": REVERSIBILITY,
        "audiences": AUDIENCES,
    })


@app.route("/api/samples")
def api_samples():
    return jsonify({"samples": samples.list_samples()})


@app.route("/api/sample/<sample_id>")
def api_sample(sample_id: str):
    sample = samples.get_sample(sample_id)
    if not sample:
        return jsonify({"error": "unknown sample", "id": sample_id}), 404
    return jsonify(sample)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json(silent=True) or {}
    text = data.get("text") or ""
    if not isinstance(text, str):
        return jsonify({"error": "text must be a string"}), 400
    if not text.strip():
        return jsonify({"error": "text is empty"}), 400

    doc_type = data.get("doc_type") or "auto"
    if doc_type not in DOC_TYPES:
        doc_type = "auto"
    stakes = data.get("stakes") if data.get("stakes") in STAKES else "medium"
    reversibility = (data.get("reversibility")
                     if data.get("reversibility") in REVERSIBILITY else "unknown")
    audience = data.get("audience") if data.get("audience") in AUDIENCES else "mixed"

    report = engine.analyze(text, doc_type=doc_type, stakes=stakes,
                             reversibility=reversibility, audience=audience)

    session_id = None
    if data.get("save"):
        title = (data.get("title") or "").strip() or report["meta"]["doc_type_label"]
        session_id = save_session(report, title[:120])

    report["session_id"] = session_id
    report["markdown"] = engine.to_markdown(report)
    return jsonify(report)


@app.route("/api/sessions")
def api_sessions():
    limit = request.args.get("limit", default=30, type=int)
    limit = max(1, min(limit, 200))
    conn = db()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return jsonify({"sessions": [row_to_session(r) for r in rows]})


@app.route("/api/sessions/<int:sid>")
def api_session(sid: int):
    conn = db()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "session not found", "id": sid}), 404
    out = row_to_session(row)
    out["report"] = json.loads(row["payload"])
    return jsonify(out)


@app.route("/api/sessions/<int:sid>", methods=["PATCH"])
def api_patch_session(sid: int):
    data = request.get_json(silent=True) or {}
    conn = db()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "session not found", "id": sid}), 404

    rating = data.get("self_rating", row["self_rating"])
    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            rating = None
        if rating is not None and not (1 <= rating <= 5):
            rating = None
    notes = data.get("notes", row["notes"])
    if notes is not None and not isinstance(notes, str):
        notes = None

    conn.execute(
        "UPDATE sessions SET self_rating = ?, notes = ? WHERE id = ?",
        (rating, notes, sid),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    return jsonify(row_to_session(updated))


@app.route("/api/export/<int:sid>")
def api_export(sid: int):
    fmt = (request.args.get("fmt") or "md").lower()
    conn = db()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "session not found", "id": sid}), 404

    if fmt == "json":
        payload = json.dumps(json.loads(row["payload"]), indent=2)
        return Response(payload, mimetype="application/json", headers={
            "Content-Disposition": "attachment; filename=decision-memo-review-%d.json" % sid})

    report = json.loads(row["payload"])
    payload = engine.to_markdown(report)
    return Response(payload, mimetype="text/markdown", headers={
        "Content-Disposition": "attachment; filename=decision-memo-review-%d.md" % sid})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8017"))
    print("Decision Memo Forge running on http://127.0.0.1:%d" % port)
    app.run(host="127.0.0.1", port=port, debug=False)
