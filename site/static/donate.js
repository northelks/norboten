/* The donate page: pick an amount and an interval, and the API opens a Stripe Checkout Session.
 *
 * Nothing about a card is handled here — the button leads to Stripe's own page, and this script
 * only asks the API for its address (the API's routers/donate.py).
 */
(function () {
  "use strict";

  var api = (document.body.dataset.api || "").replace(/\/$/, "");
  var form = document.getElementById("give");
  if (!form) return;

  var go = document.getElementById("give-go");
  var problem = document.getElementById("give-problem");
  var other = document.getElementById("give-other");
  var amounts = form.querySelectorAll("button.amount");
  var intervals = form.querySelectorAll("button.pill");

  var state = { amount: 10, interval: "monthly" };

  function label() {
    var amount = state.amount ? "€" + state.amount : "";
    go.textContent = state.interval === "monthly"
      ? "Donate " + amount + " a month"
      : "Donate " + amount + " once";
    go.disabled = !state.amount;
  }

  function say(text) {
    problem.textContent = text || "";
    problem.hidden = !text;
  }

  function pick(amount) {
    state.amount = amount;
    amounts.forEach(function (b) {
      var on = Number(b.dataset.amount) === amount;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    label();
  }

  amounts.forEach(function (b) {
    b.addEventListener("click", function () {
      other.value = "";
      pick(Number(b.dataset.amount));
      say("");
    });
  });

  other.addEventListener("input", function () {
    var value = Math.floor(Number(other.value));
    pick(value >= 2 && value <= 5000 ? value : 0);
    say("");
  });

  intervals.forEach(function (b) {
    b.addEventListener("click", function () {
      state.interval = b.dataset.interval;
      intervals.forEach(function (p) {
        p.setAttribute("aria-pressed", p === b ? "true" : "false");
      });
      label();
    });
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!state.amount) return;
    say("");
    go.disabled = true;
    var was = go.textContent;
    go.textContent = "Opening Stripe…";
    fetch(api + "/donations/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: state.amount, interval: state.interval })
    }).then(function (answer) {
      return answer.json().then(function (data) { return { ok: answer.ok, status: answer.status, data: data }; });
    }).then(function (result) {
      if (result.ok && result.data.url) {
        window.location.href = result.data.url;
        return;
      }
      go.textContent = was;
      go.disabled = false;
      if (result.status === 503) {
        say("Card donations are switched off on this deployment. The other ways to help below need no money.");
      } else if (result.status === 429) {
        say("That is a lot of attempts in one minute. Try again shortly.");
      } else {
        say("Stripe could not be reached. Nothing was charged — please try again in a moment.");
      }
    }).catch(function () {
      go.textContent = was;
      go.disabled = false;
      say("The donation could not be started — the API did not answer. Nothing was charged.");
    });
  });

  label();
})();
