// The everyday tools on the phone: wording, time maths, file kinds, and what Home offers and does. Run with:  node tests/js/daily_test.js   (pytest runs it too)
const assert = require("assert");
const D = require("../../src/handoff/web/daily.js");

const run = [];
function test(name, fn) { try { fn(); run.push([name, true]); } catch (e) { run.push([name, false, e]); } }
const asyncTests = [];
function atest(name, fn) { asyncTests.push(fn().then(() => run.push([name, true]), (e) => run.push([name, false, e]))); }
const later = (ms = 25) => new Promise((resolve) => setTimeout(resolve, ms));

const NOW = new Date(2026, 4, 4, 14, 30, 0).getTime() / 1000;   // Mon 4 May 2026, 2:30 pm, in whatever zone this runs in

/* ---------------------------------------------------------------- the pure functions */

test("sizes are said in plain units", () => {
  assert.strictEqual(D.sizeText(0), "0 B");
  assert.strictEqual(D.sizeText(2048), "2 KB");
  assert.strictEqual(D.sizeText(1.5 * 1024 * 1024), "1.5 MB");
  assert.strictEqual(D.sizeText(50 * 1024 * 1024), "50 MB");
  assert.strictEqual(D.sizeText(3 * 1024 ** 3), "3.0 GB");
  assert.strictEqual(D.sizeText(-5), "0 B");
  assert.strictEqual(D.sizeText("x"), "0 B");
});

test("a time says today, tomorrow or the day", () => {
  assert.strictEqual(D.whenText(NOW + 3 * 3600, NOW), "today 5:30 pm");
  assert.strictEqual(D.whenText(new Date(2026, 4, 5, 8, 0).getTime() / 1000, NOW), "tomorrow 8:00 am");
  assert.strictEqual(D.whenText(new Date(2026, 4, 9, 0, 5).getTime() / 1000, NOW), "Sat 9 May, 12:05 am");
  assert.strictEqual(D.whenText(new Date(2026, 4, 4, 12, 0).getTime() / 1000, NOW), "today 12:00 pm");
});

test("how long ago is said in small words", () => {
  assert.strictEqual(D.agoText(NOW - 5, NOW), "just now");
  assert.strictEqual(D.agoText(NOW - 600, NOW), "10 min ago");
  assert.strictEqual(D.agoText(NOW - 7200, NOW), "2 h ago");
  assert.strictEqual(D.agoText(NOW - 3 * 86400, NOW), "3 d ago");
  assert.strictEqual(D.agoText(NOW + 50, NOW), "just now");
});

test("how long until a time is said as a countdown", () => {
  assert.strictEqual(D.inText(NOW + 10, NOW), "now");
  assert.strictEqual(D.inText(NOW - 500, NOW), "now");
  assert.strictEqual(D.inText(NOW + 12 * 60, NOW), "in 12 min");
  assert.strictEqual(D.inText(NOW + 3600, NOW), "in 1 h");
  assert.strictEqual(D.inText(NOW + 2 * 3600 + 14 * 60, NOW), "in 2 h 14 m");
  assert.strictEqual(D.inText(NOW + 30 * 3600, NOW), "in 1 day");
  assert.strictEqual(D.inText(NOW + 3 * 86400, NOW), "in 3 days");
});

test("an upload's speed and time left are said simply", () => {
  assert.strictEqual(D.speedText(500 * 1024), "500 KB/s");
  assert.strictEqual(D.speedText(2.5 * 1024 * 1024), "2.5 MB/s");
  assert.strictEqual(D.speedText(-1), "0 KB/s");
  assert.strictEqual(D.etaText(2), "a few seconds left");
  assert.strictEqual(D.etaText(40), "40 s left");
  assert.strictEqual(D.etaText(61), "2 min left");
  assert.strictEqual(D.etaText(Infinity), "");
  assert.strictEqual(D.etaText(-3), "");
});

test("progress is a whole percent between 0 and 100", () => {
  assert.strictEqual(D.percent(0, 100), 0);
  assert.strictEqual(D.percent(50, 200), 25);
  assert.strictEqual(D.percent(300, 200), 100);
  assert.strictEqual(D.percent(5, 0), 0);
  assert.strictEqual(D.percent(-5, 100), 0);
});

test("how long a PC has been up", () => {
  assert.strictEqual(D.uptimeText(20 * 60), "20 min");
  assert.strictEqual(D.uptimeText(5 * 3600), "5 h");
  assert.strictEqual(D.uptimeText(5 * 3600 + 20 * 60), "5 h 20 m");
  assert.strictEqual(D.uptimeText(3 * 86400 + 4 * 3600), "3 d 4 h");
  assert.strictEqual(D.uptimeText(0), "1 min");
});

test("ready-made times are all in the future and in order", () => {
  const q = D.quickTimes(NOW);
  assert.ok(q.length >= 3);
  q.forEach((t) => assert.ok(t.ts > NOW, t.label));
  assert.deepStrictEqual(q.map((t) => t.ts), [...q.map((t) => t.ts)].sort((a, b) => a - b));
  assert.strictEqual(q[0].label, "In 10 min");
  assert.ok(q.some((t) => t.label === "This evening" && D.whenText(t.ts, NOW) === "today 6:00 pm"));
  assert.ok(q.some((t) => t.label === "Tomorrow 8 am" && D.whenText(t.ts, NOW) === "tomorrow 8:00 am"));
});

