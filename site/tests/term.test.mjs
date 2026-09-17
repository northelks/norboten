/* The terminal emulator, checked against the recordings the site actually ships.
 *
 * Run with:  node site/tests/term.test.mjs
 *
 * player.js is a browser file with no module system, so it is loaded by evaluating it against a
 * minimal document stub — the same way the browser does, minus the browser.
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const site = join(here, "..");

/* The smallest document player.js needs to load: it only touches these on mount. */
const noop = () => {};
function element() {
  return {
    className: "", style: {}, dataset: {}, textContent: "", title: "", type: "",
    children: [],
    appendChild(child) { this.children.push(child); return child; },
    addEventListener: noop,
    classList: { add: noop, toggle: noop, remove: noop },
  };
}
const stub = {
  readyState: "complete",
  addEventListener: noop,
  querySelectorAll: () => [],
  querySelector: () => null,
  createElement: element,
  getElementById: () => null,
};
globalThis.document = stub;
globalThis.window = globalThis;
globalThis.requestAnimationFrame = noop;
globalThis.fetch = () => Promise.reject(new Error("not in this test"));

const source = readFileSync(join(site, "static", "player.js"), "utf8");
new Function(source)();
const { Term, Player, timeline } = globalThis.NorbotenTerm;

let failures = 0;
function check(name, fn) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name}\n     ${e.message}`);
  }
}
function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

function screen(term) {
  return term.toHtml().replace(/<[^>]+>/g, "");
}

check("plain text lands on the screen", () => {
  const t = new Term(20, 3);
  t.write("hello");
  assert(screen(t).startsWith("hello"), screen(t));
});

check("a carriage return overwrites the line, as a progress bar does", () => {
  const t = new Term(20, 2);
  t.write("50%\r100%");
  assert(screen(t).split("\n")[0].trim() === "100%", JSON.stringify(screen(t)));
});

check("a terminal is never smaller than something you could read", () => {
  const t = new Term(4, 1);
  assert(t.cols === 20 && t.rows === 5, `${t.cols}x${t.rows}`);
});

check("newlines scroll when the screen is full", () => {
  const t = new Term(20, 5);
  t.write("one\ntwo\nthree\nfour\nfive\nsix");
  const lines = screen(t).split("\n").map((l) => l.trim());
  assert(lines.length === 5, JSON.stringify(lines));
  assert(lines[0] === "two" && lines[4] === "six", JSON.stringify(lines));
});

check("wrapping at the right margin", () => {
  const t = new Term(20, 5);
  t.write("x".repeat(25));
  const lines = screen(t).split("\n").map((l) => l.trimEnd());
  assert(lines[0] === "x".repeat(20), JSON.stringify(lines[0]));
  assert(lines[1] === "x".repeat(5), JSON.stringify(lines[1]));
});

check("erase-in-line clears to the end", () => {
  const t = new Term(10, 1);
  t.write("abcdefgh\x1b[5G\x1b[K");
  assert(screen(t).trim() === "abcd", JSON.stringify(screen(t)));
});

check("erase-in-display clears everything", () => {
  const t = new Term(10, 2);
  t.write("abc\ndef\x1b[2J");
  assert(screen(t).trim() === "", JSON.stringify(screen(t)));
});

check("cursor positioning writes where it is told", () => {
  const t = new Term(10, 3);
  t.write("\x1b[2;3Hx");
  const lines = screen(t).split("\n");
  assert(lines[1][2] === "x", JSON.stringify(lines));
});

check("colour becomes a span, and reset ends it", () => {
  const t = new Term(20, 1);
  t.write("\x1b[32mgreen\x1b[0m plain");
  const html = t.toHtml();
  assert(html.includes("color:#4ade80"), html);
  assert(html.includes("plain"), html);
});

check("bracketed paste and other private modes are swallowed", () => {
  const t = new Term(20, 1);
  t.write("\x1b[?2004hprompt\x1b[?2004l");
  assert(screen(t).trim() === "prompt", JSON.stringify(screen(t)));
});

check("a window title is not printed", () => {
  const t = new Term(20, 1);
  t.write("\x1b]0;a title\x07visible");
  assert(screen(t).trim() === "visible", JSON.stringify(screen(t)));
});

check("an escape split across two writes still works", () => {
  const t = new Term(20, 1);
  t.write("a\x1b[3");
  t.write("Gb");
  assert(screen(t).trim() === "a b".replace(" ", " "), JSON.stringify(screen(t)));
});

check("html in the output cannot inject markup", () => {
  const t = new Term(40, 1);
  t.write("<script>alert(1)</script>");
  const html = t.toHtml();
  assert(!html.includes("<script>"), html);
  assert(html.includes("&lt;script&gt;"), html);
});

/* ---- the player's controls ---------------------------------------------- */

function recording() {
  const events = [], commands = [];
  for (let i = 0; i < 12; i++) {
    events.push([i * 2 + 1, "o", `$ cmd${i}\r\n`]);
    commands.push({ at: i * 2 + 1, text: `cmd${i}` });
  }
  return { header: { width: 40, height: 10 }, events, commands };
}

check("long pauses are squeezed on the player's clock", () => {
  const clock = timeline([[0, "o", "a"], [0.5, "o", "b"], [30, "o", "c"]]);
  assert(clock[1] === 0.5, JSON.stringify(clock));
  assert(clock[2] < 1.5, JSON.stringify(clock));
});

check("a recording does not play until asked", () => {
  const p = new Player(element(), recording(), {});
  assert(!p.playing && p.t === 0 && p.commandIndex() === -1, `${p.playing} ${p.t}`);
});

check("forward three commands pauses and lands on the third", () => {
  const p = new Player(element(), recording(), {});
  p.play();
  assert(p.playing, "did not start");
  p.skip(3);
  assert(!p.playing, "skipping should pause");
  assert(p.commandIndex() === 2, `at ${p.commandIndex()}`);
  p.skip(3);
  assert(p.commandIndex() === 5, `at ${p.commandIndex()}`);
  assert(screen(p.screen.term).includes("cmd5"), screen(p.screen.term));
});

check("back three commands pauses too, and stop rewinds to nothing", () => {
  const p = new Player(element(), recording(), {});
  p.goToCommand(9);
  p.play();
  p.skip(-3);
  assert(!p.playing && p.commandIndex() === 6, `at ${p.commandIndex()}`);
  assert(!screen(p.screen.term).includes("cmd7"), "the screen shows the future");
  p.stop();
  assert(p.t === 0 && p.commandIndex() === -1 && screen(p.screen.term).trim() === "", "not rewound");
});

check("the table follows the playhead", () => {
  const seen = [];
  const p = new Player(element(), recording(), { onMove: (i) => seen.push(i) });
  p.goToCommand(4);
  p.skip(-3);
  assert(JSON.stringify(seen) === "[4,1]", JSON.stringify(seen));
});

/* ---- the real recordings ------------------------------------------------- */

const streams = join(site, "streams");
const files = readdirSync(streams).filter((f) => f.endsWith(".json"));
assert(files.length > 0, "no recordings to check");

for (const file of files) {
  check(`${file} replays to a sane screen`, () => {
    const data = JSON.parse(readFileSync(join(streams, file), "utf8"));
    const t = new Term(data.header.width, data.header.height);
    for (const event of data.events) if (event[1] === "o") t.write(event[2]);
    const text = screen(t);
    assert(text.length > 0, "empty screen");
    assert(!text.includes("\x1b"), "an escape sequence reached the screen");
    assert(!/\[\?\d+[hl]/.test(text), "a private-mode sequence reached the screen");
    // the last command of every script is followed by output, so the screen cannot be blank
    assert(text.trim().length > 20, JSON.stringify(text.slice(-200)));
  });
}

console.log(failures ? `\n${failures} failed` : `\nall passed`);
process.exit(failures ? 1 : 0);
