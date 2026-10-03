/**
 * Tests for the Lovelace card.
 *
 * The card is plain custom-element JavaScript with no build step, so rather
 * than pull in a DOM library these tests stub the handful of browser APIs it
 * touches and assert on the HTML it produces.
 *
 * Run with:  node --test tests/
 */

import assert from "node:assert/strict";
import { mock, test } from "node:test";

class FakeElement {
  constructor(tag) {
    this.tagName = tag;
    this.innerHTML = "";
    this.children = [];
    this.listeners = {};
  }

  addEventListener(type, handler) {
    (this.listeners[type] ||= []).push(handler);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  querySelector() {
    return (this._card ||= new FakeElement("ha-card"));
  }
}

globalThis.window = globalThis;
globalThis.customElements = {
  _registry: new Map(),
  define(name, ctor) {
    this._registry.set(name, ctor);
  },
  get(name) {
    return this._registry.get(name);
  },
};
globalThis.document = { createElement: (tag) => new FakeElement(tag) };
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = new FakeElement("#shadow-root");
    return this.shadowRoot;
  }
};

/* Keep the card's version banner out of the test output. */
const realInfo = console.info;
console.info = () => {};
await import("../custom_components/audiobookshelf/frontend/audiobookshelf-card.js");
console.info = realInfo;

const CardClass = customElements.get("audiobookshelf-card");

const PAYLOAD = {
  entry_id: "abc123",
  public_url: "http://books.local:13378",
  is_listening: true,
  server: { version: "2.26.3" },
  now: {
    id: "li_current",
    title: "Dune",
    author: "Frank Herbert",
    narrator: "Simon Vance",
    series: "Dune",
    series_sequence: "1",
    percent: 42.1,
    remaining: 20840,
    duration: 36000,
    cover_url: "/api/audiobookshelf/cover/abc123/li_current",
    url: "http://books.local:13378/item/li_current",
  },
  in_progress: [
    {
      id: "li_current",
      title: "Dune",
      author: "Frank Herbert",
      percent: 42.1,
      remaining: 20840,
      url: "http://books.local:13378/item/li_current",
    },
    {
      id: "li_second",
      title: "Piranesi",
      author: "Susanna Clarke",
      percent: 10,
      remaining: 16200,
      url: "http://books.local:13378/item/li_second",
    },
  ],
  finished: [
    {
      id: "li_done",
      title: "Project Hail Mary",
      author: "Andy Weir",
      finished_at: new Date(Date.now() - 86400000).toISOString(),
      url: "http://books.local:13378/item/li_done",
    },
  ],
  recently_added: [
    {
      id: "li_new",
      title: "The Spare Man",
      author: "Mary Robinette Kowal",
      added_at: new Date(Date.now() - 3600000).toISOString(),
      url: "http://books.local:13378/item/li_new",
    },
  ],
  stats: {
    today_seconds: 3600,
    week_seconds: 15600,
    total_seconds: 900000,
    books_finished: 3,
    streak_days: 4,
    recent_days: [
      { date: "2026-01-01", seconds: 0 },
      { date: "2026-01-02", seconds: 1800 },
    ],
  },
};

/** Build a card with the given config and feed it a payload. */
async function renderCard(config = {}, payload = PAYLOAD) {
  const card = new CardClass();
  card.setConfig({ type: "custom:audiobookshelf-card", ...config });
  await card._onData(payload);
  return { card, html: card.shadowRoot.querySelector().innerHTML };
}

test("registers both custom elements and the card picker entry", () => {
  assert.ok(customElements.get("audiobookshelf-card"));
  assert.ok(customElements.get("audiobookshelf-card-editor"));
  const entry = window.customCards.find((c) => c.type === "audiobookshelf-card");
  assert.ok(entry);
  assert.equal(entry.preview, true);
});

test("rejects an unknown section rather than rendering nothing", () => {
  const card = new CardClass();
  assert.throws(
    () => card.setConfig({ type: "custom:audiobookshelf-card", sections: ["nope"] }),
    /unknown section/,
  );
});

test("rejects an empty section list", () => {
  const card = new CardClass();
  assert.throws(
    () => card.setConfig({ type: "custom:audiobookshelf-card", sections: [] }),
    /at least one section/,
  );
});