test("this evening is not offered when it is nearly evening already", () => {
  const late = new Date(2026, 4, 4, 17, 55, 0).getTime() / 1000;
  assert.ok(!D.quickTimes(late).some((t) => t.label === "This evening"));
  const night = new Date(2026, 4, 4, 22, 0, 0).getTime() / 1000;
  assert.ok(!D.quickTimes(night).some((t) => t.label === "This evening"));
});

test("the date box value and seconds convert both ways", () => {
  assert.strictEqual(D.tsToInput(D.inputToTs("2026-05-04T21:30")), "2026-05-04T21:30");
  assert.strictEqual(D.inputToTs("2026-05-04T21:30"), new Date(2026, 4, 4, 21, 30).getTime() / 1000);
  ["", null, undefined, "tomorrow", "2026-05-04", "2026-13-40T99:99", "2026-02-31T10:00", "2026-05-04T25:00"].forEach((bad) => assert.strictEqual(D.inputToTs(bad), null, String(bad)));
});

test("repeat and power actions have plain names", () => {
  assert.strictEqual(D.repeatText("daily"), "Every day");
  assert.strictEqual(D.repeatText("weekdays"), "Weekdays");
  assert.strictEqual(D.repeatText(""), "");
  assert.strictEqual(D.powerText("sleep"), "Put this PC to sleep");
  assert.strictEqual(D.powerText("mystery"), "mystery");
  assert.strictEqual(D.powerShort("screen_off"), "Screen off");
  assert.strictEqual(D.powerShort("mystery"), "mystery");
});

test("a task or watcher reads as one line", () => {
  assert.strictEqual(D.taskText({ kind: "remind", text: "call mum" }), "call mum");
  assert.strictEqual(D.taskText({ kind: "power", action: "lock" }), "Lock this PC");
  assert.strictEqual(D.watchText({ label: "render.exe to finish", then: "" }), "render.exe to finish");
  assert.strictEqual(D.watchText({ label: "render.exe to finish", then: "sleep" }), "render.exe to finish · then put this pc to sleep");
});

test("only documents and pictures count as printable", () => {
  ["a.pdf", "B.DOCX", "x.y.png", "sheet.xlsx", "notes.txt"].forEach((n) => assert.ok(D.printable(n), n));
  ["setup.exe", "run.ps1", "noext", "", "a.html", "script.bat", "archive.zip"].forEach((n) => assert.ok(!D.printable(n), n));
});

test("every file is sorted into a kind, for its icon and colour", () => {
  const cases = { "photo.JPG": "image", "clip.mp4": "video", "song.mp3": "audio", "ticket.pdf": "pdf", "letter.docx": "doc", "notes.txt": "doc", "budget.xlsx": "sheet",
    "deck.pptx": "slides", "backup.zip": "archive", "app.py": "code", "setup.exe": "file", "README": "file", "": "file", "archive.tar.gz": "archive" };
  Object.entries(cases).forEach(([name, kind]) => assert.strictEqual(D.kindOf(name, false), kind, name));
  assert.strictEqual(D.kindOf("anything.jpg", true), "folder");
  assert.strictEqual(D.kindOf("Downloads", true), "folder");
  assert.strictEqual(D.kindOf("constructor", false), "file");   // not fooled by names that are also JavaScript words
});

test("notes are grouped by day in the order they came", () => {
  const groups = D.groupNotes([{ date: "2026-05-04", text: "b" }, { date: "2026-05-04", text: "a" }, { date: "2026-05-03", text: "z" }]);
  assert.deepStrictEqual(groups.map((g) => [g.date, g.items.map((n) => n.text)]), [["2026-05-04", ["b", "a"]], ["2026-05-03", ["z"]]]);
  assert.deepStrictEqual(D.groupNotes(null), []);
});

test("a day heading says today, yesterday or the date", () => {
  assert.strictEqual(D.dayText("2026-05-04", NOW), "Today");
  assert.strictEqual(D.dayText("2026-05-03", NOW), "Yesterday");
  assert.strictEqual(D.dayText("2026-04-28", NOW), "Tue 28 Apr");
  assert.strictEqual(D.dayText("junk", NOW), "junk");
});

test("an error says what the PC said, or something kind", () => {
  assert.strictEqual(D.errorText(new Error("The screen is blacked out.")), "The screen is blacked out.");
  assert.strictEqual(D.errorText(null), "That didn't work.");
  assert.strictEqual(D.errorText({}), "That didn't work.");
});

/* ---------------------------------------------------------------- a small stand-in for the page, so Home can be driven without a browser */

