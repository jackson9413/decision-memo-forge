/* Decision Memo Forge - client. Vanilla JS, no build step, no dependencies. */

var state = { report: null, sessionId: null, severity: "all", axis: "all" };

function $(id) { return document.getElementById(id); }

function escapeHtml(value) {
  if (value === null || value === undefined) { return ""; }
  return String(value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function setStatus(text, kind) {
  var pill = $("status-pill");
  pill.textContent = text;
  pill.className = "pill " + (kind ? "pill-" + kind : "pill-ghost");
}

function colorFor(score) {
  if (score >= 85) { return "#37d39b"; }
  if (score >= 72) { return "#4da3ff"; }
  if (score >= 58) { return "#f2b544"; }
  if (score >= 42) { return "#f0803c"; }
  return "#f2555a";
}

function verdictColor(key) {
  if (key === "decision_ready") { return "#37d39b"; }
  if (key === "mostly_ready") { return "#4da3ff"; }
  if (key === "needs_revision") { return "#f2b544"; }
  if (key === "tight_but_usable") { return "#f0803c"; }
  return "#f2555a";
}

/* ---------------------------------------------------------------- samples */

function loadSamples() {
  fetch("/api/samples").then(function (r) { return r.json(); }).then(function (data) {
    var box = $("sample-list");
    box.innerHTML = "";
    (data.samples || []).forEach(function (s) {
      var card = document.createElement("div");
      card.className = "sample";
      card.innerHTML = '<span class="tag">' + escapeHtml(s.doc_type) + "</span><strong>" +
        escapeHtml(s.title) + "</strong><span>" + escapeHtml(s.blurb) + "</span>";
      card.addEventListener("click", function () { loadSample(s.id); });
      box.appendChild(card);
    });
  }).catch(function () { setStatus("samples failed", "err"); });
}

function loadSample(id) {
  fetch("/api/sample/" + id).then(function (r) { return r.json(); }).then(function (s) {
    $("doc-text").value = s.text;
    $("doc-type").value = s.doc_type;
    $("stakes").value = s.stakes;
    $("reversibility").value = s.reversibility;
    $("audience").value = s.audience;
    setStatus("sample loaded", "ok");
    review();
  }).catch(function () { setStatus("sample failed", "err"); });
}

/* ---------------------------------------------------------------- analyze */

function review() {
  var text = $("doc-text").value;
  if (!text.trim()) {
    setStatus("nothing to review", "err");
    return;
  }
  setStatus("reviewing", "busy");
  var payload = {
    text: text,
    doc_type: $("doc-type").value,
    stakes: $("stakes").value,
    reversibility: $("reversibility").value,
    audience: $("audience").value
  };
  fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(function (r) { return r.json(); }).then(function (data) {
    if (data.error) {
      setStatus(data.error, "err");
      return;
    }
    state.report = data;
    state.sessionId = null;
    render(data);
    setStatus("scored " + data.score, "ok");
  }).catch(function (err) {
    setStatus("review failed", "err");
  });
}

function saveReview() {
  if (!state.report) { return; }
  var text = $("doc-text").value;
  var payload = {
    text: text,
    doc_type: $("doc-type").value,
    stakes: $("stakes").value,
    reversibility: $("reversibility").value,
    audience: $("audience").value,
    save: true,
    title: (state.report.meta.doc_type_label || "Decision document")
  };
  setStatus("saving", "busy");
  fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(function (r) { return r.json(); }).then(function (data) {
    if (data.error) { setStatus(data.error, "err"); return; }
    state.report = data;
    state.sessionId = data.session_id;
    render(data);
    $("save-status").textContent = "saved as review #" + data.session_id;
    $("btn-md").href = "/api/export/" + data.session_id + "?fmt=md";
    $("btn-json").href = "/api/export/" + data.session_id + "?fmt=json";
    setStatus("saved", "ok");
    loadHistory();
  }).catch(function () { setStatus("save failed", "err"); });
}

/* ---------------------------------------------------------------- render */

function render(data) {
  $("empty-state").hidden = true;
  $("report").hidden = false;

  $("score-num").textContent = data.score;
  $("verdict-pill").textContent = data.verdict.key.replace(/_/g, " ");
  $("verdict-pill").style.color = verdictColor(data.verdict.key);
  $("verdict-pill").style.borderColor = verdictColor(data.verdict.key);
  $("verdict-blurb").textContent = data.verdict.blurb;

  $("m-type").textContent = data.meta.doc_type_label +
    (data.meta.doc_type_detected ? " (detected)" : " (set)");
  $("m-words").textContent = data.input_words;
  $("m-findings").textContent = data.finding_counts.high + " high / " +
    data.finding_counts.medium + " medium / " + data.finding_counts.low + " low";
  $("m-options").textContent = data.options.count + " (" + data.options.method + ")";

  renderAxes(data);
  renderFindings(data);
  renderCoverage(data);
  renderOptions(data);
  renderPlan(data);
  renderStrengths(data);

  if (data.session_id) {
    state.sessionId = data.session_id;
    $("save-status").textContent = "saved as review #" + data.session_id;
    $("btn-md").href = "/api/export/" + data.session_id + "?fmt=md";
    $("btn-json").href = "/api/export/" + data.session_id + "?fmt=json";
  }
}

function renderAxes(data) {
  var row = $("axis-row");
  row.innerHTML = "";
  Object.keys(data.axes).forEach(function (axis) {
    var a = data.axes[axis];
    var color = colorFor(a.score);
    var el = document.createElement("div");
    el.className = "axis";
    el.innerHTML = '<div class="name">' + escapeHtml(axis) + "</div>" +
      '<div class="val" style="color:' + color + '">' + a.score + "</div>" +
      '<div class="bar"><i style="width:' + Math.max(2, a.score) + "%;background:" + color + '"></i></div>' +
      '<div class="w">weight ' + data.meta.weights[axis] + "</div>";
    el.title = a.components.map(function (c) {
      return c.name + ": " + c.score;
    }).join(" | ");
    row.appendChild(el);
  });
}

function renderFindings(data) {
  state.findings = data.findings;
  var box = $("findings-list");
  box.innerHTML = "";
  var visible = data.findings.filter(function (f) {
    var sevOk = state.severity === "all" || f.severity === state.severity;
    var axisOk = state.axis === "all" || f.axis === state.axis;
    return sevOk && axisOk;
  });
  if (!visible.length) {
    box.innerHTML = '<p class="muted">No findings match this filter. That is either good news or a sign the filter is too narrow.</p>';
    return;
  }
  visible.forEach(function (f) {
    var el = document.createElement("div");
    el.className = "finding " + f.severity;
    el.innerHTML = "<h4><span class='sev'>" + escapeHtml(f.severity) + "</span>" +
      escapeHtml(f.title) + "</h4>" +
      "<div class='why'>" + escapeHtml(f.why) + "</div>" +
      "<div class='fix'><strong>Fix:</strong> " + escapeHtml(f.fix) + "</div>" +
      (f.evidence ? "<div class='ev'>" + escapeHtml(f.evidence) + "</div>" : "");
    box.appendChild(el);
  });
}

function renderCoverage(data) {
  var box = $("coverage-list");
  box.innerHTML = "<h3 style='font-size:13px;color:var(--muted);margin-bottom:8px'>Section coverage (" +
    Math.round(data.coverage.coverage * 100) + "% of required sections)</h3>";
  data.scaffold.outline.forEach(function (o) {
    var cls = o.present ? "yes" : (o.requirement === "required" ? "no" : "opt");
    var how = data.coverage.confidence[o.key] || "";
    var row = document.createElement("div");
    row.className = "cov";
    row.innerHTML = '<span class="dot ' + cls + '"></span>' +
      '<span class="lbl">' + escapeHtml(o.label) + "</span>" +
      '<span class="req">' + escapeHtml(o.requirement) + "</span>" +
      '<span class="how">' + escapeHtml(how) + "</span>";
    row.title = o.guidance;
    box.appendChild(row);
  });

  var caps = $("caps-list");
  caps.innerHTML = "";
  if (data.caps.length) {
    caps.innerHTML = "<h3 style='font-size:13px;color:var(--muted);margin:14px 0 8px'>Score caps applied</h3>";
    data.caps.forEach(function (c) {
      var el = document.createElement("div");
      el.className = "note";
      el.innerHTML = "<strong>" + escapeHtml(c.axis) + " capped at " + c.ceiling + "</strong> - " +
        escapeHtml(c.reason);
      caps.appendChild(el);
    });
  }
}

function renderOptions(data) {
  var box = $("options-list");
  box.innerHTML = "";
  var o = data.options;
  if (!o.count) {
    box.innerHTML = '<p class="muted">No options were found. A decision document needs at least two alternatives plus doing nothing.</p>';
    return;
  }
  var head = document.createElement("div");
  head.className = "note";
  head.innerHTML = "<strong>" + o.count + " options</strong> found (source: " + escapeHtml(o.method) + "). " +
    "Description balance: " + o.asymmetry + "x spread between the longest and the median option. " +
    "Status quo option: " + escapeHtml(o.status_quo_option || "not present") + ". " +
    "Recommendation traces to: " + escapeHtml(o.traceable_to || "no named option") + ".";
  box.appendChild(head);

  if (o.criteria.length) {
    var table = document.createElement("table");
    table.className = "opt";
    var headRow = "<tr><th>Option</th>";
    o.criteria.forEach(function (c) { headRow += "<th>" + escapeHtml(c) + "</th>"; });
    headRow += "</tr>";
    var body = "";
    o.options.forEach(function (row) {
      body += "<tr><td>" + escapeHtml(row.name) + "</td>";
      var cells = row.source === "table" ? row.detail.split(" | ") : [row.detail];
      for (var i = 0; i < o.criteria.length; i++) {
        var cell = cells[i] === undefined ? "" : cells[i];
        body += cell.trim() === ""
          ? '<td class="blank">blank</td>'
          : "<td>" + escapeHtml(cell) + "</td>";
      }
      body += "</tr>";
    });
    table.innerHTML = "<thead>" + headRow + "</thead><tbody>" + body + "</tbody>";
    box.appendChild(table);
  } else {
    o.options.forEach(function (row) {
      var el = document.createElement("div");
      el.className = "note";
      el.innerHTML = "<strong>" + escapeHtml(row.name) + "</strong><br>" + escapeHtml(row.detail);
      box.appendChild(el);
    });
  }
}

function renderPlan(data) {
  var box = $("plan-list");
  box.innerHTML = "";
  if (!data.fix_plan.length) {
    box.innerHTML = '<p class="muted">Nothing to fix. Send it.</p>';
  }
  data.fix_plan.forEach(function (item) {
    var el = document.createElement("div");
    el.className = "plan-item";
    el.innerHTML = '<div class="rank">' + item.rank + "</div>" +
      '<div class="body"><div class="t"><span class="sev-tag ' + item.severity + '">' +
      escapeHtml(item.severity) + "</span>" + escapeHtml(item.title) + "</div>" +
      '<div class="f">' + escapeHtml(item.fix) + "</div></div>" +
      '<div class="gain">+' + item.estimated_gain + " pts</div>";
    box.appendChild(el);
  });

  var sc = $("scaffold-box");
  sc.innerHTML = "<h4>Rewrite scaffold</h4><p>" + escapeHtml(data.scaffold.prompt) + "</p>";
  var outline = document.createElement("div");
  outline.className = "outline";
  data.scaffold.outline.forEach(function (o) {
    var cls = o.present ? "" : (o.requirement === "required" ? "miss" : "opt");
    var label = o.present ? "have" : (o.requirement === "required" ? "missing" : "optional");
    outline.innerHTML += '<div class="row"><span class="tag ' + cls + '">' + label +
      "</span><span>" + escapeHtml(o.label) + "</span></div>";
  });
  sc.appendChild(outline);
}

function renderStrengths(data) {
  var box = $("strengths-list");
  box.innerHTML = "";
  data.strengths.forEach(function (s) {
    var el = document.createElement("div");
    el.className = "note";
    el.textContent = s;
    box.appendChild(el);
  });
}

/* ---------------------------------------------------------------- history */

function loadHistory() {
  fetch("/api/sessions?limit=20").then(function (r) { return r.json(); }).then(function (data) {
    var list = $("history-list");
    list.innerHTML = "";
    var sessions = data.sessions || [];
    $("history-count").textContent = sessions.length + " saved review(s)";
    if (!sessions.length) {
      list.innerHTML = '<p class="muted">No saved reviews yet. Press "Save review" after scoring a document.</p>';
      return;
    }
    sessions.forEach(function (s) {
      var row = document.createElement("div");
      row.className = "hist";
      var stars = "";
      for (var i = 1; i <= 5; i++) {
        stars += '<span class="' + (s.self_rating && s.self_rating >= i ? "on" : "") +
          '" data-star="' + i + '">&#9733;</span>';
      }
      row.innerHTML =
        '<div class="sc" style="color:' + colorFor(s.score || 0) + '">' + s.score + "</div>" +
        '<div><div class="t">' + escapeHtml(s.title || "Decision document") + "</div>" +
        '<div class="d">' + escapeHtml(s.verdict) + " | " + escapeHtml(s.doc_type) +
        " | " + escapeHtml((s.created_at || "").slice(0, 19)) + "</div></div>" +
        '<div class="rating">' + stars + "</div>" +
        '<div class="acts"><button class="btn btn-ghost" data-open="' + s.id +
        '">open</button></div>' +
        '<div class="notes"><input placeholder="Notes on this review" value="' +
        escapeHtml(s.notes || "") + '" data-notes="' + s.id + '"></div>';
      list.appendChild(row);
    });

    list.querySelectorAll("[data-star]").forEach(function (star) {
      star.addEventListener("click", function () {
        var id = star.getAttribute("data-open");
        var sid = star.closest(".hist").querySelector("[data-notes]").getAttribute("data-notes");
        var rating = parseInt(star.getAttribute("data-star"), 10);
        patchSession(sid, { self_rating: rating });
      });
    });
    list.querySelectorAll("[data-notes]").forEach(function (input) {
      input.addEventListener("change", function () {
        patchSession(input.getAttribute("data-notes"), { notes: input.value });
      });
    });
    list.querySelectorAll("[data-open]").forEach(function (btn) {
      btn.addEventListener("click", function () { openSession(btn.getAttribute("data-open")); });
    });
  }).catch(function () { /* history is best effort */ });
}

function patchSession(id, body) {
  fetch("/api/sessions/" + id, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function () { loadHistory(); });
}

function openSession(id) {
  fetch("/api/sessions/" + id).then(function (r) { return r.json(); }).then(function (data) {
    if (!data.report) { return; }
    state.report = data.report;
    state.sessionId = data.id;
    render(data.report);
    $("save-status").textContent = "loaded review #" + data.id;
    $("btn-md").href = "/api/export/" + data.id + "?fmt=md";
    $("btn-json").href = "/api/export/" + data.id + "?fmt=json";
    setStatus("review " + data.id + " loaded", "ok");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

/* ---------------------------------------------------------------- wiring */

document.addEventListener("DOMContentLoaded", function () {
  loadSamples();
  loadHistory();

  $("btn-review").addEventListener("click", review);
  $("btn-save").addEventListener("click", saveReview);
  $("btn-clear").addEventListener("click", function () {
    $("doc-text").value = "";
    $("save-status").textContent = "";
    setStatus("cleared", null);
  });

  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
      ["findings", "coverage", "options", "plan", "strengths"].forEach(function (name) {
        $("tab-" + name).hidden = (name !== tab.getAttribute("data-tab"));
      });
    });
  });

  document.querySelectorAll("#finding-filters .chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      document.querySelectorAll("#finding-filters .chip").forEach(function (c) {
        c.classList.remove("active");
      });
      chip.classList.add("active");
      state.severity = chip.getAttribute("data-sev");
      if (state.report) { renderFindings(state.report); }
    });
  });

  $("axis-filter").addEventListener("change", function () {
    state.axis = this.value;
    if (state.report) { renderFindings(state.report); }
  });

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      review();
    }
  });
});
