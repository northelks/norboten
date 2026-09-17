/* BM25 in the browser, for when the consultant cannot be reached.
 *
 * The site ships ask-index.json: the same passages the API's consultant retrieves from
 * (api/src/norboten_api/retrieval.py builds both), with the same exclusions — no solution file, no
 * hint ladder, no journal walkthrough. When the API is down this ranks those passages locally and
 * the widget shows the best ones, quoted and linked. It never writes an answer of its own.
 *
 * The tokenizer and the constants match the Python side, so a question ranks the same passages in
 * both places.
 */
(function (root) {
  "use strict";

  var K1 = 1.5;
  var B = 0.75;
  var WORD = /[a-z0-9_.\-/]+/g;
  var STOP = {};
  ("a an the and or but if of to in on for with without from by is are was were be been " +
   "being it its this that these those as at not no you your they them we our can may might " +
   "will would should could do does did done has have had what which who when where why how")
    .split(" ").forEach(function (w) { STOP[w] = true; });

  function tokenize(text) {
    var out = [];
    var words = String(text || "").toLowerCase().match(WORD) || [];
    for (var i = 0; i < words.length; i++) {
      if (words[i].length > 1 && !STOP[words[i]]) out.push(words[i]);
    }
    return out;
  }

  function counts(terms) {
    var c = {};
    for (var i = 0; i < terms.length; i++) c[terms[i]] = (c[terms[i]] || 0) + 1;
    return c;
  }

  /* Query terms and weights: each term 1, its synonyms 0.5 — retrieval.expand() on the API side. */
  var SYNONYM_WEIGHT = 0.5;
  function expand(terms, synonymsOf) {
    var weights = {}, i, j;
    for (i = 0; i < terms.length; i++) weights[terms[i]] = 1;
    for (i = 0; i < terms.length; i++) {
      var group = synonymsOf[terms[i]] || [];
      for (j = 0; j < group.length; j++) {
        if (!(group[j] in weights)) weights[group[j]] = SYNONYM_WEIGHT;
      }
    }
    return weights;
  }

  /* Build once: term counts per passage and document frequencies. */
  function Index(passages, synonyms) {
    var synonymsOf = {};
    (synonyms || []).forEach(function (group) {
      group.forEach(function (w) { synonymsOf[w] = group; });
    });
    this.synonymsOf = synonymsOf;
    this.passages = passages.map(function (p) {
      var terms = tokenize(p.title + " " + p.text);
      return { p: p, tf: counts(terms), length: terms.length };
    });
    var df = {};
    var total = 0;
    this.passages.forEach(function (d) {
      total += d.length;
      Object.keys(d.tf).forEach(function (t) { df[t] = (df[t] || 0) + 1; });
    });
    this.df = df;
    this.n = this.passages.length;
    this.avg = this.n ? total / this.n : 0;
  }

  Index.prototype.idf = function (term) {
    var n = this.df[term] || 0;
    return n ? Math.log(1 + (this.n - n + 0.5) / (n + 0.5)) : 0;
  };

  Index.prototype.search = function (query, limit) {
    var weights = expand(tokenize(query), this.synonymsOf);
    var terms = Object.keys(weights);
    var hits = [];
    if (!terms.length) return hits;
    for (var i = 0; i < this.passages.length; i++) {
      var d = this.passages[i];
      var score = 0;
      for (var j = 0; j < terms.length; j++) {
        var f = d.tf[terms[j]] || 0;
        if (!f) continue;
        var norm = 1 - B + B * (d.length / (this.avg || 1));
        score += weights[terms[j]] * this.idf(terms[j]) * (f * (K1 + 1)) / (f + K1 * norm);
      }
      if (score > 0) hits.push({ passage: d.p, score: Math.round(score * 1e4) / 1e4 });
    }
    hits.sort(function (a, b) { return b.score - a.score; });
    return hits.slice(0, limit || 3);
  };

  /* The sentences of a passage that carry the most query terms, in their original order. */
  function excerpt(text, query, maxChars) {
    var wanted = counts(tokenize(query));
    var plain = String(text)
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/^\|[\s:|-]+\|$/gm, "")                        // a table's rule line
      .replace(/^\|(.*)\|$/gm, function (_, row) {              // a table row: one sentence
        return row.split("|").map(function (c) { return c.trim(); }).filter(Boolean).join(" — ") + ".\n\n";
      })
      .replace(/[#*_`>]/g, " ");
    var sentences = plain.split(/(?<=[.!?])\s+|\n{2,}/).map(function (s) {
      return s.replace(/\s+/g, " ").trim();
    }).filter(Boolean);
    var scored = sentences.map(function (s, i) {
      var t = tokenize(s), score = 0;
      for (var k = 0; k < t.length; k++) if (wanted[t[k]]) score++;
      return { i: i, s: s, score: score };
    });
    var best = scored.slice().sort(function (a, b) { return b.score - a.score || a.i - b.i; });
    var chosen = [], used = 0, limit = maxChars || 320;
    for (var n = 0; n < best.length && used < limit; n++) {
      if (!best[n].score && chosen.length) break;
      chosen.push(best[n]);
      used += best[n].s.length;
    }
    chosen.sort(function (a, b) { return a.i - b.i; });
    var out = chosen.map(function (c) { return c.s; }).join(" … ");
    return out.length > limit ? out.slice(0, limit - 1) + "…" : out;
  }

  var api = { tokenize: tokenize, expand: expand, Index: Index, excerpt: excerpt, K1: K1, B: B };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.NorbotenAsk = api;
})(typeof window !== "undefined" ? window : globalThis);
