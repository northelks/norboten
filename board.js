/* The board's filters: a nick, a topic, and the two ends of a rating range.
 *
 * Everything is in the page already, so this only hides rows — no request, no re-sort. The rank
 * column keeps the rank the learner has on the whole board, not a position in the filtered view.
 */
(function () {
  "use strict";
  var form = document.getElementById("boardfilter");
  var table = document.getElementById("boardtable");
  if (!form || !table) return;

  var rows = Array.prototype.slice.call(table.querySelectorAll("tr[data-nick]"));
  var nick = document.getElementById("filter-nick");
  var topic = document.getElementById("filter-topic");
  var min = document.getElementById("filter-min");
  var max = document.getElementById("filter-max");
  var minOut = document.getElementById("filter-min-out");
  var maxOut = document.getElementById("filter-max-out");
  var count = document.getElementById("filter-count");

  function apply() {
    var lo = parseInt(min.value, 10);
    var hi = parseInt(max.value, 10);
    if (lo > hi) { // the two handles cannot cross
      if (document.activeElement === min) { hi = lo; max.value = hi; }
      else { lo = hi; min.value = lo; }
    }
    minOut.textContent = lo;
    maxOut.textContent = hi;
    var text = nick.value.trim().toLowerCase();
    var want = topic.value;
    var shown = 0;
    rows.forEach(function (row) {
      var rating = parseInt(row.dataset.rating, 10);
      var topics = (row.dataset.topics || "").split("|");
      var ok = rating >= lo && rating <= hi &&
        (!text || row.dataset.nick.toLowerCase().indexOf(text) >= 0) &&
        (!want || topics.indexOf(want) >= 0);
      row.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = shown + " of " + rows.length;
  }

  form.addEventListener("input", apply);
  form.addEventListener("submit", function (e) { e.preventDefault(); });
  apply();
})();
