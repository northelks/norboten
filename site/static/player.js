/* A terminal player for asciicast v2 recordings, and for live sessions over SSE.
 *
 * There is no dependency here on purpose: the site ships no framework, and a recording of someone
 * fixing a Linux box needs a screen buffer, the escape sequences a shell actually emits, and a
 * clock. That is what this is.
 *
 * What it understands: printable text, \r \n \b \t, CSI cursor moves, erase display/line, SGR
 * colour and attributes, and it skips OSC strings (window titles). A full-screen editor mostly
 * works; anything it does not know is dropped rather than printed as garbage.
 *
 * Usage:
 *   <div class="term" data-cast="streams/rhcsa-03.json"></div>     replay a recording
 *   <div class="term" data-live="https://api…/play/sessions/ID/stream"></div>   follow a session
 */
(function () {
  "use strict";

  var PALETTE = [
    "#0a0e0c", "#f0836c", "#4ade80", "#e8d16c", "#7aa2f7", "#c792ea", "#56c8d8", "#c8d3cd",
    "#4a5651", "#ff9d87", "#6ef0a0", "#ffe484", "#9ec0ff", "#e0b0ff", "#8ae8f5", "#e8ece9"
  ];
  /* Terminal themes: the sixteen colours a recording asks for, per look. The page's CSS sets the
   * ground and default text colour to match (.term[data-theme=…]). */
  var THEMES = {
    green: PALETTE,
    amber: [
      "#140e04", "#ff8f5a", "#ffc861", "#ffd98a", "#f0b25c", "#ff9f7a", "#ffcf7a", "#f2d7a6",
      "#6b5436", "#ffab80", "#ffd88a", "#ffe6b0", "#f5c78a", "#ffbfa0", "#ffe0a8", "#fff1d6"
    ],
    ice: [
      "#07101a", "#ff7b8a", "#6ee7c8", "#f2e38a", "#7cb7ff", "#c3a6ff", "#67d8ef", "#c9d8e8",
      "#3d4f63", "#ff9aa6", "#93f5da", "#fff0a8", "#a3ccff", "#d8c2ff", "#94e8f7", "#eef5fc"
    ],
    violet: [
      "#0e0a16", "#ff7aa8", "#9ef08a", "#ffe08a", "#8aa8ff", "#d49cff", "#7de0e6", "#d6cce6",
      "#4c4260", "#ff9ec0", "#b8f5a8", "#fff0b0", "#aec3ff", "#e6bfff", "#a6eef2", "#f4eefc"
    ]
  };
  var IDLE_CAP = 1.2;   // seconds: a longer pause than this is squeezed
  var IDLE_KEEP = 0.45; // what a squeezed pause becomes

  function Cell(ch, fg, bg, bold) {
    this.ch = ch; this.fg = fg; this.bg = bg; this.bold = bold;
  }

  function Term(cols, rows) {
    this.cols = Math.max(20, Math.min(cols || 80, 400));
    this.rows = Math.max(5, Math.min(rows || 24, 200));
    this.reset();
  }

  Term.prototype.reset = function () {
    this.buf = [];
    for (var y = 0; y < this.rows; y++) this.buf.push(this.blankRow());
    this.x = 0; this.y = 0;
    this.fg = null; this.bg = null; this.bold = false;
    this.pending = "";
  };

  Term.prototype.blankRow = function () {
    var row = [];
    for (var x = 0; x < this.cols; x++) row.push(new Cell(" ", null, null, false));
    return row;
  };

  Term.prototype.scroll = function () {
    this.buf.shift();
    this.buf.push(this.blankRow());
    this.y = this.rows - 1;
  };

  Term.prototype.newline = function () {
    this.y++;
    if (this.y >= this.rows) this.scroll();
  };

  Term.prototype.put = function (ch) {
    if (this.x >= this.cols) { this.x = 0; this.newline(); }
    this.buf[this.y][this.x] = new Cell(ch, this.fg, this.bg, this.bold);
    this.x++;
  };

  Term.prototype.eraseInLine = function (mode) {
    var row = this.buf[this.y];
    var from = mode === 1 ? 0 : this.x;
    var to = mode === 1 ? this.x + 1 : this.cols;
    if (mode === 2) { from = 0; to = this.cols; }
    for (var x = from; x < to && x < this.cols; x++) row[x] = new Cell(" ", null, this.bg, false);
  };

  Term.prototype.eraseInDisplay = function (mode) {
    if (mode === 2 || mode === 3) {
      for (var y = 0; y < this.rows; y++) this.buf[y] = this.blankRow();
      return;
    }
    this.eraseInLine(mode === 1 ? 1 : 0);
    var start = mode === 1 ? 0 : this.y + 1;
    var end = mode === 1 ? this.y : this.rows;
    for (var i = start; i < end; i++) this.buf[i] = this.blankRow();
  };

  Term.prototype.sgr = function (params) {
    if (!params.length) params = [0];
    for (var i = 0; i < params.length; i++) {
      var p = params[i];
      if (p === 0) { this.fg = null; this.bg = null; this.bold = false; }
      else if (p === 1) this.bold = true;
      else if (p === 22) this.bold = false;
      else if (p === 39) this.fg = null;
      else if (p === 49) this.bg = null;
      else if (p >= 30 && p <= 37) this.fg = p - 30;
      else if (p >= 90 && p <= 97) this.fg = p - 90 + 8;
      else if (p >= 40 && p <= 47) this.bg = p - 40;
      else if (p >= 100 && p <= 107) this.bg = p - 100 + 8;
      else if (p === 38 || p === 48) {
        // 256-colour and truecolour: take the nearest of our sixteen, or give up on the rest
        var target = p === 38 ? "fg" : "bg";
        if (params[i + 1] === 5) { this[target] = params[i + 2] % 16; i += 2; }
        else if (params[i + 1] === 2) { this[target] = null; i += 4; }
      }
    }
  };

  Term.prototype.csi = function (body, final) {
    var params = body.replace(/^\?/, "").split(";").map(function (n) {
      return n === "" ? 0 : parseInt(n, 10);
    });
    var n = params[0] || 0;
    switch (final) {
      case "H": case "f":
        this.y = Math.min(this.rows - 1, Math.max(0, (params[0] || 1) - 1));
        this.x = Math.min(this.cols - 1, Math.max(0, (params[1] || 1) - 1));
        break;
      case "A": this.y = Math.max(0, this.y - (n || 1)); break;
      case "B": this.y = Math.min(this.rows - 1, this.y + (n || 1)); break;
      case "C": this.x = Math.min(this.cols - 1, this.x + (n || 1)); break;
      case "D": this.x = Math.max(0, this.x - (n || 1)); break;
      case "G": this.x = Math.min(this.cols - 1, Math.max(0, (n || 1) - 1)); break;
      case "d": this.y = Math.min(this.rows - 1, Math.max(0, (n || 1) - 1)); break;
      case "J": this.eraseInDisplay(n); break;
      case "K": this.eraseInLine(n); break;
      case "L": this.buf.splice(this.y, 0, this.blankRow()); this.buf.length = this.rows; break;
      case "M": this.buf.splice(this.y, 1); this.buf.push(this.blankRow()); break;
      case "m": this.sgr(params); break;
      default: break; // cursor visibility, bracketed paste, alternate screen: ignored
    }
  };

  Term.prototype.write = function (text) {
    var data = this.pending + text;
    this.pending = "";
    var i = 0;
    while (i < data.length) {
      var ch = data[i];
      if (ch === "\x1b") {
        var rest = data.slice(i);
        var csi = /^\x1b\[([0-9;?]*)([A-Za-z@])/.exec(rest);
        if (csi) { this.csi(csi[1], csi[2]); i += csi[0].length; continue; }
        var osc = /^\x1b\][^\x07\x1b]*(\x07|\x1b\\)/.exec(rest);
        if (osc) { i += osc[0].length; continue; }
        var short = /^\x1b[()#][0-9A-Za-z]/.exec(rest) || /^\x1b[=>78Mc]/.exec(rest);
        if (short) { i += short[0].length; continue; }
        if (rest.length < 8) { this.pending = rest; return; }  // split across frames
        i += 1;
        continue;
      }
      if (ch === "\n") { this.newline(); this.x = 0; i++; continue; }
      if (ch === "\r") { this.x = 0; i++; continue; }
      if (ch === "\b") { this.x = Math.max(0, this.x - 1); i++; continue; }
      if (ch === "\t") { this.x = Math.min(this.cols - 1, (Math.floor(this.x / 8) + 1) * 8); i++; continue; }
      if (ch === "\x07" || ch < " ") { i++; continue; }
      this.put(ch);
      i++;
    }
  };

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  Term.prototype.toHtml = function (palette) {
    var colours = palette || PALETTE;
    var out = [];
    for (var y = 0; y < this.rows; y++) {
      var row = this.buf[y], line = [], run = "", cur = null;
      for (var x = 0; x < this.cols; x++) {
        var cell = row[x];
        var key = cell.fg + "/" + cell.bg + "/" + cell.bold;
        if (key !== cur) {
          if (run) line.push(span(run, cur, colours));
          run = ""; cur = key;
        }
        run += cell.ch;
      }
      if (run) line.push(span(run, cur, colours));
      out.push(line.join("").replace(/(\s+)$/, "$1"));
    }
    return out.join("\n");
  };

  function span(text, key, colours) {
    var parts = key.split("/");
    var fg = parts[0] === "null" ? null : parseInt(parts[0], 10);
    var bg = parts[1] === "null" ? null : parseInt(parts[1], 10);
    var bold = parts[2] === "true";
    var style = "";
    if (fg !== null) style += "color:" + colours[fg] + ";";
    if (bg !== null) style += "background:" + colours[bg] + ";";
    if (bold) style += "font-weight:600;";
    var body = escapeHtml(text);
    return style ? '<span style="' + style + '">' + body + "</span>" : body;
  }

  /* ---------------------------------------------------------------- playback */

  function Screen(el, cols, rows, theme) {
    this.el = el;
    this.palette = THEMES[theme] || PALETTE;
    this.term = new Term(cols, rows);
    this.pre = document.createElement("pre");
    this.pre.className = "termscreen";
    this.el.appendChild(this.pre);
    this.dirty = true;
    var self = this;
    this.tick = function () {
      if (self.dirty) { self.pre.innerHTML = self.term.toHtml(self.palette); self.dirty = false; }
      requestAnimationFrame(self.tick);
    };
    requestAnimationFrame(this.tick);
  }

  Screen.prototype.write = function (text) {
    this.term.write(text);
    this.dirty = true;
  };

  Screen.prototype.resize = function (cols, rows) {
    if (cols === this.term.cols && rows === this.term.rows) return;
    this.term = new Term(cols, rows);
    this.dirty = true;
  };

  Screen.prototype.clear = function () {
    this.term = new Term(this.term.cols, this.term.rows);
    this.dirty = true;
  };

  /* The recording's clock with long pauses squeezed: nobody wants to watch someone think. */
  function timeline(events) {
    var out = [], previous = 0, clock = 0;
    for (var i = 0; i < events.length; i++) {
      var gap = Math.max(0, events[i][0] - previous);
      previous = events[i][0];
      clock += gap > IDLE_CAP ? IDLE_KEEP : gap;
      out.push(clock);
    }
    return out;
  }

  /* Where an original timestamp falls on the squeezed clock. */
  function squeeze(events, clock, at) {
    var lo = 0, hi = events.length - 1, best = -1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (events[mid][0] <= at) { best = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    if (best < 0) return 0;
    return clock[best] + Math.min(at - events[best][0], IDLE_CAP);
  }

  var SKIP = 3;

  /* A recording with controls: play/pause, stop, and the next three commands.
   * Skipping pauses — you skipped to look at something. */
  function Player(el, data, options) {
    options = options || {};
    var header = data.header || data;
    this.events = data.events || [];
    this.clock = timeline(this.events);
    var self = this;
    this.commands = (data.commands || []).map(function (c) {
      return { text: c.text, t: squeeze(self.events, self.clock, c.at) };
    });
    this.duration = this.clock.length ? this.clock[this.clock.length - 1] : 0;
    this.loop = !!options.loop;
    this.onMove = options.onMove || null;
    this.t = 0;
    this.i = 0;
    this.playing = false;
    this.timer = null;
    this.lastCommand = -1;

    el.classList.add("has-player");
    this.wall = options.controls === "wall" || options.controls === "view";
    this.onExpand = options.controls === "wall" ? (options.onExpand || null) : null;
    this.onLogs = options.onLogs || null;
    if (this.wall) this.bar = this.buildWallBar(el);
    else if (options.controls !== false) this.bar = this.buildBar(el);
    var body = document.createElement("div");
    body.className = "termbody";
    el.appendChild(body);
    this.screen = new Screen(body, header.width, header.height, el.dataset.theme);
    this.status();
    if (options.autoplay) this.play();
  }

  Player.prototype.buildBar = function (el) {
    var self = this;
    var bar = document.createElement("div");
    bar.className = "termbar";
    function button(label, title, fn) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.title = title;
      b.addEventListener("click", fn);
      bar.appendChild(b);
      return b;
    }
    this.playButton = button("▶ Play", "Play or pause", function () { self.toggle(); });
    this.stopButton = button("■ Stop", "Stop and rewind", function () { self.stop(); });
    this.nextButton = button("next " + SKIP + " cmd", "Forward " + SKIP + " commands (pauses)", function () { self.skip(SKIP); });
    this.label = document.createElement("span");
    this.label.className = "termstatus";
    bar.appendChild(this.label);
    if (this.onLogs) {
      var logs = iconButton("logs", "Every command, and how long each took",
        '<path d="M3 4h10M3 8h10M3 12h6" fill="none" stroke="currentColor" stroke-width="1.6" ' +
        'stroke-linecap="round"/>');
      logs.classList.add("logs");
      logs.addEventListener("click", function () { self.onLogs(self); });
      bar.appendChild(logs);
    }
    el.appendChild(bar);
    return bar;
  };

  /* A small bordered button with an icon, the way the wall's expand is drawn. */
  function iconButton(label, title, path) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "expand";
    b.title = title;
    b.innerHTML = '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">' + path +
      '</svg><span>' + label + '</span>';
    return b;
  }

  /* The wall has no transport: these four play by themselves. What it shows is how far in the
   * session is — the clock and the commands that have run — and a way to open it big. The big view
   * ("view") is the same terminal and the same bar, without the way to open it big. */
  Player.prototype.buildWallBar = function (el) {
    var self = this;
    var bar = document.createElement("div");
    bar.className = "termbar wallbar";
    this.label = document.createElement("span");
    this.label.className = "termstatus";
    bar.appendChild(this.label);
    if (this.onExpand) {
      var expand = iconButton("expand", "Open this session in a large view",
        '<path d="M6 2H2v4M10 14h4v-4M14 6V2h-4M2 10v4h4" fill="none" stroke="currentColor" ' +
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>');
      expand.addEventListener("click", function () { self.onExpand(self); });
      bar.appendChild(expand);
    }
    el.appendChild(bar);
    return bar;
  };

  function clockText(seconds) {
    seconds = Math.max(0, Math.floor(seconds));
    return Math.floor(seconds / 60) + ":" + ("0" + (seconds % 60)).slice(-2);
  }

  Player.prototype.commandIndex = function () {
    var idx = -1;
    for (var k = 0; k < this.commands.length; k++) {
      if (this.commands[k].t <= this.t + 1e-6) idx = k; else break;
    }
    return idx;
  };

  Player.prototype.status = function () {
    var idx = this.commandIndex();
    if (idx !== this.lastCommand) {
      this.lastCommand = idx;
      if (this.onMove) this.onMove(idx);
    }
    if (!this.bar) return;
    if (this.wall) {
      var n = idx + 1;
      this.label.textContent = clockText(this.t) + "  ·  " + n + " cmd";
      return;
    }
    this.playButton.textContent = this.playing ? "⏸ Pause" : (this.i >= this.events.length && this.events.length ? "↺ Again" : "▶ Play");
    this.label.textContent = clockText(this.t) + " / " + clockText(this.duration) +
      "  ·  command " + (idx + 1) + "/" + this.commands.length;
  };

  Player.prototype.step = function () {
    var self = this;
    this.timer = null;
    if (!this.playing) return;
    if (this.i >= this.events.length) {
      this.playing = false;
      this.status();
      if (this.loop) {
        this.timer = setTimeout(function () { self.rewind(); self.play(); }, 4000);
      }
      return;
    }
    var wait = Math.max(0, this.clock[this.i] - this.t);
    this.timer = setTimeout(function () {
      if (!self.playing) return;
      var event = self.events[self.i];
      self.t = self.clock[self.i];
      if (event[1] === "o") self.screen.write(event[2]);
      self.i++;
      self.status();
      self.step();
    }, wait * 1000);
  };

  /* Before the first play the screen is not empty and not playing either: it lists the commands
   * this session is about to run, dimmed, so a paused terminal still says something. */
  Player.prototype.preview = function (el, limit) {
    if (!this.commands.length) return;
    var lines = this.commands.slice(0, limit || 20).map(function (c) { return "$ " + c.text; });
    if (this.commands.length > lines.length) {
      lines.push("… " + (this.commands.length - lines.length) + " more");
    }
    this.screen.write("\r\n" + lines.join("\r\n") + "\r\n");
    this.previewing = true;
    this.el = el;
    el.classList.add("is-preview");
  };

  Player.prototype.clearPreview = function () {
    if (!this.previewing) return;
    this.previewing = false;
    if (this.el) this.el.classList.remove("is-preview");
    this.rewind();
  };

  Player.prototype.play = function () {
    if (this.playing) return;
    this.clearPreview();
    if (this.i >= this.events.length) this.rewind();
    this.playing = true;
    this.status();
    this.step();
  };

  Player.prototype.pause = function () {
    this.playing = false;
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    this.status();
  };

  Player.prototype.toggle = function () {
    if (this.playing) this.pause(); else this.play();
  };

  Player.prototype.rewind = function () {
    this.t = 0;
    this.i = 0;
    this.screen.clear();
  };

  Player.prototype.stop = function () {
    this.pause();
    this.rewind();
    this.status();
  };

  /* Put the screen exactly where the recording was at squeezed time `t`. */
  Player.prototype.seek = function (t) {
    if (t < this.t) this.rewind();
    while (this.i < this.events.length && this.clock[this.i] <= t) {
      var event = this.events[this.i];
      if (event[1] === "o") this.screen.term.write(event[2]);
      this.i++;
    }
    this.t = t;
    this.screen.dirty = true;
    this.status();
  };

  Player.prototype.goToCommand = function (index) {
    if (!this.commands.length) return;
    this.clearPreview();
    index = Math.max(0, Math.min(this.commands.length - 1, index));
    this.pause();
    // just past the command's own echo, so the line that was typed is on screen
    this.seek(this.commands[index].t + 0.05);
  };

  Player.prototype.skip = function (delta) {
    this.goToCommand(this.commandIndex() + delta);
  };

  /* ---------------------------------------------------------- the big view */

  function modal() {
    var node = document.getElementById("termmodal");
    if (node) return node;
    node = document.createElement("div");
    node.className = "modal";
    node.id = "termmodal";
    node.hidden = true;
    node.innerHTML = '<div class="modal-card" role="dialog" aria-modal="true">' +
      '<header><div><div class="kicker">Session</div><h2></h2>' +
      '<p class="muted mono small"></p></div>' +
      '<button type="button" class="modal-close" aria-label="Close">×</button></header>' +
      '<div class="modal-body"></div></div>';
    document.body.appendChild(node);
    function close() {
      var player = node.norbotenPlayer;
      if (player) player.pause();
      node.hidden = true;
      var body = node.querySelector(".modal-body");
      if (node.returnTo) {  // borrowed content goes back where it came from, listeners and all
        while (body.firstChild) node.returnTo.appendChild(body.firstChild);
        node.returnTo = null;
      }
      body.innerHTML = "";
      node.norbotenPlayer = null;
    }
    node.querySelector(".modal-close").addEventListener("click", close);
    node.addEventListener("click", function (e) { if (e.target === node) close(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !node.hidden) close();
    });
    return node;
  }

  function expandInto(data, options) {
    var node = modal();
    node.querySelector(".modal-card .kicker").textContent = "Session";
    node.querySelector("h2").textContent = options.title || "Session";
    node.querySelector(".modal-card header p").textContent = options.meta || "";
    var body = node.querySelector(".modal-body");
    body.innerHTML = "";
    var term = document.createElement("div");
    term.className = "term";
    term.dataset.theme = options.theme || "green";
    body.appendChild(term);
    node.hidden = false;
    var player = new Player(term, data, { controls: "view", loop: true });
    if (options.at) player.seek(options.at);  // the same terminal, where the small one is
    player.play();
    node.norbotenPlayer = player;
    node.querySelector(".modal-close").focus();
  }

  /* A recording's command list, in the same dialog: the table is lent to it and given back on
   * close, so a click on a command still moves the player on the page. */
  function showCommands(holder, title, subtitle) {
    var node = modal();
    node.querySelector(".modal-card .kicker").textContent = "Logs";
    node.querySelector("h2").textContent = title || "";
    node.querySelector(".modal-card header p").textContent = subtitle || "";
    var body = node.querySelector(".modal-body");
    body.innerHTML = "";
    while (holder.firstChild) body.appendChild(holder.firstChild);
    node.returnTo = holder;
    node.hidden = false;
    node.querySelector(".modal-close").focus();
  }

  /* ---------------------------------------------------------------- wiring */

  function mount(el) {
    if (el.dataset.mounted) return el.norbotenPlayer;
    el.dataset.mounted = "1";
    var cast = el.dataset.cast, liveUrl = el.dataset.live;
    var label = el.querySelector(".termlabel");

    if (cast) {
      fetch(cast).then(function (r) { return r.json(); }).then(function (data) {
        var autoplay = el.dataset.autoplay;
        var table = el.dataset.commands ? document.querySelector(el.dataset.commands) : null;
        var rows = table ? table.querySelectorAll("tr[data-command]") : [];
        var controls = el.dataset.controls === "none" ? false :
          (el.dataset.controls === "wall" ? "wall" : true);
        var player = new Player(el, data, {
          autoplay: autoplay === "loop" || autoplay === "once",
          loop: autoplay === "loop",
          controls: controls,
          onLogs: el.dataset.logs ? function () {
            var holder = document.querySelector(el.dataset.logs);
            if (holder) showCommands(holder, el.dataset.title, holder.dataset.subtitle);
          } : null,
          onExpand: function (small) {
            expandInto(data, {
              at: small.t,
              title: el.dataset.title || (data.title || ""),
              meta: el.dataset.meta || "",
              theme: el.dataset.theme
            });
          },
          onMove: function (idx) {
            for (var k = 0; k < rows.length; k++) {
              rows[k].classList.toggle("current", k === idx);
            }
          }
        });
        el.norbotenPlayer = player;
        if (!autoplay && controls === true) player.preview(el, 20);
        for (var k = 0; k < rows.length; k++) {
          (function (n) {
            rows[n].addEventListener("click", function () { player.goToCommand(n); });
          })(k);
        }
      }).catch(function () {
        var failed = document.createElement("pre");
        failed.className = "termscreen";
        failed.textContent = "\n  this recording could not be loaded\n";
        el.appendChild(failed);
      });
      return null;
    }

    if (liveUrl) {
      var screen = new Screen(el, parseInt(el.dataset.cols || "100", 10),
                              parseInt(el.dataset.rows || "28", 10), el.dataset.theme);
      var source = new EventSource(liveUrl);
      source.addEventListener("header", function (e) {
        var header = JSON.parse(e.data);
        screen.resize(header.width, header.height);
      });
      source.addEventListener("batch", function (e) {
        var batch = JSON.parse(e.data);
        (batch.events || []).forEach(function (event) {
          if (event[1] === "o") screen.write(event[2]);
        });
      });
      source.addEventListener("end", function () {
        source.close();
        if (label) label.textContent = "session ended";
      });
      source.onerror = function () {
        if (label) label.textContent = "reconnecting…";
      };
    }
    return null;
  }

  function init() {
    document.querySelectorAll("[data-cast], [data-live]").forEach(mount);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.NorbotenTerm = { Term: Term, Screen: Screen, Player: Player, timeline: timeline, mount: mount,
    expand: expandInto, THEMES: THEMES };
})();
