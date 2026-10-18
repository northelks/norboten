/* A profile page: what was done on a day of the heatmap, and one attempt in a large popup.
 *
 * The heatmap is an SVG the build draws; hovering (or focusing) a day shows the labs attempted that
 * day, from a JSON block the build writes beside it. Clicking an attempt opens it with a replay of
 * a recorded session of the same lab when the site ships one. Sample accounts have no recordings
 * of their own, and the popup says so rather than implying the replay is theirs.
 */
(function () {
  "use strict";

  var root = document.body.dataset.root || "";

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  /* ------------------------------------------------------------ the heatmap */

  function heatmap(openAttempt) {
    var wrap = document.getElementById("heatmap");
    var tip = document.getElementById("heattip");
    var data = document.getElementById("heatdays");
    if (!wrap || !tip || !data) return;
    var days = JSON.parse(data.textContent || "{}");

    function summary(day, done) {
      var when = new Date(day + "T12:00:00Z").toLocaleDateString(undefined, {
        weekday: "short", day: "numeric", month: "short", year: "numeric"
      });
      var head = document.createDocumentFragment();
      head.appendChild(el("strong", null, when));
      head.appendChild(el("span", "muted",
        " · " + done.length + " attempt" + (done.length === 1 ? "" : "s")));
      return head;
    }

    function show(rect) {
      var day = rect.getAttribute("data-day");
      var done = days[day] || [];
      tip.textContent = "";
      tip.appendChild(summary(day, done));
      if (done.length) {
        var list = el("ul");
        done.slice(0, 8).forEach(function (item) {
          var li = el("li");
          li.appendChild(el("span", item.passed ? "pass" : "fail", item.passed ? "✓ " : "✗ "));
          li.appendChild(document.createTextNode(item.title));
          if (item.kind === "quiz") li.appendChild(el("span", "tag", "theory"));
          list.appendChild(li);
        });
        if (done.length > 8) list.appendChild(el("li", "muted", "and " + (done.length - 8) + " more"));
        tip.appendChild(list);
        tip.appendChild(el("p", "muted small", "click the day for the attempts themselves"));
      }
      tip.hidden = false;
      // beside the square itself, not where the page happens to start
      var box = wrap.getBoundingClientRect();
      var cell = rect.getBoundingClientRect();
      var left = cell.left - box.left + cell.width + 8;
      tip.style.left = Math.max(0, Math.min(left, wrap.clientWidth - 240)) + "px";
      tip.style.top = (cell.bottom - box.top + 8) + "px";
    }

    function dayOf(target) {
      var rect = target.closest ? target.closest("rect[data-day]") : null;
      return rect && rect.getAttribute("data-count") !== "0" ? rect : null;
    }

    wrap.addEventListener("mousemove", function (e) {
      var rect = dayOf(e.target);
      if (!rect) { tip.hidden = true; return; }
      show(rect);
    });
    wrap.addEventListener("mouseleave", function () { tip.hidden = true; });
    wrap.addEventListener("click", function (e) {
      var rect = dayOf(e.target);
      if (!rect || !openAttempt) return;
      var day = rect.getAttribute("data-day");
      openAttempt.day(day, days[day] || []);
    });

    var tabs = document.getElementById("heatyears");
    if (!tabs) return;
    tabs.addEventListener("click", function (e) {
      var button = e.target.closest ? e.target.closest("button[data-year]") : null;
      if (!button) return;
      tabs.querySelectorAll("button[data-year]").forEach(function (other) {
        if (other === button) other.setAttribute("aria-current", "true");
        else other.removeAttribute("aria-current");
      });
      wrap.querySelectorAll(".heatyear").forEach(function (panel) {
        panel.hidden = panel.dataset.year !== button.dataset.year;
      });
      tip.hidden = true;
    });
  }

  /* -------------------------------------------------------------- the radar */

  function radar() {
    var wrap = document.getElementById("radar");
    var read = document.getElementById("radarread");
    if (!wrap || !read) return;
    function show(spoke) {
      wrap.querySelectorAll(".spoke.on").forEach(function (s) { s.classList.remove("on"); });
      spoke.classList.add("on");
      var games = parseInt(spoke.dataset.games, 10) || 0;
      read.textContent = spoke.dataset.title + " · " + spoke.dataset.rating + " · " +
        games + " lab" + (games === 1 ? "" : "s");
    }
    wrap.addEventListener("mouseover", function (e) {
      var spoke = e.target.closest ? e.target.closest(".spoke") : null;
      if (spoke) show(spoke);
    });
    wrap.addEventListener("focusin", function (e) {
      var spoke = e.target.closest ? e.target.closest(".spoke") : null;
      if (spoke) show(spoke);
    });
  }

  /* ------------------------------------------------------------ one attempt */

  function attempts() {
    var modal = document.getElementById("attemptmodal");
    if (!modal) return null;
    var slot = document.getElementById("attemptterm");
    var note = document.getElementById("attemptnote");
    var current = null;

    function close() {
      if (current && current.norbotenPlayer) current.norbotenPlayer.pause();
      modal.hidden = true;
      slot.textContent = "";
      current = null;
    }

    function open(a) {
      document.getElementById("attemptkind").textContent =
        (a.kind === "quiz" ? "Theory run" : "Lab attempt") + " · " + a.when;
      document.getElementById("attempttitle").textContent = a.title;
      var result = a.passed ? "passed" : "not passed";
      var rating = a.rated ? ("rating " + (a.delta >= 0 ? "+" : "") + a.delta) : "practice, not rated";
      document.getElementById("attemptmeta").textContent =
        result + " · score " + a.score + "% · took " + a.duration + " · " + rating;
      slot.textContent = "";
      if (a.recording) {
        note.hidden = false;
        note.textContent = "A recorded session of this lab, on a real VM — not this attempt: " +
          "sample accounts have no recordings of their own.";
        current = el("div", "term");
        current.dataset.cast = root + "streams/" + a.recording + ".json";
        current.dataset.theme = "green";
        slot.appendChild(current);
        window.NorbotenTerm.mount(current);
      } else {
        note.hidden = false;
        note.textContent = a.kind === "quiz"
          ? "Theory runs are never recorded — only the answers and the score."
          : "No recording of this lab ships with the site yet.";
      }
      modal.hidden = false;
      modal.querySelector(".modal-close").focus();
    }

    /* A day of the heatmap: what was attempted, as a list; pick one to see it. */
    function openDay(day, done) {
      if (!done.length) return;
      var when = new Date(day + "T12:00:00Z").toLocaleDateString(undefined, {
        weekday: "long", day: "numeric", month: "long", year: "numeric"
      });
      document.getElementById("attemptkind").textContent = "A day";
      document.getElementById("attempttitle").textContent = when;
      document.getElementById("attemptmeta").textContent =
        done.length + " attempt" + (done.length === 1 ? "" : "s") + " · " +
        done.filter(function (a) { return a.passed; }).length + " passed";
      note.hidden = true;
      slot.textContent = "";
      var list = el("ul", "daylist");
      done.forEach(function (a) {
        var item = el("li");
        var button = el("button", "dayitem");
        button.type = "button";
        button.appendChild(el("span", a.passed ? "pass" : "fail", a.passed ? "✓" : "✗"));
        button.appendChild(el("span", "t", a.title));
        button.appendChild(el("span", "muted mono",
          a.score + "% · " + a.duration + (a.rated ? "" : " · practice")));
        button.addEventListener("click", function () { open(a); });
        item.appendChild(button);
        list.appendChild(item);
      });
      slot.appendChild(list);
      modal.hidden = false;
      modal.querySelector(".modal-close").focus();
    }

    document.querySelectorAll("tr.attempt").forEach(function (row) {
      var a = JSON.parse(row.getAttribute("data-attempt"));
      row.addEventListener("click", function () { open(a); });
      row.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(a); }
      });
    });
    modal.querySelector(".modal-close").addEventListener("click", close);
    modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !modal.hidden) close();
    });
    return { day: openDay, one: open };
  }

  function init() { heatmap(attempts()); radar(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
