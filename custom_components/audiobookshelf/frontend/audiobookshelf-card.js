/**
 * Audiobookshelf card for Home Assistant.
 *
 * Served by the Audiobookshelf integration, which also owns the connection to
 * the server. The card never sees the Audiobookshelf API token: it subscribes
 * to `audiobookshelf/subscribe` over the Home Assistant websocket and asks
 * Home Assistant to sign the cover-art URLs it renders.
 */

const CARD_VERSION = "1.0.0";

const SECTIONS = ["now", "progress", "finished", "added", "stats"];

const DEFAULTS = {
  title: "Audiobookshelf",
  sections: ["now", "progress", "finished", "stats"],
  limit: 6,
  hero: true,
  allow_mark_finished: false,
  open_links: true,
  show_series: true,
  show_narrator: false,
};

/* Signed cover URLs are valid for an hour; re-sign well before that. */
const SIGN_EXPIRY = 3600;
const SIGN_REFRESH = 2400 * 1000;

/* Back-off for retrying a failed subscription, e.g. when the dashboard loads
 * before the integration has finished starting. */
const RETRY_MIN = 5 * 1000;
const RETRY_MAX = 60 * 1000;

const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char],
  );

/** Format a duration in seconds as "3h 12m", "12m" or "45s". */
function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (!total) return "0m";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
  if (minutes) return `${minutes}m`;
  return `${total}s`;
}