const flat = (kids) => kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false);
const drawnIcons = new Set();   // every icon name the tools ask for, so each can be checked against the page's own icon set
class Node_ {
  constructor(tag, props, kids) {
    this.tag = tag; this.props = props || {}; this.kids = kids || []; this.parent = null; this.attrs = {}; this.listeners = {}; this.filled = null;
    this.kids.forEach((k) => { if (k instanceof Node_) k.parent = this; });
    this.classes = new Set(String(this.props.class || "").split(/\s+/).filter(Boolean));
    this.classList = {
      add: (...c) => c.forEach((x) => this.classes.add(x)), remove: (...c) => c.forEach((x) => this.classes.delete(x)),
      contains: (c) => this.classes.has(c), toggle: (c, force) => { const on = force === undefined ? !this.classes.has(c) : !!force; on ? this.classes.add(c) : this.classes.delete(c); return on; },
    };
    this.styleProps = {}; this.style = { setProperty: (k, v) => { this.styleProps[k] = v; } };
    this.textContent = this.props.text || ""; this.hidden = !!this.props.hidden; this.value = this.props.value !== undefined ? String(this.props.value) : ""; this.disabled = false;
    Object.keys(this.props).forEach((k) => { if (k.startsWith("on") && typeof this.props[k] === "function") this.addEventListener(k.slice(2), this.props[k]); });
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  fire(type, event = {}) { (this.listeners[type] || []).forEach((fn) => fn({ currentTarget: this, target: this, preventDefault() {}, stopPropagation() {}, ...event })); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : (k in this.props ? String(this.props[k]) : null); }
  get firstChild() { return this.kids[0] || null; }
  get childNodes() { return this.kids; }
  replaceChildren(...kids) { this.filled = kids; this.kids = flat(kids); this.kids.forEach((k) => { if (k instanceof Node_) k.parent = this; }); }
  append(...kids) { this.kids.push(...flat(kids)); }
  replaceWith(node) { if (this.parent) { const i = this.parent.kids.indexOf(this); if (i >= 0) { this.parent.kids[i] = node; node.parent = this.parent; } } }
  all(out = []) { out.push(this); this.kids.forEach((k) => k instanceof Node_ && k.all(out)); return out; }
  find(fn) { return this.all().find(fn) || null; }
  querySelector(sel) {
    const badge = /^\[data-badge="(.+)"\]$/.exec(sel);
    if (badge) return this.all().find((n) => n.props["data-badge"] === badge[1]) || null;
    const cls = /^\.([\w-]+)$/.exec(sel);
    return cls ? this.all().find((n) => n.classes.has(cls[1])) || null : null;
  }
}

function rig(daily, answers = {}, opts = {}) {
  const calls = [], toasts = [], sheets = [];
  const deps = {
    h: (tag, props, ...kids) => new Node_(tag, props, flat(kids)),
    ico: (name) => { drawnIcons.add(name); return new Node_("ico", { name }, []); },
    api: async (path, o = {}) => {
      calls.push([path, o.method || "GET", o.body]);
      const key = path.split("?")[0];
      const out = typeof answers[key] === "function" ? answers[key](o) : (answers[key] || {});
      return { json: async () => out, blob: async () => ({}), headers: { get: () => null } };
    },
    ask: async () => true, toast: (m) => toasts.push(m), haptic: () => {}, openSheet: ({ title, body, onClose }) => { const sheet = { title, body, close() { if (onClose) onClose(); } }; sheets.push(sheet); return sheet; }, saveBlob() {}, askAccess() {},
    copy() {}, speech: null, lang: () => "en-IN", closeSheet() {}, openFolder() {}, openFile() {}, openScreen() {}, token: () => "t",
    ...opts,
  };
  const c = D.create(deps);
  c.sync({ daily });
  return { c, calls, toasts, sheets };
}
const ON = { enabled: true, controls: true, power: ["lock", "sleep"], printing: true, notifications: false, webcam: false, max_upload_mb: 100 };
const STATE = (level) => ({ "/daily/state": { counts: {}, level, alert_id: 0 } });
const LEVELS = { "/daily/volume": { available: true, level: 40, muted: false }, "/daily/brightness": { available: true, level: 70 } };
const tools = (card) => card.all().filter((n) => n.props["data-tool"]).map((n) => n.props["data-tool"]);
const slider = (card, kind) => card.find((n) => n.props["data-kind"] === kind);
const inputOf = (box) => box.find((n) => n.tag === "input");
const posts = (r, path) => r.calls.filter((c) => c[0] === path && c[1] === "POST").map((c) => JSON.parse(c[2]));

test("Home offers nothing when the PC has the helpers switched off", () => {
  assert.strictEqual(rig({ enabled: false }).c.homeCard(), null);
  assert.strictEqual(rig(undefined).c.homeCard(), null);
  assert.strictEqual(rig(undefined).c.enabled(), false);
});

test("Home offers the tools this PC has, and leaves out the ones it hasn't", () => {
  assert.deepStrictEqual(tools(rig(ON).c.homeCard()), ["inbox", "notes", "tasks", "watch", "recent", "snap", "print", "brief"]);
  assert.ok(!tools(rig({ ...ON, printing: false }).c.homeCard()).includes("print"));
  const withAlerts = tools(rig({ ...ON, notifications: true }).c.homeCard());
  assert.ok(withAlerts.includes("pcnotes") && withAlerts.indexOf("pcnotes") < withAlerts.indexOf("brief"));
});

test("the sliders and media keys are only there when quick controls work on this PC", () => {
  const card = rig({ ...ON, controls: false }).c.homeCard();
  assert.strictEqual(slider(card, "volume"), null);
  assert.strictEqual(card.find((n) => n.classes.has("dy-controls")), null);
  assert.ok(slider(rig(ON).c.homeCard(), "volume") && slider(rig(ON).c.homeCard(), "brightness"));
});

atest("the sliders show what the PC really is at, as soon as it answers", async () => {
  const r = rig(ON, { ...LEVELS, ...STATE("operator") });
  const card = r.c.homeCard();
  assert.ok(slider(card, "volume").classes.has("is-loading"), "a shimmer until the PC answers");
  await later();
  const vol = slider(card, "volume"), bri = slider(card, "brightness");
  assert.ok(!vol.classes.has("is-loading"));
  assert.strictEqual(inputOf(vol).value, "40");
  assert.strictEqual(vol.styleProps["--v"], "40%");
  assert.strictEqual(vol.find((n) => n.classes.has("dy-sv")).textContent, "40%");
  assert.strictEqual(inputOf(bri).value, "70");
  assert.strictEqual(bri.find((n) => n.classes.has("dy-sv")).textContent, "70%");
});

atest("dragging the volume sends the level to the PC while moving, and again when let go", async () => {
  const r = rig(ON, { ...LEVELS, ...STATE("operator"), "/daily/volume": (o) => (o.method === "POST" ? { available: true, level: JSON.parse(o.body).level, muted: false } : { available: true, level: 40, muted: false }) });
  const card = r.c.homeCard(); await later();
  const vol = slider(card, "volume"), input = inputOf(vol);
  input.value = "75"; input.fire("input");
  assert.strictEqual(vol.styleProps["--v"], "75%", "the fill follows the finger at once");
  assert.ok(vol.classes.has("is-drag"));
  input.fire("change"); await later();
  assert.ok(!vol.classes.has("is-drag"));
  const sent = posts(r, "/daily/volume");
  assert.ok(sent.length >= 1 && sent.every((b) => b.level === 75), JSON.stringify(sent));
  assert.strictEqual(sent[sent.length - 1].level, 75);
  assert.strictEqual(vol.find((n) => n.classes.has("dy-sv")).textContent, "75%");
});

atest("a drag is not sent on every pixel", async () => {
  const r = rig(ON, { ...LEVELS, ...STATE("operator") });
  const card = r.c.homeCard(); await later();
  const input = inputOf(slider(card, "volume"));
  for (let v = 41; v <= 60; v++) { input.value = String(v); input.fire("input"); }
  await later();
  assert.ok(posts(r, "/daily/volume").length <= 2, "twenty moves in an instant are one or two requests");
});

atest("the brightness slider asks the PC only when let go (changing it is slow)", async () => {
  const r = rig(ON, { ...LEVELS, ...STATE("operator"), "/daily/brightness": (o) => (o.method === "POST" ? { available: true, level: JSON.parse(o.body).level } : { available: true, level: 70 }) });
  const card = r.c.homeCard(); await later();
  const input = inputOf(slider(card, "brightness"));
  input.value = "30"; input.fire("input"); input.value = "35"; input.fire("input"); await later();
  assert.strictEqual(posts(r, "/daily/brightness").length, 0);
  input.fire("change"); await later();
  assert.deepStrictEqual(posts(r, "/daily/brightness"), [{ level: 35 }]);
});

atest("tapping the volume icon mutes, and again un-mutes", async () => {
  let muted = false;
  const r = rig(ON, { ...STATE("operator"), "/daily/brightness": LEVELS["/daily/brightness"],
    "/daily/volume": (o) => { if (o.method === "POST") muted = JSON.parse(o.body).muted; return { available: true, level: 40, muted }; } });
  const card = r.c.homeCard(); await later();
  const icon = slider(card, "volume").find((n) => n.classes.has("dy-si"));
  icon.fire("click"); await later();
  assert.deepStrictEqual(posts(r, "/daily/volume"), [{ muted: true }]);
  assert.ok(slider(card, "volume").classes.has("is-muted"));
  assert.strictEqual(slider(card, "volume").find((n) => n.classes.has("dy-sv")).textContent, "Muted");
  slider(card, "volume").find((n) => n.classes.has("dy-si")).fire("click"); await later();
  assert.deepStrictEqual(posts(r, "/daily/volume").pop(), { muted: false });
});

atest("a desktop screen and a PC with no sound say so instead of showing a slider that does nothing", async () => {
  const r = rig(ON, { ...STATE("operator"), "/daily/volume": { available: false, level: 0, muted: false, why: "no sound" }, "/daily/brightness": { available: false, level: 0 } });
  const card = r.c.homeCard(); await later();
  const bri = slider(card, "brightness"), vol = slider(card, "volume");
  assert.ok(bri.classes.has("is-off") && inputOf(bri).disabled);
  assert.strictEqual(bri.find((n) => n.classes.has("dy-sv")).textContent, "Not on this screen");
  assert.ok(vol.classes.has("is-off") && inputOf(vol).disabled);
  assert.strictEqual(vol.find((n) => n.classes.has("dy-sv")).textContent, "No sound device");
});

atest("a phone that may only look sees the sliders but cannot move them, and has no media keys", async () => {
  const r = rig(ON, { ...LEVELS, ...STATE("viewer") });
  const card = r.c.homeCard(); await later(40);
  assert.ok(inputOf(slider(card, "volume")).disabled && inputOf(slider(card, "brightness")).disabled);
  assert.ok(card.find((n) => n.props.role === "group" && n.props["aria-label"] === "Media").hidden === true, "the media keys are hidden");
});

atest("a slider the PC refused snaps back to what the PC is at, and says why", async () => {
  let refuse = false;
  const r = rig(ON, { ...STATE("operator"), "/daily/brightness": LEVELS["/daily/brightness"],
    "/daily/volume": (o) => { if (o.method === "POST") { refuse = true; throw Object.assign(new Error("That didn't work."), { status: 422 }); } return { available: true, level: 40, muted: false }; } });
  const card = r.c.homeCard(); await later();
  const input = inputOf(slider(card, "volume"));
  input.value = "90"; input.fire("input"); input.fire("change"); await later(60);
  assert.ok(refuse && r.toasts.length >= 1);
  assert.strictEqual(inputOf(slider(card, "volume")).value, "40");
});

atest("each media key sends exactly one key to the PC", async () => {
  const r = rig(ON, { ...LEVELS, ...STATE("operator") });
  const card = r.c.homeCard(); await later();
  const key = (label) => card.find((n) => n.props["aria-label"] === label && n.tag === "button");
  const wanted = { Previous: "previous_track", "Play or pause": "play_pause", Next: "next_track" };
  for (const [label, action] of Object.entries(wanted)) {
    key(label).fire("click");
    await later(10);
    assert.deepStrictEqual(posts(r, "/daily/control").pop(), { action, steps: 1 }, label);
  }
  assert.strictEqual(posts(r, "/daily/control").length, 3);
});

atest("the badges show how much is waiting, and hide at zero", async () => {
  const r = rig(ON, { ...LEVELS, "/daily/state": { counts: { in_inbox: 2, to_phone: 1, tasks: 0, watchers: 4 }, level: "operator", alert_id: 0 } });
  const card = r.c.homeCard(); await later();
  const badge = (key) => card.querySelector(`[data-badge="${key}"]`);
  assert.strictEqual(badge("inbox").textContent, "2");
  assert.strictEqual(badge("tasks").hidden, true);
  assert.strictEqual(badge("watch").textContent, "4");
});

/* ---------------------------------------------------------------- sheets */

const SHEET_DATA = {
  "/daily/inbox": { to_pc: [{ id: "a1", kind: "text", name: "", text: "hello", size: 5, from: "Me", time: NOW, more: false, risky: false }], to_phone: [], folders: { inbox: "C:\\x\\Inbox", to_phone: "C:\\x\\To phone" } },
  "/daily/notes": { notes: [], folder: "C:\\x\\Notes" },
  "/daily/tasks": { tasks: [], now: NOW, power: ["lock"], repeats: ["daily"] },
  "/daily/watch": { watchers: [], power: ["lock"], places: [] },
  "/daily/processes": { processes: [] },
  "/daily/favourites": { favourites: [], suggestions: [{ key: "downloads", name: "Downloads", path: "C:\\Users\\x\\Downloads" }] },
  "/daily/recent": { files: [] },
  "/daily/print/info": { enabled: true, printer: "Office", offline: false },
  "/daily/notifications": { enabled: true, items: [], problem: "", available: true },
  "/daily/briefing": { lines: ["Nothing needs you right now."], status: { available: false }, updates: { count: 0, reboot: false }, inbox: {}, alerts: 0, next: [], top_programs: [] },
};

atest("Send to PC opens directly with sending controls and sent items, without download tabs", async () => {
  const r = rig(ON, { ...SHEET_DATA, ...STATE("operator"), "/daily/inbox": {
    ...SHEET_DATA["/daily/inbox"],
    to_phone: [{ name: "phone-only.pdf", size: 50, time: NOW }],
    to_pc: [...SHEET_DATA["/daily/inbox"].to_pc,
      { id: "link1", kind: "link", text: "https://example.com", time: NOW },
      { id: "file1", kind: "file", name: "sent.pdf", size: 50, time: NOW }],
  } });
  const card = r.c.homeCard(); await later();
  assert.ok(card.find((node) => node.textContent === "Send to PC"));
  r.c.openInbox(); await later();
  const { title, body } = r.sheets[0];
  assert.strictEqual(title, "Send to PC");
  assert.ok(!body.find((node) => node.props["aria-label"] === "Direction"));
  assert.ok(!body.find((node) => /To this phone|To the PC|phone-only.pdf/.test(node.textContent)));
  assert.ok(body.find((node) => node.tag === "input" && node.props.type === "file" && node.props.multiple));
  for (const label of ["Choose files…", "Send", "Copy", "To PC clipboard", "Open on PC", "Save", "sent.pdf", "hello"]) {
    assert.ok(body.find((node) => node.textContent === label), label);
  }
  for (const text of ["a message", "https://example.com/shared"]) {
    body.find((node) => node.tag === "textarea").value = "  " + text + "  ";
    body.find((node) => node.tag === "button" && node.all().some((child) => child.textContent === "Send")).fire("click");
    await later();
    assert.deepStrictEqual(posts(r, "/daily/inbox/text").pop(), { text });
    assert.strictEqual(body.find((node) => node.tag === "textarea").value, "");
  }
  assert.ok(!r.calls.some(([path]) => path.includes("tophone")));
});

atest("Choose files gives touch feedback before opening the picker", async () => {
  const feedback = [];
  const r = rig(ON, { ...SHEET_DATA, ...STATE("editor") }, { haptic: (kind) => feedback.push(kind) });
  r.c.homeCard(); await later();
  r.c.openInbox(); await later();
  const body = r.sheets[0].body;
  body.find((node) => node.tag === "input" && node.props.type === "file").click = () => feedback.push("picker");
  feedback.length = 0;
  body.find((node) => node.tag === "button" && node.all().some((child) => child.textContent === "Choose files…")).fire("click");
  assert.deepStrictEqual(feedback, ["light", "picker"]);
});

atest("Send to PC keeps the empty state and does not offer sending to viewers", async () => {
  for (const level of ["editor", "viewer"]) {
    const r = rig(ON, { ...SHEET_DATA, ...STATE(level), "/daily/inbox": { to_pc: [], folders: { inbox: "C:\\x\\Inbox" } } });
    r.c.homeCard(); await later();
    r.c.openInbox(); await later();
    const body = r.sheets[0].body;
    assert.ok(body.find((node) => node.textContent === "Nothing sent yet"));
    assert.strictEqual(!!body.find((node) => node.classes.has("dy-compose")), level === "editor");
    assert.strictEqual(!!body.find((node) => node.classes.has("dy-lock")), level === "viewer");
  }
});

for (const level of ["viewer", "editor", "operator", "admin"]) {
  atest(`a sheet is never filled with an empty slot (which a page would print as the word "null"), at ${level} level`, async () => {
    for (const open of ["openInbox", "openNotes", "openTasks", "openWatch", "openRecent", "openPrint", "openPcNotices", "openBriefing"]) {
      const r = rig({ ...ON, notifications: true }, { ...SHEET_DATA, ...STATE(level) });
      r.c.homeCard();
      await later(10);
      r.c[open]();
      await later(40);
      const body = r.sheets[0].body;
      assert.ok(body.filled && body.filled.length > 0, `${open} was filled`);
      body.filled.forEach((k, i) => assert.ok(k instanceof Node_, `${open} item ${i} is a real node, not ${k}`));
    }
  });
}

atest("an empty sheet says so with a picture slot and a plain sentence, not a blank page", async () => {
  const r = rig(ON, { ...SHEET_DATA, ...STATE("operator") });
  r.c.homeCard(); await later(10);
  r.c.openWatch(); await later(40);
  const empty = r.sheets[0].body.find((n) => n.classes.has("dy-empty"));
  assert.ok(empty, "an empty state");
  assert.ok(empty.find((n) => n.tag === "b" && /watched/i.test(n.textContent)));
});

atest("a view-only phone is told it can look but not change, and gets no form", async () => {
  const r = rig(ON, { ...SHEET_DATA, ...STATE("viewer") });
  r.c.homeCard(); await later(40);
  r.c.openTasks(); await later(40);
  const body = r.sheets[0].body;
  assert.ok(body.find((n) => n.classes.has("dy-lock")), "the note");
  assert.ok(!body.find((n) => n.classes.has("dy-form")), "no form to add tasks");
});

atest("a sheet that cannot load says why and offers to try again", async () => {
  const r = rig(ON, { ...SHEET_DATA, ...STATE("operator"), "/daily/notes": () => { throw new Error("The PC didn't answer."); } });
  r.c.homeCard(); await later(10);
  r.c.openNotes(); await later(40);
  const body = r.sheets[0].body;
  assert.ok(body.find((n) => n.tag === "b" && /didn't load/i.test(n.textContent)));
  assert.ok(body.find((n) => n.tag === "p" && /didn't answer/.test(n.textContent)));
  assert.ok(body.find((n) => n.tag === "button" && n.all().some((k) => k.tag === "span" && k.textContent === "Try again")));
});

atest("Notes keeps listening through silence and stops repeated errors after a real failure", async () => {
  let callbacks, aborted = 0;
  const speech = { status: () => "ok", start: (lang, handlers) => { callbacks = handlers; return "ok"; }, abort: () => { aborted++; } };
  const fixture = rig(ON, SHEET_DATA, { speech });
  fixture.c.openNotes(); await later();
  const body = fixture.sheets[0].body;
  const mic = body.querySelector(".dy-mic"), field = body.find((node) => node.tag === "textarea");
  field.value = "First";
  mic.onclick();
  callbacks.error("no-speech");
  assert.ok(mic.classList.contains("on"));
  assert.strictEqual(fixture.toasts.length, 0);
  callbacks.text("spoken note");
  assert.strictEqual(field.value, "First spoken note");
  callbacks.error("network");
  callbacks.error("network");
  assert.strictEqual(aborted, 1);
  assert.strictEqual(fixture.toasts.length, 1);
  assert.match(fixture.toasts[0], /internet/);
  assert.ok(!mic.classList.contains("on"));
  callbacks.text("late result");
  assert.strictEqual(field.value, "First spoken note");
});

atest("Notes stops dictation on close, resets on completion, and explains permission errors", async () => {
  let callbacks, aborted = 0;
  const speech = { status: () => "ok", start: (lang, handlers) => { callbacks = handlers; return "ok"; }, abort: () => { aborted++; } };
  const fixture = rig(ON, SHEET_DATA, { speech });
  fixture.c.openNotes(); await later();
  const mic = fixture.sheets[0].body.querySelector(".dy-mic");
  mic.onclick(); callbacks.finished();
  assert.ok(!mic.classList.contains("on"));
  mic.onclick(); callbacks.error("not-allowed");
  assert.match(fixture.toasts[0], /permission/);
  mic.onclick(); fixture.sheets[0].close();
  assert.strictEqual(aborted, 2);
  assert.ok(!mic.classList.contains("on"));
  callbacks.error("network");
  assert.strictEqual(fixture.toasts.length, 1);
});

atest("Watch can search and select Notepad beyond the old top-14 list", async () => {
  const programs = Array.from({ length: 30 }, (_, index) => ({ name: "program-" + index + ".exe", count: 1, memory_mb: 100 }));
  programs.push({ name: "notepad.exe", count: 1, memory_mb: 1 });
  const fixture = rig(ON, { ...SHEET_DATA, "/daily/processes": { processes: programs } });
  fixture.c.openWatch(); await later();
  const body = fixture.sheets[0].body;
  const select = body.find((node) => node.props["aria-label"] === "Program to watch");
  const search = body.find((node) => node.props["aria-label"] === "Search programs");
  assert.strictEqual(select.kids.length, 32);
  search.value = "NOTEPAD"; search.oninput();
  assert.deepStrictEqual(select.kids.map((node) => node.props.value), ["", "notepad.exe"]);
  select.value = "notepad.exe"; select.onchange();
  const watch = body.querySelector(".dy-form").find((node) => node.tag === "button" && node.all().some((child) => child.tag === "span" && child.textContent === "Watch"));
  watch.fire("click"); await later();
  assert.deepStrictEqual(posts(fixture, "/daily/watch"), [{ kind: "process", target: "notepad.exe", then: "" }]);
});

atest("Watch refreshes running programs and handles an empty search", async () => {
  let programs = [];
  const fixture = rig(ON, { ...SHEET_DATA, "/daily/processes": () => ({ processes: programs }) });
  fixture.c.openWatch(); await later();
  const body = fixture.sheets[0].body;
  assert.strictEqual(body.find((node) => node.tag === "select").kids[0].textContent, "No matching programs");
  programs = [{ name: "notepad.exe", count: 2 }];
  body.find((node) => node.tag === "button" && node.all().some((child) => child.textContent === "Refresh programs")).fire("click");
  await later();
  assert.strictEqual(body.find((node) => node.tag === "select").kids[1].props.value, "notepad.exe");
});

atest("a reminder form opens closed, and its quick times are all in the future", async () => {
  const r = rig(ON, { ...SHEET_DATA, ...STATE("operator") });
  r.c.homeCard(); await later(10);
  r.c.openTasks(); await later(40);
  const form = r.sheets[0].body.find((n) => n.classes.has("dy-form"));
  assert.ok(form && !form.classes.has("is-open"));
  const timeChips = form.all().filter((n) => n.classes.has("dy-chip") && /min|hour|evening|Tomorrow/.test(n.all().map((k) => k.textContent).join("")));
  assert.ok(timeChips.length >= 3);
});

atest("every icon the tools draw exists in the page's own icon set", async () => {
  const r = rig(ON, { ...SHEET_DATA, ...STATE("operator") });
  r.c.homeCard(); await later(10);
  for (const open of ["openInbox", "openNotes", "openTasks", "openWatch", "openNotifications", "openBriefing", "openRecents", "openPrint", "openSnap"]) {
    if (typeof r.c[open] === "function") { try { r.c[open](); await later(30); } catch (e) { /* a sheet that needs input is still counted for what it drew */ } }
  }
  const app = require("fs").readFileSync(require("path").join(__dirname, "..", "..", "src", "handoff", "web", "app.js"), "utf8");
  const block = app.slice(app.indexOf("const ICONS"), app.indexOf("function ico("));
  const known = new Set([...block.matchAll(/^\s{4}(\w+): '</gm)].map((m) => m[1]));
  const missing = [...drawnIcons].filter((n) => !known.has(n));
  assert.ok(drawnIcons.size >= 15, "drew " + drawnIcons.size);
  assert.deepStrictEqual(missing, []);
});

test("activity duration keeps idle totals separate from rounding", () => {
  assert.strictEqual(D.activityDuration(0), "0 min");
  assert.strictEqual(D.activityDuration(5), "<1 min");
  assert.strictEqual(D.activityDuration(8100), "2 h 15 min");
});

atest("Activity shows usage totals, open apps, history and selected dates", async () => {
  const report = { enabled: true, supported: true, paused: false, error: "", date: "2026-11-25", pc_today: "2026-11-25", retention_days: 7,
    current: { state: "idle", app: "notepad.exe", since: NOW }, open_apps: ["notepad.exe", "EXCEL.EXE"],
    icons: { "notepad.exe": "data:image/png;base64,aWNvbg==", "EXCEL.EXE": "https://untrusted.example/icon.png", "Code.exe": "data:image/png;base64,Y29kZQ==" },
    totals: { active: 8100, idle: 2700, locked: 0, excluded: 0, unavailable: 0 }, untracked_seconds: 60,
    day_start: NOW - 60, day_end: NOW + 300,
    applications: [{ name: "Code.exe", seconds: 8100 }], timeline: [{ start: NOW, end: NOW + 300, state: "active", app: "Code.exe" }],
    events: [{ time: NOW, kind: "closed", app: "EXCEL.EXE" }] };
  const fixture = rig(ON, { "/daily/activity": report });
  fixture.c.openActivity(); await later();
  try {
    const body = fixture.sheets[0].body;
    assert.ok(body.find(node => node.textContent === "2 h 15 min"));
    assert.ok(body.find(node => node.textContent === "notepad.exe"));
    assert.ok(body.find(node => node.textContent.startsWith("Idle since ")));
    assert.strictEqual(body.all().filter(node => node.tag === "img").length, 3);
    const logo = body.find(node => node.tag === "img");
    assert.strictEqual(logo.props.src, report.icons["notepad.exe"]);
    logo.fire("error");
    assert.strictEqual(body.all().filter(node => node.tag === "img").length, 2);
    body.find(node => node.tag === "button" && node.all().some(child => child.textContent === "Timeline")).fire("click");
    await later();
    assert.ok(body.find(node => node.textContent === "Not tracked"));
    assert.ok(body.find(node => node.textContent === "Code.exe"));
    assert.strictEqual(body.find(node => node.tag === "img").props.src, report.icons["Code.exe"]);
    body.find(node => node.tag === "button" && node.all().some(child => child.textContent === "App events")).fire("click");
    await later();
    assert.ok(body.find(node => node.textContent.includes("Last window closed")));
    const date = body.find(node => node.props["aria-label"] === "Activity date");
    date.value = "2026-11-24"; date.onchange(); await later();
    assert.ok(fixture.calls.some(call => call[0] === "/daily/activity?day=2026-11-24"));
  } finally { fixture.sheets[0].close(); }
});

atest("Activity handles tracking disabled without inventing work", async () => {
  const fixture = rig(ON, { "/daily/activity": { enabled: false, supported: true, paused: false, date: "2026-11-25", pc_today: "2026-11-25", retention_days: 7,
    current: { state: "unavailable" }, open_apps: [], applications: [], timeline: [], events: [], totals: {}, untracked_seconds: 60 } });
  fixture.c.openActivity(); await later();
  try {
    assert.ok(fixture.sheets[0].body.find(node => node.textContent.includes("Tracking is off")));
    assert.ok(fixture.sheets[0].body.find(node => node.textContent.includes("No active usage recorded")));
  } finally { fixture.sheets[0].close(); }
});

atest("closing an open app requires confirmation and keeps the observed row", async () => {
  let yes = false, broken = false;
  const questions = [];
  const report = { enabled: true, supported: true, can_close: true, force_quit_apps: ["notepad.exe"], date: "2026-11-25", pc_today: "2026-11-25", retention_days: 7,
    current: { state: "active", app: "notepad.exe" }, open_apps: ["notepad.exe"], applications: [], timeline: [], events: [], totals: {}, untracked_seconds: 0 };
  const fixture = rig(ON, { "/daily/activity": report, "/daily/activity/close": () => {
    if (broken) throw new Error("Windows refused the request");
    return { ok: true, message: "Close requested; check the PC for a save prompt." };
  } }, { ask: async question => { questions.push(question); return yes; } });
  fixture.c.openActivity(); await later();
  try {
    const body = fixture.sheets[0].body;
    const close = () => body.find(node => node.getAttribute("aria-label") === "Close notepad.exe").fire("click");
    close(); await later();
    assert.strictEqual(posts(fixture, "/daily/activity/close").length, 0);
    assert.ok(questions[0].message.includes("all windows"));
    yes = true; close(); await later();
    assert.deepStrictEqual(posts(fixture, "/daily/activity/close"), [{ name: "notepad.exe", confirmed: true }]);
    assert.ok(body.find(node => node.getAttribute("aria-label") === "Close notepad.exe"));
    assert.ok(fixture.toasts.some(message => message.includes("save prompt")));
    const force = () => body.find(node => node.getAttribute("aria-label") === "Force quit notepad.exe").fire("click");
    yes = false; force(); await later();
    assert.strictEqual(posts(fixture, "/daily/activity/close").length, 1);
    assert.ok(questions[questions.length - 1].message.includes("Unsaved work will be lost"));
    yes = true; force(); await later();
    assert.deepStrictEqual(posts(fixture, "/daily/activity/close")[1], { name: "notepad.exe", confirmed: true, force: true });
    broken = true; close(); await later();
    assert.ok(fixture.toasts.includes("Windows refused the request"));
    assert.ok(body.find(node => node.textContent === "notepad.exe"));
    const date = body.find(node => node.props["aria-label"] === "Activity date");
    report.date = "2026-11-24"; date.value = report.date; date.onchange(); await later();
    assert.strictEqual(body.find(node => node.getAttribute("aria-label") === "Close notepad.exe"), null);
  } finally { fixture.sheets[0].close(); }
});

Promise.all(asyncTests).then(() => {
  const bad = run.filter((r) => !r[1]);
  bad.forEach(([name, , e]) => console.log("FAIL " + name + "\n  " + (e && e.stack || e)));
  console.log(`${run.length - bad.length} of ${run.length} passed`);
  process.exit(bad.length ? 1 : 0);
});
