/* The consultant widget: a question box on every page, answered from the repository.
 *
 * It asks the API, streams the answer over server-sent events, and shows the passages the answer
 * came from so a reader can go and check. The questions people arrive with sit underneath in
 * sections, one tap each.
 *
 * When the API cannot be reached — reading the site offline, or a deployment with no server — the
 * widget does not pretend to think: it ranks the site's own passages in the browser (BM25 over
 * ask-index.json, see ask-engine.js) and shows the best ones, quoted and linked.
 *
 * No framework, no dependency, and nothing is stored: the conversation lives in this tab only.
 */
(function () {
  "use strict";

  var api = (document.body.dataset.api || "").replace(/\/$/, "");
  var labId = document.body.dataset.lab || "";
  var root = document.body.dataset.root || "";
  var open = false;
  var busy = false;
  var panel, log, input, sections, button;
  var local = null;        // the in-browser index, loaded on first need
  var localGroups = null;  // FAQ sections from ask-index.json, for when the API is down

  var ICON =
    '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">' +
    '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 ' +
    '3.6c-.5.4-1.3.1-1.3-.6V16A2.5 2.5 0 0 1 4 13.5z" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linejoin="round"/>' +
    '<path d="M8.5 8.5h7M8.5 11.5h4.5" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round"/></svg>';
  var CLOSE =
    '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M6 6l12 12M18 6 ' +
    '6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function href(url) {
    return root + url.replace(/^\//, "");
  }

  function bubble(kind, text) {
    var node = el("div", "chat-msg " + kind);
    node.appendChild(el("div", "chat-body", text || ""));
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
  }

  function renderSources(node, sources) {
    if (!sources || !sources.length) return;
    var box = el("div", "chat-sources");
    box.appendChild(el("span", "chat-sources-label", "from"));
    sources.forEach(function (s) {
      var a = el("a", null, "[" + s.n + "] " + s.title);
      a.href = href(s.url);
      a.title = s.kind;
      box.appendChild(a);
    });
    node.appendChild(box);
  }

  /* ------------------------------------------------------------ the offline answer */

  function loadLocal() {
    if (local) return Promise.resolve(local);
    return fetch(root + "ask-index.json")
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .then(function (data) {
        localGroups = data.faq || null;
        local = new window.NorbotenAsk.Index(data.passages || [], data.synonyms || []);
        return local;
      });
  }

  function answerLocally(node, question, reason) {
    var body = node.querySelector(".chat-body");
    body.classList.remove("thinking");
    body.textContent = "…";
    return loadLocal().then(function (index) {
      var hits = index.search(question, 3);
      body.textContent = "";
      body.appendChild(el("p", "chat-offline", reason));
      if (!hits.length) {
        body.appendChild(el("p", null, "Nothing on the site matches that. Try the docs search."));
        return;
      }
      hits.forEach(function (hit, i) {
        var item = el("div", "chat-quote");
        var a = el("a", null, "[" + (i + 1) + "] " + hit.passage.title);
        a.href = href(hit.passage.url);
        item.appendChild(a);
        item.appendChild(el("p", null, window.NorbotenAsk.excerpt(hit.passage.text, question, 300)));
        body.appendChild(item);
      });
    }).catch(function () {
      body.textContent = reason + " The documentation holds the same material.";
    });
  }

  /* ------------------------------------------------------------ asking */

  function ask(question) {
    if (busy || !question.trim()) return;
    busy = true;
    showSections(false);
    bubble("me", question);
    input.value = "";
    var answer = bubble("them", "");
    var body = answer.querySelector(".chat-body");
    body.classList.add("thinking");

    function done() { busy = false; input.focus(); }

    if (!api || typeof EventSource === "undefined") {
      answerLocally(answer, question, "No consultant is configured here, so these are the " +
        "passages on this site that match best:").then(done);
      return;
    }

    var url =
      api + "/chat/stream?question=" + encodeURIComponent(question) +
      (labId ? "&lab_id=" + encodeURIComponent(labId) : "");
    var source = new EventSource(url);
    var text = "";

    source.addEventListener("sources", function (e) {
      renderSources(answer, JSON.parse(e.data).sources);
    });
    source.addEventListener("token", function (e) {
      body.classList.remove("thinking");
      text += JSON.parse(e.data).text;
      body.textContent = text;
      log.scrollTop = log.scrollHeight;
    });
    source.addEventListener("failed", function () {
      source.close();
      answerLocally(answer, question, "The consultant is not answering right now; these are " +
        "the passages on this site that match best:").then(done);
    });
    source.addEventListener("end", function () {
      source.close();
      body.classList.remove("thinking");
      if (!text) body.textContent = "No answer came back. The sources above are what matched.";
      done();
    });
    source.onerror = function () {
      source.close();
      if (text) { done(); return; }
      answerLocally(answer, question, "The consultant cannot be reached; these are the passages " +
        "on this site that match best:").then(done);
    };
  }

  /* ------------------------------------------------------------ the question sections */

  function renderGroups(groups) {
    sections.textContent = "";
    groups.forEach(function (group, i) {
      var details = el("details", "chat-group");
      if (i === 0) details.open = true;
      details.appendChild(el("summary", null, group.title));
      var chips = el("div", "chat-chips");
      group.chips.forEach(function (chip) {
        var b = el("button", "chat-chip", chip);
        b.type = "button";
        b.addEventListener("click", function () { ask(chip); });
        chips.appendChild(b);
      });
      details.appendChild(chips);
      sections.appendChild(details);
    });
  }

  function loadSections() {
    var fromSite = function () {
      return loadLocal().then(function () { if (localGroups) renderGroups(localGroups); });
    };
    if (!api) { fromSite().catch(function () {}); return; }
    fetch(api + "/chat/faq")
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .then(function (data) {
        renderGroups(data.categories || [{ title: "Questions", chips: data.chips || [] }]);
      })
      .catch(function () { fromSite().catch(function () {}); });
  }

  function showSections(show) {
    sections.hidden = !show;
    panel.querySelector(".chat-topics").setAttribute("aria-expanded", show ? "true" : "false");
  }

  /* ------------------------------------------------------------ the panel */

  function build() {
    panel = el("aside", "chat-panel");
    panel.hidden = true;
    panel.setAttribute("aria-label", "Ask about Norboten");
    panel.innerHTML =
      '<header><div><strong>Ask about Norboten</strong>' +
      '<span class="chat-sub">answers from the docs, journals, labs and theory</span></div>' +
      '<button type="button" class="chat-close" aria-label="Close">' + CLOSE + "</button></header>" +
      '<div class="chat-log"></div>' +
      '<div class="chat-sections"></div>' +
      '<form class="chat-form">' +
      '<button type="button" class="chat-topics" aria-expanded="true" title="Show the questions">☰</button>' +
      '<input type="text" placeholder="How is a lab graded?" aria-label="Your question" maxlength="500">' +
      '<button type="submit">Ask</button></form>';
    document.body.appendChild(panel);

    log = panel.querySelector(".chat-log");
    sections = panel.querySelector(".chat-sections");
    input = panel.querySelector("input");

    bubble(
      "them",
      "I answer from this repository — the docs, the journals, the lab briefings and the theory " +
      "explanations — and I will not hand over a lab's solution. Pick a question below, or ask " +
      "your own."
    );

    panel.querySelector(".chat-close").addEventListener("click", function () { toggle(false); });
    panel.querySelector(".chat-topics").addEventListener("click", function () {
      showSections(sections.hidden);
    });
    panel.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      ask(input.value);
    });
    loadSections();
  }

  function toggle(want) {
    if (!panel) build();
    open = typeof want === "boolean" ? want : !open;
    panel.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.classList.toggle("is-open", open);
    if (open) input.focus();
  }

  function init() {
    button = el("button", "chat-button");
    button.type = "button";
    button.innerHTML = ICON;
    button.setAttribute("aria-label", "Ask about Norboten");
    button.setAttribute("aria-expanded", "false");
    button.title = "Ask about Norboten";
    button.addEventListener("click", function () { toggle(); });
    document.body.appendChild(button);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && open) toggle(false);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