/** Format an ISO timestamp as a coarse "3 days ago". */
function formatRelative(iso) {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) {
    const minutes = Math.round(seconds / 60);
    return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  }
  if (seconds < 86400) {
    const hours = Math.round(seconds / 3600);
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  const days = Math.round(seconds / 86400);
  if (days < 31) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months} month${months === 1 ? "" : "s"} ago`;
  const years = Math.round(days / 365);
  return `${years} year${years === 1 ? "" : "s"} ago`;
}

const STYLES = `
  :host { display: block; }
  ha-card {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
  }
  .header h1 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 500;
    color: var(--ha-card-header-color, var(--primary-text-color));
    line-height: 1.2;
  }
  .header .meta {
    font-size: 0.75rem;
    color: var(--secondary-text-color);
    white-space: nowrap;
  }
  .live {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .live::before {
    content: "";
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--success-color, #4caf50);
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.25; }
  }
  @media (prefers-reduced-motion: reduce) {
    .live::before { animation: none; }
  }

  .section-title {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--secondary-text-color);
    margin: 0 0 10px;
  }

  /* Hero ---------------------------------------------------------- */
  .hero {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 16px;
    align-items: start;
  }
  .hero .cover { width: 108px; }
  .hero .title {
    font-size: 1.05rem;
    font-weight: 500;
    color: var(--primary-text-color);
    line-height: 1.3;
  }
  .hero .author {
    color: var(--secondary-text-color);
    font-size: 0.9rem;
    margin-top: 2px;
  }
  .hero .series {
    color: var(--secondary-text-color);
    font-size: 0.8rem;
    margin-top: 4px;
    font-style: italic;
  }
  .hero .times {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    color: var(--secondary-text-color);
    margin-top: 6px;
  }
  .hero-actions {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  button.action {
    font: inherit;
    font-size: 0.75rem;
    padding: 5px 12px;
    border-radius: 16px;
    border: 1px solid var(--divider-color);
    background: transparent;
    color: var(--primary-text-color);
    cursor: pointer;
  }
  button.action:hover {
    background: var(--secondary-background-color);
  }
  button.action:disabled { opacity: 0.5; cursor: default; }

  /* Covers -------------------------------------------------------- */
  .cover {
    position: relative;
    aspect-ratio: 1 / 1;
    border-radius: 6px;
    overflow: hidden;
    background: var(--secondary-background-color);
    flex-shrink: 0;
  }
  .cover img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .cover .fallback {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.4rem;
    color: var(--secondary-text-color);
    text-align: center;
    padding: 6px;
    line-height: 1.2;
  }

  /* Progress bar -------------------------------------------------- */
  .bar {
    height: 5px;
    border-radius: 3px;
    background: var(--divider-color);
    overflow: hidden;
    margin-top: 10px;
  }
  .bar > span {
    display: block;
    height: 100%;
    border-radius: 3px;
    background: var(--primary-color);
  }

  /* Grid ---------------------------------------------------------- */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
    gap: 12px;
  }
  .tile {
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 6px;
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    text-align: left;
    color: inherit;
  }
  .tile[data-static] { cursor: default; }
  .tile:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: 3px;
    border-radius: 8px;
  }
  .tile .name {
    font-size: 0.78rem;
    line-height: 1.25;
    color: var(--primary-text-color);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .tile .sub {
    font-size: 0.7rem;
    color: var(--secondary-text-color);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tile .bar { margin-top: 0; }

  /* Stats --------------------------------------------------------- */
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(78px, 1fr));
    gap: 12px;
  }
  .stat { text-align: center; }
  .stat .value {
    font-size: 1.15rem;
    font-weight: 500;
    color: var(--primary-text-color);
  }
  .stat .label {
    font-size: 0.68rem;
    color: var(--secondary-text-color);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 2px;
  }
  .spark {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    height: 34px;
    margin-top: 14px;
  }
  .spark > span {
    flex: 1;
    min-height: 2px;
    border-radius: 1px;
    background: var(--primary-color);
    opacity: 0.75;
  }
  .spark > span[data-empty] {
    background: var(--divider-color);
    opacity: 1;
  }

  .empty {
    color: var(--secondary-text-color);
    font-size: 0.85rem;
    padding: 4px 0;
  }
  .error {
    color: var(--error-color, #db4437);
    font-size: 0.85rem;
  }
  hr.divider {
    border: none;
    border-top: 1px solid var(--divider-color);
    margin: 0;
  }
`;

class AudiobookshelfCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = { ...DEFAULTS };
    this._hass = null;
    this._data = null;
    this._error = null;
    this._unsub = null;
    this._subscribing = false;
    this._retryTimer = null;
    this._retryDelay = RETRY_MIN;
    this._covers = new Map();
    this._signedAt = 0;
    this._busy = new Set();
    this._rendered = false;
  }

  static getConfigElement() {
    return document.createElement("audiobookshelf-card-editor");
  }

  static getStubConfig() {
    return { type: "custom:audiobookshelf-card", ...DEFAULTS };
  }

  setConfig(config) {
    const sections = Array.isArray(config.sections) ? config.sections : DEFAULTS.sections;
    const unknown = sections.filter((section) => !SECTIONS.includes(section));
    if (unknown.length) {
      throw new Error(
        `audiobookshelf-card: unknown section(s) ${unknown.join(", ")}. ` +
          `Valid sections are: ${SECTIONS.join(", ")}`,
      );
    }
    if (!sections.length) {
      throw new Error("audiobookshelf-card: at least one section is required");
    }

    const previousEntry = this._config.entry_id || null;
    this._config = { ...DEFAULTS, ...config, sections };
    if ((this._config.entry_id || null) !== previousEntry && this._hass) {
      /* Pointed at a different server: drop the old feed and its data. */
      this._unsubscribe();
      this._cancelRetry();
      this._data = null;
      this._error = null;
      this._subscribe();
    }
    this._config.limit = Math.max(1, Math.min(50, Number(this._config.limit) || DEFAULTS.limit));
    this._rendered = false;
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this.isConnected) this._subscribe();
  }

  connectedCallback() {
    if (this._hass) this._subscribe();
  }

  disconnectedCallback() {
    this._cancelRetry();
    this._unsubscribe();
  }

  getCardSize() {
    let size = 1;
    if (this._config.sections.includes("now")) size += 3;
    if (this._config.sections.includes("progress")) size += 3;
    if (this._config.sections.includes("finished")) size += 3;
    if (this._config.sections.includes("added")) size += 3;
    if (this._config.sections.includes("stats")) size += 2;
    return size;
  }

  getLayoutOptions() {
    return { grid_columns: 12, grid_min_columns: 6, grid_rows: this.getCardSize() };
  }

  /* ---------------------------------------------------------------- */
  /* Data                                                              */
  /* ---------------------------------------------------------------- */

  async _subscribe() {
    if (this._unsub || this._subscribing || !this._hass) return;
    this._cancelRetry();
    this._subscribing = true;
    const entryId = this._config.entry_id || null;
    const message = { type: "audiobookshelf/subscribe" };
    if (entryId) message.entry_id = entryId;

    let unsub = null;
    let error = null;
    try {
      unsub = await this._hass.connection.subscribeMessage((data) => {
        /* Ignore a feed for a server the card is no longer pointed at. */
        if (entryId === (this._config.entry_id || null)) this._onData(data);
      }, message);
    } catch (err) {
      error = err;
    }
    this._subscribing = false;

    if (error) {
      this._error =
        error.code === "not_found"
          ? "No Audiobookshelf server found. If you have more than one, set entry_id in the card configuration."
          : `Could not subscribe to Audiobookshelf: ${error.message || error}`;
      this._render();
      this._scheduleRetry();
      return;
    }
    if (entryId !== (this._config.entry_id || null)) {
      /* The config changed while we were waiting; subscribe to the new one. */
      this._release(unsub);
      this._subscribe();
      return;
    }

    this._unsub = unsub;
    this._retryDelay = RETRY_MIN;
    if (this._error) {
      this._error = null;
      this._render();
    }
  }

  _unsubscribe() {
    if (this._unsub) {
      this._release(this._unsub);
      this._unsub = null;
    }
  }

  /** Call an unsubscribe function, ignoring a connection that already went away. */
  _release(unsub) {
    Promise.resolve()
      .then(() => unsub && unsub())
      .catch(() => {});
  }

  _scheduleRetry() {
    if (this._retryTimer) return;
    const delay = this._retryDelay;
    this._retryDelay = Math.min(this._retryDelay * 2, RETRY_MAX);
    this._retryTimer = setTimeout(() => {
      this._retryTimer = null;
      this._subscribe();
    }, delay);
  }

  _cancelRetry() {
    if (this._retryTimer) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
  }

  async _onData(data) {
    this._data = data;
    this._error = null;
    await this._signCovers();
    this._render();
  }

  /** Ask Home Assistant to sign the cover paths so <img> can load them. */
  async _signCovers() {
    if (!this._hass || !this._data) return;

    const stale = Date.now() - this._signedAt > SIGN_REFRESH;
    if (stale) {
      this._covers.clear();
      this._signedAt = Date.now();
    }

    const paths = new Set();
    for (const key of ["in_progress", "finished", "recently_added"]) {
      for (const book of this._data[key] || []) {
        if (book.cover_url) paths.add(book.cover_url);
      }
    }
    if (this._data.now?.cover_url) paths.add(this._data.now.cover_url);

    await Promise.all(
      [...paths]
        .filter((path) => !this._covers.has(path))
        .map(async (path) => {
          try {
            const signed = await this._hass.callWS({
              type: "auth/sign_path",
              path,
              expires: SIGN_EXPIRY,
            });
            this._covers.set(path, signed.path);
          } catch (err) {
            // Leave it unsigned; the tile falls back to its initials.
            this._covers.set(path, null);
          }
        }),
    );
  }

  async _setFinished(book, finished) {
    if (!this._hass || this._busy.has(book.id)) return;
    this._busy.add(book.id);
    this._render();
    try {
      await this._hass.callWS({
        type: "audiobookshelf/set_finished",
        item_id: book.id,
        episode_id: book.episode_id || null,
        finished,
        ...(this._config.entry_id ? { entry_id: this._config.entry_id } : {}),
      });
    } catch (err) {
      this._error = `Could not update Audiobookshelf: ${err?.message || err}`;
    } finally {
      this._busy.delete(book.id);
      this._render();
    }
  }

  _openBook(book) {
    if (!this._config.open_links || !book?.url) return;
    window.open(book.url, "_blank", "noopener,noreferrer");
  }

  /* ---------------------------------------------------------------- */
  /* Rendering                                                         */
  /* ---------------------------------------------------------------- */

  _coverHtml(book, sizeClass = "") {
    const signed = book.cover_url ? this._covers.get(book.cover_url) : null;
    const initials = escapeHtml((book.title || "?").slice(0, 1).toUpperCase());
    const img = signed
      ? `<img src="${escapeHtml(signed)}" alt="" loading="lazy"
             onerror="this.style.display='none'">`
      : "";
    return `<div class="cover ${sizeClass}">
        <div class="fallback">${initials}</div>${img}
      </div>`;
  }

  _tileHtml(book, options = {}) {
    const sub = options.sub ?? (book.author || "");
    const bar =
      options.progress && book.percent
        ? `<div class="bar"><span style="width:${Math.min(100, book.percent)}%"></span></div>`
        : "";
    const clickable = this._config.open_links && book.url;
    return `<button class="tile" type="button" data-item="${escapeHtml(book.id)}"
        ${clickable ? "" : "data-static"}
        title="${escapeHtml(book.title)}${book.author ? ` — ${escapeHtml(book.author)}` : ""}">
        ${this._coverHtml(book)}
        <div class="name">${escapeHtml(book.title)}</div>
        ${sub ? `<div class="sub">${escapeHtml(sub)}</div>` : ""}
        ${bar}
      </button>`;
  }

  _heroHtml(book) {
    const percent = Math.min(100, Math.max(0, Number(book.percent) || 0));
    const parts = [];
    if (this._config.show_series && book.series) {
      const sequence = book.series_sequence ? ` #${book.series_sequence}` : "";
      parts.push(`<div class="series">${escapeHtml(book.series)}${escapeHtml(sequence)}</div>`);
    }
    if (this._config.show_narrator && book.narrator) {
      parts.push(`<div class="series">Read by ${escapeHtml(book.narrator)}</div>`);
    }

    const busy = this._busy.has(book.id);
    const actions = [];
    if (this._config.open_links && book.url) {
      actions.push(`<button class="action" type="button" data-open="${escapeHtml(book.id)}">Open</button>`);
    }
    if (this._config.allow_mark_finished) {
      actions.push(
        `<button class="action" type="button" data-finish="${escapeHtml(book.id)}" ${busy ? "disabled" : ""}>
           ${busy ? "Saving…" : "Mark finished"}
         </button>`,
      );
    }

    return `<div class="hero">
        ${this._coverHtml(book)}
        <div class="hero-body">
          <div class="title">${escapeHtml(book.title)}</div>
          ${book.author ? `<div class="author">${escapeHtml(book.author)}</div>` : ""}
          ${parts.join("")}
          <div class="bar"><span style="width:${percent}%"></span></div>
          <div class="times">
            <span>${percent.toFixed(0)}%</span>
            <span>${formatDuration(book.remaining)} left</span>
          </div>
          ${actions.length ? `<div class="hero-actions">${actions.join("")}</div>` : ""}
        </div>
      </div>`;
  }

  _statsHtml(stats) {
    /* null means Audiobookshelf has not returned listening stats yet. */
    const time = (seconds) => (seconds == null ? "–" : formatDuration(seconds));
    const tiles = [
      { value: time(stats.today_seconds), label: "Today" },
      { value: time(stats.week_seconds), label: "This week" },
      {
        value: stats.total_seconds == null ? "–" : `${Math.round(stats.total_seconds / 3600)}h`,
        label: "Total",
      },
      { value: stats.books_finished ?? 0, label: "Finished" },
      { value: stats.streak_days ?? "–", label: "Day streak" },
    ];

    const days = stats.recent_days || [];
    const peak = Math.max(1, ...days.map((day) => day.seconds || 0));
    const spark = days.length
      ? `<div class="spark">${days
          .map((day) => {
            const height = Math.round(((day.seconds || 0) / peak) * 100);
            const empty = day.seconds ? "" : " data-empty";
            return `<span style="height:${Math.max(height, 4)}%"${empty}
                title="${escapeHtml(day.date)}: ${escapeHtml(formatDuration(day.seconds))}"></span>`;
          })
          .join("")}</div>`
      : "";

    return `<div class="stats">${tiles
      .map(
        (tile) =>
          `<div class="stat">
             <div class="value">${escapeHtml(tile.value)}</div>
             <div class="label">${escapeHtml(tile.label)}</div>
           </div>`,
      )
      .join("")}</div>${spark}`;
  }

  _sectionHtml(title, body) {
    return `<div class="section">
        <h2 class="section-title">${escapeHtml(title)}</h2>
        ${body}
      </div>`;
  }

  _bodyHtml() {
    const config = this._config;
    const data = this._data;
    const sections = [];
    const limit = config.limit;

    const inProgress = data.in_progress || [];
    const current = data.now;
    const heroShown = config.sections.includes("now") && config.hero && current;

    if (config.sections.includes("now")) {
      sections.push(
        this._sectionHtml(
          data.is_listening ? "Listening now" : "Continue listening",
          current
            ? config.hero
              ? this._heroHtml(current)
              : `<div class="grid">${this._tileHtml(current, { progress: true })}</div>`
            : `<div class="empty">Nothing in progress.</div>`,
        ),
      );
    }

    if (config.sections.includes("progress")) {
      const rest = heroShown ? inProgress.slice(1) : inProgress;
      const shown = rest.slice(0, limit);
      sections.push(
        this._sectionHtml(
          "In progress",
          shown.length
            ? `<div class="grid">${shown
                .map((book) =>
                  this._tileHtml(book, {
                    progress: true,
                    sub: `${Math.round(book.percent || 0)}% · ${formatDuration(book.remaining)} left`,
                  }),
                )
                .join("")}</div>`
            : `<div class="empty">No other books on the go.</div>`,
        ),
      );
    }

    if (config.sections.includes("finished")) {
      const finished = (data.finished || []).slice(0, limit);
      sections.push(
        this._sectionHtml(
          "Recently finished",
          finished.length
            ? `<div class="grid">${finished
                .map((book) =>
                  this._tileHtml(book, {
                    sub: formatRelative(book.finished_at || book.last_update),
                  }),
                )
                .join("")}</div>`
            : `<div class="empty">Nothing finished yet.</div>`,
        ),
      );
    }

    if (config.sections.includes("added")) {
      const added = (data.recently_added || []).slice(0, limit);
      sections.push(
        this._sectionHtml(
          "Recently added",
          added.length
            ? `<div class="grid">${added
                .map((book) => this._tileHtml(book, { sub: formatRelative(book.added_at) }))
                .join("")}</div>`
            : `<div class="empty">Nothing added recently.</div>`,
        ),
      );
    }

    if (config.sections.includes("stats")) {
      sections.push(this._sectionHtml("Listening", this._statsHtml(data.stats || {})));
    }

    return sections.join('<hr class="divider">');
  }

  _render() {
    const root = this.shadowRoot;
    if (!this._rendered) {
      root.innerHTML = `<style>${STYLES}</style><ha-card></ha-card>`;
      this._rendered = true;
      this._card = root.querySelector("ha-card");
      this._card.addEventListener("click", (event) => this._onClick(event));
    }

    const config = this._config;
    const header = config.title
      ? `<div class="header">
           <h1>${escapeHtml(config.title)}</h1>
           ${
             this._data?.is_listening
               ? '<div class="meta live">Listening</div>'
               : this._data?.server?.version
                 ? `<div class="meta">v${escapeHtml(this._data.server.version)}</div>`
                 : ""
           }
         </div>`
      : "";

    let body;
    if (this._error) {
      body = `<div class="error">${escapeHtml(this._error)}</div>`;
    } else if (!this._data) {
      body = `<div class="empty">Loading Audiobookshelf…</div>`;
    } else {
      body = this._bodyHtml();
    }

    this._card.innerHTML = header + body;
  }

  _onClick(event) {
    const finish = event.target.closest("[data-finish]");
    if (finish) {
      const book = this._findBook(finish.dataset.finish);
      if (book) this._setFinished(book, true);
      return;
    }
    const open = event.target.closest("[data-open]");
    if (open) {
      this._openBook(this._findBook(open.dataset.open));
      return;
    }
    const tile = event.target.closest(".tile[data-item]:not([data-static])");
    if (tile) this._openBook(this._findBook(tile.dataset.item));
  }

  _findBook(itemId) {
    if (!this._data || !itemId) return null;
    if (this._data.now?.id === itemId) return this._data.now;
    for (const key of ["in_progress", "finished", "recently_added"]) {
      const match = (this._data[key] || []).find((book) => book.id === itemId);
      if (match) return match;
    }
    return null;
  }
}

