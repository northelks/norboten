/* The account pages: sign in with GitHub, choose a nick, link Discord for the weekly digest, and
 * answer an MCP client's request to read the account (OAuth; the API's routers/oauth.py).
 *
 * Signing in is one button. The page makes a random `state`, keeps it in sessionStorage and sends
 * the browser to the API, which sends it on to GitHub. GitHub sends it back to the API, and the API
 * back here with `#once=…&state=…` in the fragment: the page checks the state is the one it made
 * (so nobody can sign this browser into their own account), then exchanges the one-time code for a
 * token. "Remember this browser" is the whole difference between a ninety-day token in localStorage
 * and a twelve-hour one in sessionStorage — there are no cookies.
 */
(function () {
  "use strict";

  var api = (document.body.dataset.api || "").replace(/\/$/, "");
  var box = document.getElementById("account");
  if (!box) return;
  var page = box.dataset.page;
  var KEY = "norboten.token";
  var STATE = "norboten.signin.state";
  var NICK = /^[a-z0-9][a-z0-9_-]{1,18}[a-z0-9]$/;
  var identity = null;

  function $(id) { return document.getElementById(id); }
  function show(id, on) { var el = $(id); if (el) el.hidden = !on; }

  /* base.html sets the same word from the token before the page paints; this keeps it right when
   * signing in or out happens on this page, without a reload. */
  function paintNav(signedIn) {
    var links = document.querySelectorAll(".nav-account");
    for (var i = 0; i < links.length; i++) links[i].textContent = signedIn ? "Account" : "Sign in";
  }

  /* A remembered browser keeps the token until it expires; an unremembered one keeps it only as
   * long as the tab. Both can throw in a private window, where the sign-in lasts one page. */
  function token() {
    try { return localStorage.getItem(KEY) || sessionStorage.getItem(KEY) || ""; }
    catch (e) { return ""; }
  }
  function keep(value, remember) {
    try {
      localStorage.removeItem(KEY);
      sessionStorage.removeItem(KEY);
      if (value) (remember ? localStorage : sessionStorage).setItem(KEY, value);
    } catch (e) { /* private window: the session lasts as long as the page */ }
  }

  function message(text, bad) {
    var el = $("acct-message");
    el.textContent = text;
    el.className = "acct-message" + (bad ? " bad" : " good");
    el.hidden = !text;
  }

  function call(method, path, body) {
    var headers = { "Content-Type": "application/json" };
    if (token()) headers.Authorization = "Bearer " + token();
    return fetch(api + path, {
      method: method,
      headers: headers,
      body: body ? JSON.stringify(body) : undefined,
      mode: "cors"
    }).then(function (r) {
      return r.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        return { status: r.status, data: data };
      });
    });
  }

  function detail(res, fallback) {
    var d = res.data && res.data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) return d[0].msg || fallback;
    return fallback;
  }

  function requestId() { return new URLSearchParams(location.search).get("request") || ""; }

  /* ------------------------------------------------------------ signing in */

  function randomState() {
    var bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }

  function signIn() {
    var state = randomState();
    try { sessionStorage.setItem(STATE, state); } catch (e) { /* the check below will then refuse */ }
    var target = page === "authorize" ? "authorize:" + requestId() : "account";
    location.assign(api + "/auth/github/go?" + new URLSearchParams({
      state: state,
      remember: $("acct-remember").checked ? "true" : "false",
      "return": target
    }).toString());
  }

  var ERRORS = {
    "denied": "Signing in was cancelled on GitHub.",
    "expired": "That sign-in took too long or was already used; sign in again.",
    "github": "GitHub did not complete the sign-in; try again in a moment.",
    "not-configured": "Sign-in is not configured on this server."
  };
  var DISCORD = {
    "linked": ["Discord is linked.", false],
    "joined": ["Discord is linked, and you are in the Norboten server.", false],
    "taken": ["That Discord account is already linked to another Norboten account.", true],
    "denied": ["Linking Discord was cancelled.", true],
    "expired": ["That link took too long; try again.", true],
    "error": ["Discord did not complete the link; try again in a moment.", true]
  };

  /* What the API put in the fragment on the way back: a one-time code, an error, or a Discord
   * result. The fragment is cleared at once, so a reload or a shared URL carries nothing. */
  function fromFragment() {
    var hash = new URLSearchParams(location.hash.slice(1));
    if (!hash.has("once") && !hash.has("error") && !hash.has("discord")) return Promise.resolve();
    history.replaceState(null, "", location.pathname + location.search);
    if (hash.has("error")) {
      message(ERRORS[hash.get("error")] || "Signing in did not work.", true);
      return Promise.resolve();
    }
    if (hash.has("discord")) {
      var said = DISCORD[hash.get("discord")] || DISCORD.error;
      message(said[0], said[1]);
      return Promise.resolve();
    }
    var expected = "";
    try { expected = sessionStorage.getItem(STATE) || ""; sessionStorage.removeItem(STATE); } catch (e) { expected = ""; }
    if (!expected || expected !== hash.get("state")) {
      message("This sign-in was not started from this browser, so it was not used.", true);
      return Promise.resolve();
    }
    return call("POST", "/auth/github/exchange", { once: hash.get("once") }).then(function (res) {
      if (res.status !== 200) { message(detail(res, "Signing in did not work."), true); return; }
      keep(res.data.token, res.data.expires_in > 86400);
      message(res.data.new_account ? "Your account is made — you are signed in." : "Signed in as " + res.data.github_login + ".", false);
    });
  }

  function signedOut() {
    show("acct-signed-in", false);
    show("acct-authorize", false);
    show("acct-signin", true);
    paintNav(false);
  }

  /* ------------------------------------------------------------ signed in */

  function flag(country) {
    return String.fromCodePoint.apply(null, country.toUpperCase().split("").map(function (c) {
      return 0x1f1e6 + c.charCodeAt(0) - 65;
    }));
  }

  function when(seconds) {
    return new Date(seconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  /* The GitHub login as a nick draft: lower case, only what a nick may hold, three to twenty. */
  function nickDraft(login) {
    var draft = (login || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "").slice(0, 20);
    draft = draft.replace(/[-_]+$/g, "");
    while (draft.length < 3) draft += "0";
    return NICK.test(draft) ? draft : "";
  }

  function loadIdentity() {
    return call("GET", "/auth/me").then(function (res) {
      if (res.status === 401) { keep("", false); signedOut(); return false; }
      if (res.status !== 200) return true;
      identity = res.data;
      var who = $("acct-github");
      who.textContent = "";
      var img = document.createElement("img");
      img.src = "https://github.com/" + encodeURIComponent(identity.github_login) + ".png?size=64";
      img.alt = "";
      img.width = 40;
      img.height = 40;
      var link = document.createElement("a");
      link.href = "https://github.com/" + encodeURIComponent(identity.github_login);
      link.rel = "noopener";
      link.textContent = identity.github_login;
      var text = document.createElement("span");
      text.append("Signed in with GitHub as ", link);
      who.append(img, text);
      show("acct-github", true);
      paintDiscord();
      return true;
    });
  }

  function paintDiscord() {
    var d = identity && identity.discord;
    if (!d || !d.available) { show("acct-discord", false); return; }
    show("acct-discord", true);
    show("discord-connect", !d.linked);
    show("discord-linked", d.linked);
    $("digest-on").disabled = !d.linked;
    $("digest-on").checked = !!identity.digest;
    $("discord-error").textContent = d.error || "";
    show("discord-error", !!d.error);
  }

  function loadProfile() {
    return call("GET", "/me").then(function (res) {
      if (res.status === 401) { keep("", false); signedOut(); return; }
      show("acct-signin", false);
      show("acct-signed-in", true);
      if (res.status === 404) {
        show("acct-claim", true);
        show("acct-profile", false);
        show("acct-country", false);
        var form = $("claim-form");
        if (!form.nick.value && identity) form.nick.value = nickDraft(identity.github_login);
        if (!form.country.value) {
          call("GET", "/geo/country").then(function (guess) {
            if (guess.status === 200 && guess.data.country && !form.country.value) form.country.value = guess.data.country;
          });
        }
        return;
      }
      show("acct-claim", false);
      $("country-form").country.value = res.data.user.country;
      show("acct-country", true);
      var p = res.data, card = $("acct-profile");
      card.textContent = "";
      var h = document.createElement("h3");
      h.textContent = p.user.nick + " " + flag(p.user.country);
      card.appendChild(h);
      var line = document.createElement("p");
      line.className = "muted";
      line.textContent = p.overall.rating + " ± " + p.overall.rd +
        (p.overall.provisional ? " (provisional)" : "") + " · " + p.passed + " passed of " +
        p.attempts + " attempts";
      card.appendChild(line);
      card.hidden = false;
    });
  }

  function loadTokens() {
    /* The card holds the sign-out button, so it is there for anyone signed in — an empty or
     * unreachable list must not take the only way out with it. */
    show("acct-tokens", true);
    return call("GET", "/auth/tokens").then(function (res) {
      if (res.status !== 200) return;
      var list = $("token-list");
      list.textContent = "";
      res.data.forEach(function (t) {
        var li = document.createElement("li");
        li.textContent = (t.kind === "cli" ? "terminal · " + (t.label || "unnamed") : t.kind.indexOf("mcp") === 0 ? "an AI client" : "this site") +
          " — until " + when(t.expires_at);
        list.appendChild(li);
      });
    });
  }

  /* ------------------------------------------------------------ an MCP client's request */

  function authorizeStep() {
    show("acct-signin", false);
    call("GET", "/oauth/requests/" + encodeURIComponent(requestId())).then(function (res) {
      if (res.status !== 200) {
        message(detail(res, "This request has expired; start again from the client."), true);
        return;
      }
      $("auth-client").textContent = res.data.client_name;
      $("auth-client-uri").textContent = res.data.client_uri || res.data.client_id;
      $("auth-what").textContent = "It will be able to " + res.data.allows + ".";
      $("auth-back").textContent = "Your browser then goes back to " + res.data.redirect_host + ".";
      show("acct-authorize", true);
    });
  }

  function decide(allow) {
    call("POST", "/oauth/approve", { request: requestId(), allow: allow }).then(function (res) {
      if (res.status === 200 && res.data.redirect) {
        message(allow ? "Allowed — returning to the client." : "Denied — returning to the client.", false);
        show("acct-authorize", false);
        location.assign(res.data.redirect);
      } else if (res.status === 401) {
        keep("", false); signedOut();
      } else {
        message(detail(res, "That did not work; start again from the client."), true);
      }
    });
  }

  /* ------------------------------------------------------------ wiring */

  function afterSignIn() {
    show("acct-signin", false);
    paintNav(true);
    if (page === "authorize") { authorizeStep(); return; }
    loadIdentity().then(function (ok) { if (ok) return loadProfile().then(loadTokens); });
  }

  function init() {
    if (!api) { show("acct-offline", true); return; }
    $("acct-github-go").addEventListener("click", signIn);

    var claim = $("claim-form");
    if (claim) claim.addEventListener("submit", function (e) {
      e.preventDefault();
      call("POST", "/me", { nick: claim.nick.value.toLowerCase(), country: claim.country.value.toUpperCase() })
        .then(function (res) {
          if (res.status === 201) { message("That nick is yours.", false); loadProfile(); }
          else message(detail(res, "That nick cannot be used."), true);
        });
    });

    var move = $("country-form");
    if (move) move.addEventListener("submit", function (e) {
      e.preventDefault();
      call("POST", "/me", { country: move.country.value.toUpperCase() }).then(function (res) {
        if (res.status === 201) { message("Your country is " + res.data.country + ".", false); loadProfile(); }
        else message(detail(res, "That country cannot be used."), true);
      });
    });

    if ($("auth-allow")) {
      $("auth-allow").addEventListener("click", function () { decide(true); });
      $("auth-deny").addEventListener("click", function () { decide(false); });
    }

    if ($("discord-connect-go")) {
      $("discord-connect-go").addEventListener("click", function () {
        call("POST", "/auth/discord/start", { join: $("discord-join").checked }).then(function (res) {
          if (res.status === 200 && res.data.url) location.assign(res.data.url);
          else message(detail(res, "Discord cannot be linked right now."), true);
        }).catch(function () { show("acct-offline", true); });
      });
      $("discord-disconnect").addEventListener("click", function () {
        call("DELETE", "/auth/discord").then(function (res) {
          if (res.status !== 200) { message(detail(res, "That did not work."), true); return; }
          identity.discord.linked = false;
          identity.discord.error = "";
          identity.digest = false;
          paintDiscord();
          message("Discord is unlinked, and the weekly digest is off.", false);
        });
      });
      var digest = $("digest-on");
      digest.addEventListener("change", function () {
        var wanted = digest.checked;
        call("PUT", "/auth/preferences", { digest: wanted }).then(function (res) {
          if (res.status !== 200) {
            digest.checked = !wanted;
            message(detail(res, "That did not save; try again."), true);
            return;
          }
          identity.digest = wanted;
          message(wanted ? "The weekly digest is on." : "The weekly digest is off.", false);
        }).catch(function () { digest.checked = !wanted; show("acct-offline", true); });
      });
    }

    $("acct-signout").addEventListener("click", function () {
      call("POST", "/auth/logout").then(function () {
        keep("", false);
        message("Signed out on this browser.", false);
        signedOut();
      });
    });

    fromFragment().then(function () {
      if (token()) afterSignIn(); else signedOut();
    }).catch(function () { show("acct-offline", true); signedOut(); });
  }

  init();
})();
