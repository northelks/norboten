// A button with data-copy="<selector>" copies that element's text.
document.querySelectorAll("button[data-copy]").forEach(function (b) {
  b.addEventListener("click", function () {
    var el = document.querySelector(b.dataset.copy);
    if (!el || !navigator.clipboard) return;
    navigator.clipboard.writeText(el.textContent.trim()).then(function () {
      var old = b.textContent;
      b.textContent = "copied";
      setTimeout(function () { b.textContent = old; }, 1200);
    });
  });
});
