/* The Live section: ask the API who is working right now, and open a read-only terminal for each.
 *
 * The site is static, so this is the one page that talks to the API from the browser. The wall of
 * four recorded sessions is always there; a live session takes one of its places while it runs.
 * When the API is not reachable the wall simply keeps playing.
 */
(function () {
  "use strict";

  var REFRESH_MS = 15000;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function flag(country) {
    if (!country || country.length !== 2) return "";
    return String.fromCodePoint.apply(null, country.toUpperCase().split("").map(function (c) {
      return 0x1f1e6 + c.charCodeAt(0) - 65;
    }));
  }

  /* A live session takes a slot on the wall; when it ends, the recording that was there comes
   * back. The wall's own figures are kept as they were built, and restored from that copy. */
  function liveFigure(api, session) {
    var box = el("figure", "wallterm");
    var caption = el("figcaption");
    var dot = el("span", "pulse");
    caption.appendChild(dot);
    caption.appendChild(el("strong", null, session.nick + " " + flag(session.country)));
    caption.appendChild(el("span", "muted mono", session.lab_title || session.lab_id));
    box.appendChild(caption);
    var term = el("div", "term");
    term.dataset.cols = session.width;
    term.dataset.rows = session.height;
    term.dataset.live = api + "/play/sessions/" + session.session_id + "/stream";
    term.appendChild(el("span", "termlabel", "streaming"));
    box.appendChild(term);
    box.dataset.session = session.session_id;
    return { box: box, term: term };
  }

  var originals = [];

  function render(section, api, data) {
    var state = section.querySelector("#livestate");
    var slots = section.querySelectorAll(".wall > figure");
    if (!originals.length) {
      slots.forEach(function (f) { originals.push(f.cloneNode(true)); });
    }
    var live = data.live || [];
    state.hidden = !live.length;
    state.textContent = live.length === 1 ? "One session is live." : live.length + " sessions are live.";

    slots.forEach(function (slot, i) {
      var session = live[i];
      if (session) {
        if (slot.dataset.session === session.session_id) return;
        var built = liveFigure(api, session);
        slot.replaceWith(built.box);
        if (window.NorbotenTerm && window.NorbotenTerm.mount) window.NorbotenTerm.mount(built.term);
      } else if (slot.dataset.session) {
        var back = originals[i].cloneNode(true);
        slot.replaceWith(back);
        var term = back.querySelector("[data-cast]");
        if (term) {  // the copy carries the old player's widgets: start it clean
          term.textContent = "";
          delete term.dataset.mounted;
          term.classList.remove("has-player");
        }
        if (term && window.NorbotenTerm && window.NorbotenTerm.mount) window.NorbotenTerm.mount(term);
      }
    });
  }

  function poll(section, api) {
    fetch(api + "/play/live", { mode: "cors" })
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .then(function (data) { render(section, api, data); })
      .catch(function () {
        // unreachable: the wall keeps playing what it has, and nothing claims to be live
        render(section, api, { live: [] });
      });
  }

  function init() {
    var section = document.getElementById("live");
    if (!section) return;
    var api = (section.dataset.api || "").replace(/\/$/, "");
    if (!api) return;
    poll(section, api);
    setInterval(function () { poll(section, api); }, REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