test("renders the hero with title, author, series and progress", async () => {
  const { html } = await renderCard({ show_narrator: true });
  assert.match(html, /Dune/);
  assert.match(html, /Frank Herbert/);
  assert.match(html, /Dune #1/);
  assert.match(html, /Read by Simon Vance/);
  assert.match(html, /width:42.1%/);
  assert.match(html, /5h 47m left/);
  assert.match(html, /Listening now/);
});

test("does not repeat the hero book in the in-progress grid", async () => {
  const { html } = await renderCard({ sections: ["now", "progress"] });
  // The hero book must not also appear as a tile below itself.
  assert.equal(html.match(/data-item="li_current"/g), null);
  assert.equal(html.match(/data-item="li_second"/g).length, 1);
  assert.match(html, /Piranesi/);
});

test("shows the hero book as a tile when hero is off", async () => {
  const { html } = await renderCard({ hero: false, sections: ["now"] });
  assert.match(html, /data-item="li_current"/);
  assert.doesNotMatch(html, /class="hero"/);
});

test("renders finished and recently added with relative dates", async () => {
  const { html } = await renderCard({ sections: ["finished", "added"] });
  assert.match(html, /Project Hail Mary/);
  assert.match(html, /1 day ago/);
  assert.match(html, /The Spare Man/);
  assert.match(html, /1 hour ago/);
});

test("renders the stats block and sparkline", async () => {
  const { html } = await renderCard({ sections: ["stats"] });
  assert.match(html, /1h<\/div>\s*<div class="label">Today/);
  assert.match(html, /4h 20m/); // 15600 seconds this week
  assert.match(html, /250h/); // 900000 seconds total
  assert.match(html, /Day streak/);
  assert.match(html, /class="spark"/);
  assert.match(html, /data-empty/); // the zero-second day
});

test("shows empty states instead of blank sections", async () => {
  const empty = {
    ...PAYLOAD,
    now: null,
    in_progress: [],
    finished: [],
    recently_added: [],
    is_listening: false,
  };
  const { html } = await renderCard(
    { sections: ["now", "progress", "finished", "added"] },
    empty,
  );
  assert.match(html, /Nothing in progress/);
  assert.match(html, /No other books on the go/);
  assert.match(html, /Nothing finished yet/);
  assert.match(html, /Nothing added recently/);
});

test("escapes titles so a book cannot inject markup", async () => {
  const nasty = {
    ...PAYLOAD,
    now: { ...PAYLOAD.now, title: '<img src=x onerror="alert(1)">' },
  };
  const { html } = await renderCard({ sections: ["now"] }, nasty);
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x/);
});

test("hides the mark-finished button unless it is enabled", async () => {
  const off = await renderCard({ sections: ["now"] });
  assert.doesNotMatch(off.html, /data-finish/);
  const on = await renderCard({ sections: ["now"], allow_mark_finished: true });
  assert.match(on.html, /data-finish="li_current"/);
});

test("marks tiles as non-interactive when links are disabled", async () => {
  const { html } = await renderCard({ sections: ["finished"], open_links: false });
  assert.match(html, /data-static/);
});

test("finds a book by id across every list", async () => {
  const { card } = await renderCard();
  assert.equal(card._findBook("li_second").title, "Piranesi");
  assert.equal(card._findBook("li_done").title, "Project Hail Mary");
  assert.equal(card._findBook("li_new").title, "The Spare Man");
  assert.equal(card._findBook("missing"), null);
});

test("limit caps how many books each section shows", async () => {
  const { html } = await renderCard({ sections: ["progress"], limit: 1, hero: false });
  assert.equal(html.match(/class="tile"/g).length, 1);
});

test("shows a loading state before any data arrives", () => {
  const card = new CardClass();
  card.setConfig({ type: "custom:audiobookshelf-card" });
  assert.match(card.shadowRoot.querySelector().innerHTML, /Loading Audiobookshelf/);
});

test("getCardSize grows with the number of sections", () => {
  const small = new CardClass();
  small.setConfig({ type: "custom:audiobookshelf-card", sections: ["now"] });
  const big = new CardClass();
  big.setConfig({
    type: "custom:audiobookshelf-card",
    sections: ["now", "progress", "finished", "added", "stats"],
  });
  assert.ok(big.getCardSize() > small.getCardSize());
});

/**
 * A stand-in for hass.connection. Each subscribeMessage call takes the next
 * scripted outcome: an Error to reject with, or a payload to deliver.
 */
