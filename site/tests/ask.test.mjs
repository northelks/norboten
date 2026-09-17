/* The in-browser consultant fallback: the tokenizer and BM25 must agree with the API's.
 *
 * Run with:  node site/tests/ask.test.mjs
 *
 * The expected tokens are what api/src/norboten_api/retrieval.py produces for the same strings;
 * if one side changes, this is where they drift apart.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
globalThis.window = globalThis;
new Function(readFileSync(join(here, "..", "static", "ask-engine.js"), "utf8"))();
const { tokenize, expand, Index, excerpt } = globalThis.NorbotenAsk;

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
function equal(a, b) {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error(`${x} !== ${y}`);
}

check("tokens match the Python tokenizer", () => {
  equal(tokenize("How is a lab graded?"), ["lab", "graded"]);
  equal(tokenize("Use lvextend -r on /dev/vg0/app"), ["use", "lvextend", "-r", "/dev/vg0/app"]);
  equal(tokenize("ss -tlnp | grep 8090"), ["ss", "-tlnp", "grep", "8090"]);
  equal(tokenize("The SELinux boolean"), ["selinux", "boolean"]);
});

const passages = [
  { id: "a", title: "Grading", url: "/docs/lab-spec/", text: "A lab is graded by checks that run in the guest, then the machine reboots and the checks run again." },
  { id: "b", title: "Storage", url: "/journals/rhcsa-03/", text: "Grow the logical volume with lvextend -r and mount it by UUID in fstab." },
  { id: "c", title: "Ratings", url: "/docs/architecture/", text: "Ratings are Glicko-2, one per topic, with a rating deviation." },
];

check("the passage that holds the terms ranks first", () => {
  const index = new Index(passages);
  equal(index.search("how is a lab graded", 3).map((h) => h.passage.id), ["a"]);
  equal(index.search("lvextend uuid", 3)[0].passage.id, "b");
  equal(index.search("the and of", 3), []);
});

check("a rarer term outweighs a common one", () => {
  const index = new Index(passages.concat([{ id: "d", title: "Checks", url: "/", text: "checks checks checks" }]));
  const top = index.search("checks reboots", 2).map((h) => h.passage.id);
  equal(top[0], "a");
});

check("a synonym finds the passage at half weight, and an exact word still wins", () => {
  const synonyms = [["container", "containers", "docker"]];
  const weights = expand(["docker", "lab"], {});
  equal(weights, { docker: 1, lab: 1 });
  const index = new Index(
    passages.concat([
      { id: "e", title: "Containers", url: "/", text: "A lab in a container shares the host kernel." },
      { id: "f", title: "Docker", url: "/", text: "Docker labs run inside the VM." },
    ]),
    synonyms,
  );
  equal(index.search("docker", 3).map((h) => h.passage.id), ["f", "e"]);
  equal(expand(["docker"], index.synonymsOf), { docker: 1, container: 0.5, containers: 0.5 });
});

check("an excerpt quotes the sentence that answers", () => {
  const text = "Norboten boots a VM. The reboot check runs every check twice. Nothing else matters.";
  const out = excerpt(text, "reboot check", 200);
  if (!out.includes("The reboot check runs every check twice.")) throw new Error(out);
  if (out.includes("boots a VM")) throw new Error("quoted a sentence with no query term: " + out);
});

if (failures) {
  console.log(`\n${failures} failing`);
  process.exit(1);
}
console.log("\nall ask checks pass");