/* -------------------------------------------------------------------- */
/* Visual editor                                                         */
/* -------------------------------------------------------------------- */

class AudiobookshelfCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
    this._form = null;
    this._entries = null;
  }

  setConfig(config) {
    this._config = { ...DEFAULTS, ...config };
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    if (!this._entries) this._loadEntries();
  }

  async _loadEntries() {
    if (!this._hass) return;
    this._entries = [];
    try {
      const result = await this._hass.callWS({ type: "audiobookshelf/entries" });
      this._entries = result.entries || [];
    } catch (err) {
      this._entries = [];
    }
    this._update();
  }

  get _schema() {
    const serverOptions = (this._entries || []).map((entry) => ({
      value: entry.entry_id,
      label: entry.title,
    }));

    const schema = [
      { name: "title", selector: { text: {} } },
      {
        name: "sections",
        selector: {
          select: {
            multiple: true,
            mode: "list",
            options: [
              { value: "now", label: "Continue listening" },
              { value: "progress", label: "In progress" },
              { value: "finished", label: "Recently finished" },
              { value: "added", label: "Recently added" },
              { value: "stats", label: "Listening stats" },
            ],
          },
        },
      },
      {
        name: "limit",
        selector: { number: { min: 1, max: 50, step: 1, mode: "box" } },
      },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "hero", selector: { boolean: {} } },
          { name: "open_links", selector: { boolean: {} } },
          { name: "show_series", selector: { boolean: {} } },
          { name: "show_narrator", selector: { boolean: {} } },
          { name: "allow_mark_finished", selector: { boolean: {} } },
        ],
      },
    ];

    /* Only worth showing when there is a choice to make. */
    if (serverOptions.length > 1) {
      schema.splice(1, 0, {
        name: "entry_id",
        selector: { select: { mode: "dropdown", options: serverOptions } },
      });
    }
    return schema;
  }

  _label(schemaItem) {
    return (
      {
        title: "Card title",
        entry_id: "Audiobookshelf server",
        sections: "Sections",
        limit: "Items per section",
        hero: "Large 'continue listening'",
        open_links: "Open books in Audiobookshelf",
        show_series: "Show series",
        show_narrator: "Show narrator",
        allow_mark_finished: "Show 'mark finished' button",
      }[schemaItem.name] || schemaItem.name
    );
  }

  _update() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schemaItem) => this._label(schemaItem);
      this._form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: { ...event.detail.value, type: this._config.type } },
            bubbles: true,
            composed: true,
          }),
        );
      });
      this.appendChild(this._form);
    }
    if (this._hass) this._form.hass = this._hass;
    this._form.schema = this._schema;
    this._form.data = this._config;
  }
}

if (!customElements.get("audiobookshelf-card")) {
  customElements.define("audiobookshelf-card", AudiobookshelfCard);
}
if (!customElements.get("audiobookshelf-card-editor")) {
  customElements.define("audiobookshelf-card-editor", AudiobookshelfCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "audiobookshelf-card")) {
  window.customCards.push({
    type: "audiobookshelf-card",
    name: "Audiobookshelf",
    preview: true,
    description:
      "What you are listening to, what you just finished, and how much you have listened.",
    documentationURL: "https://github.com/chukwudibarrah/haudiobookshelf#the-card",
  });
}

console.info(
  `%c AUDIOBOOKSHELF-CARD %c v${CARD_VERSION} `,
  "color: white; background: #2f3d4a; font-weight: 700;",
  "color: #2f3d4a; background: #e8eaed; font-weight: 700;",
);