function fakeHass(outcomes) {
  const calls = [];
  const unsubscribed = [];
  return {
    calls,
    unsubscribed,
    callWS: async () => ({ path: "/signed" }),
    connection: {
      async subscribeMessage(callback, message) {
        calls.push(message);
        const outcome = outcomes.shift();
        if (outcome instanceof Error) throw outcome;
        if (outcome) callback(outcome);
        return () => unsubscribed.push(message);
      },
    },
  };
}

/** Let pending promise callbacks run. */
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("shows a dash for listening stats that have not loaded", async () => {
  const pending = {
    ...PAYLOAD,
    stats: {
      today_seconds: null,
      week_seconds: null,
      total_seconds: null,
      streak_days: null,
      books_finished: 3,
      recent_days: null,
    },
  };
  const { html } = await renderCard({ sections: ["stats"] }, pending);
  assert.match(html, /–<\/div>\s*<div class="label">Today/);
  assert.match(html, /–<\/div>\s*<div class="label">Total/);
  assert.doesNotMatch(html, /0m/);
  assert.doesNotMatch(html, /class="spark"/);
});

test("retries a failed subscription instead of staying on the error", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const notFound = Object.assign(new Error("not found"), { code: "not_found" });
    const hass = fakeHass([notFound, PAYLOAD]);
    const card = new CardClass();
    card.setConfig({ type: "custom:audiobookshelf-card" });
    card.isConnected = true;
    card.hass = hass;
    await settle();
    assert.match(card.shadowRoot.querySelector().innerHTML, /No Audiobookshelf server found/);

    mock.timers.tick(5000);
    await settle();
    assert.equal(hass.calls.length, 2);
    assert.match(card.shadowRoot.querySelector().innerHTML, /Dune/);
    assert.doesNotMatch(card.shadowRoot.querySelector().innerHTML, /No Audiobookshelf/);
  } finally {
    mock.timers.reset();
  }
});

test("backs off between retries and stops when removed from the page", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const down = new Error("down");
    const hass = fakeHass([down, down, down]);
    const card = new CardClass();
    card.setConfig({ type: "custom:audiobookshelf-card" });
    card.isConnected = true;
    card.hass = hass;
    await settle();

    mock.timers.tick(5000);
    await settle();
    assert.equal(hass.calls.length, 2);
    // The second wait is twice as long.
    mock.timers.tick(5000);
    await settle();
    assert.equal(hass.calls.length, 2);
    mock.timers.tick(5000);
    await settle();
    assert.equal(hass.calls.length, 3);

    card.disconnectedCallback();
    mock.timers.tick(60000);
    await settle();
    assert.equal(hass.calls.length, 3);
  } finally {
    mock.timers.reset();
  }
});

test("switching entry_id resubscribes to the new server", async () => {
  const other = { ...PAYLOAD, entry_id: "other", now: { ...PAYLOAD.now, title: "Emma" } };
  const hass = fakeHass([PAYLOAD, other]);
  const card = new CardClass();
  card.setConfig({ type: "custom:audiobookshelf-card", entry_id: "abc123" });
  card.isConnected = true;
  card.hass = hass;
  await settle();
  assert.match(card.shadowRoot.querySelector().innerHTML, /Dune/);

  card.setConfig({ type: "custom:audiobookshelf-card", entry_id: "other" });
  await settle();
  assert.deepEqual(hass.unsubscribed, [{ type: "audiobookshelf/subscribe", entry_id: "abc123" }]);
  assert.deepEqual(hass.calls.at(-1), { type: "audiobookshelf/subscribe", entry_id: "other" });
  const html = card.shadowRoot.querySelector().innerHTML;
  assert.match(html, /<div class="title">Emma<\/div>/);
  assert.doesNotMatch(html, /<div class="title">Dune<\/div>/);
});

test("re-applying the same config keeps the existing subscription", async () => {
  const hass = fakeHass([PAYLOAD]);
  const card = new CardClass();
  card.setConfig({ type: "custom:audiobookshelf-card", entry_id: "abc123" });
  card.isConnected = true;
  card.hass = hass;
  await settle();

  card.setConfig({ type: "custom:audiobookshelf-card", entry_id: "abc123", limit: 3 });
  await settle();
  assert.equal(hass.calls.length, 1);
  assert.deepEqual(hass.unsubscribed, []);
});
