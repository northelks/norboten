/* The relation graph, explored with a pointer.
 *
 * The picture is inline SVG the build drew from the same layout the printed chart uses, so this
 * only has to light up the node under the pointer, the edges that touch it and what they lead to.
 */
(function () {
  "use strict";
  var wrap = document.getElementById("relations");
  var read = document.getElementById("relationsread");
  if (!wrap || !read) return;
  var svg = wrap.querySelector("svg.relations");
  var edges = Array.prototype.slice.call(svg.querySelectorAll(".edge"));
  var nodes = {};
  svg.querySelectorAll(".node").forEach(function (node) { nodes[node.dataset.id] = node; });

  function clear() {
    svg.classList.remove("focused");
    edges.forEach(function (e) { e.classList.remove("on"); });
    Object.keys(nodes).forEach(function (id) { nodes[id].classList.remove("on", "near"); });
    read.textContent = "Point at a node: its own connections light up.";
  }

  function show(node) {
    clear();
    var id = node.dataset.id;
    svg.classList.add("focused");
    node.classList.add("on");
    var declared = 0, textual = 0;
    edges.forEach(function (edge) {
      if (edge.dataset.a !== id && edge.dataset.b !== id) return;
      edge.classList.add("on");
      var other = nodes[edge.dataset.a === id ? edge.dataset.b : edge.dataset.a];
      if (other) other.classList.add("near");
      if (edge.classList.contains("text")) textual++; else declared++;
    });
    read.textContent = node.dataset.label + " · " + node.dataset.kind + " · " +
      declared + " topic edge" + (declared === 1 ? "" : "s") + " · " +
      textual + " textual neighbour" + (textual === 1 ? "" : "s");
  }

  wrap.addEventListener("mouseover", function (e) {
    var node = e.target.closest ? e.target.closest(".node") : null;
    if (node) show(node);
  });
  wrap.addEventListener("focusin", function (e) {
    var node = e.target.closest ? e.target.closest(".node") : null;
    if (node) show(node);
  });
  svg.addEventListener("mouseleave", clear);
})();
