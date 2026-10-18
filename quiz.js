// A theory question, answered in place. No state, no server: the answer is in the page, because
// these are the unrated banks and their answers are public anyway (docs/rated-labs.md).
(function () {
  document.querySelectorAll(".quiz").forEach(function (quiz) {
    var answer = (quiz.dataset.answer || "").split(",").filter(Boolean);
    var verdict = quiz.querySelector(".verdict");
    var choices = Array.prototype.slice.call(quiz.querySelectorAll(".choice"));

    choices.forEach(function (button) {
      button.addEventListener("click", function () {
        if (quiz.classList.contains("answered")) return;
        quiz.classList.add("answered");
        var picked = button.dataset.choice;
        choices.forEach(function (other) {
          var right = answer.indexOf(other.dataset.choice) >= 0;
          other.classList.add(right ? "right" : "wrong");
          other.disabled = true;
        });
        button.classList.add("picked");
        quiz.classList.add(answer.indexOf(picked) >= 0 ? "correct" : "incorrect");
        if (verdict) verdict.hidden = false;
      });
    });
  });
})();
