// Back to the top, once there is a page above you. Sits above the consultant's bubble.
(function () {
  var button = document.getElementById("to-top");
  if (!button) return;
  function update() {
    button.hidden = window.scrollY < window.innerHeight;
  }
  window.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);
  button.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  update();
})();
