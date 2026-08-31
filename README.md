# Audiobookshelf for Home Assistant

[![hacs][hacs-badge]][hacs-url]
[![validate][validate-badge]][validate-url]

Bring your [Audiobookshelf][abs] library into Home Assistant: what you are
listening to right now, what you have just finished, what has just landed in
your library, and how much you have actually listened this week.

This repository is one HACS install that gives you **both**:

- an **integration** that talks to Audiobookshelf and creates sensors, and
- a **Lovelace card** (`custom:audiobookshelf-card`) that the integration
  serves for you — no manual resource registration.

## Why an integration and not just a card

A card on its own would have to call Audiobookshelf straight from your browser.
That means your API token sits in plaintext Lovelace config, shipped to every
browser that loads the dashboard, and every request is subject to CORS — which
Audiobookshelf does not open up by default.

So Home Assistant does the talking. The token never leaves your server. Cover
art is proxied through an authenticated Home Assistant endpoint, and the card
asks Home Assistant to sign those URLs before putting them in an `<img>`.

## Installation

### HACS (recommended)

1. HACS → **⋮** → **Custom repositories**
2. Add `https://github.com/chukwudibarrah/haudiobookshelf` with category
   **Integration**
3. Search for **Audiobookshelf**, install it, and restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Audiobookshelf**

### Manual

Copy `custom_components/audiobookshelf` into your `config/custom_components/`
directory and restart Home Assistant.

## Getting an API token

In Audiobookshelf:

- **2.26 and newer:** Settings → **API Keys** → create a key
- **Older versions:** Settings → **Users** → click your user → copy the
  **API Token**

Use a token belonging to the account whose progress you want to track — the
integration reports *that user's* books, not the whole server's.

## Configuration

Everything is set up in the UI. Options (⚙️ on the integration card):

| Option | Default | What it does |
| --- | --- | --- |
| Update interval | 60 s | How often to poll. Listening stats and library listings poll more slowly regardless. |
| Items per list | 10 | How many books to keep in each of the in-progress, finished and recently-added lists. |
| Now listening window | 300 s | How recently progress must have synced for `binary_sensor.*_listening` to be on. |
| Libraries | all | Which libraries feed the *recently added* list. |
| Public URL | server URL | Address used for the card's "open in Audiobookshelf" links, if it differs from the one Home Assistant connects to. |

## Entities

One device per server, with:

| Entity | Notes |
| --- | --- |
| `sensor.*_now_listening` | Title of the current book. Attributes carry author, narrator, series, duration, position, percent, cover URL and a deep link. |
| `sensor.*_now_listening_author` | Author of the current book, for quick templating. |
| `sensor.*_now_listening_progress` | Percent complete. |
| `sensor.*_now_listening_remaining` | Minutes left. |
| `sensor.*_last_finished` | The book you most recently finished, with the same attribute set. |
| `sensor.*_books_in_progress` | Count, plus the full list in `items`. |
| `sensor.*_books_finished` | Lifetime count, plus the recent list in `items`. |
| `sensor.*_recently_added` | Newest item in your libraries, plus the list in `items`. |
| `sensor.*_listening_time_today` | Minutes listened today. |
| `sensor.*_listening_time_this_week` | Minutes listened over the last 7 days. |
| `sensor.*_listening_time_total` | Lifetime hours. `recent_days` attribute holds the last 30 days. |
| `sensor.*_listening_streak` | Consecutive days with any listening. |
| `sensor.*_library_items` | Total items across your libraries (diagnostic). |
| `binary_sensor.*_listening` | On while a player is actively syncing progress. |
| `image.*_now_listening_cover` | Cover art, usable in picture cards and notifications. |
| `image.*_last_finished_cover` | Cover of the last finished book. |

### About `binary_sensor.*_listening`

Audiobookshelf has no "is this playing" endpoint for an arbitrary client. What
it does have is players syncing their position every few seconds while audio is
running. This sensor is on when the current book's progress was updated inside
the *now listening window*. It is a good proxy, not a guarantee — expect it to
stay on for up to that window after you hit pause.

## The card

Add it from the dashboard card picker (**Audiobookshelf**), or in YAML:

```yaml
type: custom:audiobookshelf-card
title: Audiobookshelf
sections:
  - now
  - progress
  - finished
  - stats
limit: 6
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `title` | string | `Audiobookshelf` | Card heading. Set to `""` to hide it. |
| `sections` | list | `[now, progress, finished, stats]` | Any of `now`, `progress`, `finished`, `added`, `stats`, in the order you want them. |
| `limit` | number | `6` | Books shown per section. |
| `hero` | boolean | `true` | Show the current book large. `false` renders it as a tile. |
| `open_links` | boolean | `true` | Clicking a book opens it in Audiobookshelf in a new tab. |
| `show_series` | boolean | `true` | Show series name and number in the hero. |
| `show_narrator` | boolean | `false` | Show the narrator in the hero. |
| `allow_mark_finished` | boolean | `false` | Adds a "Mark finished" button to the hero. |
| `entry_id` | string | — | Only needed if you have more than one Audiobookshelf server configured. |

The card subscribes to the integration over the websocket, so it updates as
soon as Home Assistant has new data rather than on its own timer.

### Minimal "what am I reading" card

```yaml
type: custom:audiobookshelf-card
title: ""
sections: [now]
```

### Everything

```yaml
type: custom:audiobookshelf-card
sections: [now, progress, finished, added, stats]
limit: 8
show_narrator: true
allow_mark_finished: true
```

## Services

| Service | What it does |
| --- | --- |
| `audiobookshelf.mark_finished` | Mark a library item finished. |
| `audiobookshelf.mark_unfinished` | Mark it unfinished and rewind to the start. |
| `audiobookshelf.set_progress` | Jump to a position, by `current_time` (seconds) or `percent`. |
| `audiobookshelf.refresh` | Poll now instead of waiting for the next update. |

```yaml
action: audiobookshelf.mark_finished
data:
  item_id: "{{ state_attr('sensor.audiobookshelf_now_listening', 'item_id') }}"
```

## Automation ideas

Announce a finished book:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.audiobookshelf_last_finished
conditions:
  - condition: template
    value_template: "{{ trigger.from_state.state not in ['unknown', 'unavailable'] }}"
actions:
  - action: notify.mobile_app
    data:
      title: Finished
      message: >-
        {{ states('sensor.audiobookshelf_last_finished') }} by
        {{ state_attr('sensor.audiobookshelf_last_finished', 'author') }}
```

Dim the lights when you settle in with a book:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.audiobookshelf_listening
    to: "on"
    for: "00:02:00"
actions:
  - action: light.turn_on
    target:
      entity_id: light.bedroom
    data:
      brightness_pct: 15
```

## Troubleshooting

**"Audiobookshelf rejected that API token"** — the token belongs to a deleted
user, or you pasted a session token rather than an API token. Generate a fresh
one and use the integration's *Reconfigure* option.

**Covers are blank** — the item genuinely has no artwork in Audiobookshelf, or
Home Assistant cannot reach the server for the image. Check the log for
`Cover proxy failed`.

**The card says "No Audiobookshelf server found"** — you have more than one
server configured. Set `entry_id` in the card config, or pick a server in the
visual editor.

**The card does not appear in the picker** — hard-refresh the browser. The
integration registers the card automatically, so you should not add a Lovelace
resource for it; if you added one manually, remove it.

For anything else, download diagnostics from the integration page and attach
them to an issue — they redact your URL and token.

## Limitations

- Progress is read for the *token owner's* account only. Configure the
  integration once per user if you want more than one.
- There is no playback control. Audiobookshelf playback happens in its clients,
  and the server API cannot start or pause them.
- Listening statistics come from Audiobookshelf's own aggregates, so they match
  what its web UI shows, including its quirks.

## Licence

MIT. Audiobookshelf is a separate project; this integration is not affiliated
with it.

[abs]: https://www.audiobookshelf.org/
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://hacs.xyz/
[validate-badge]: https://github.com/chukwudibarrah/haudiobookshelf/actions/workflows/validate.yml/badge.svg
[validate-url]: https://github.com/chukwudibarrah/haudiobookshelf/actions/workflows/validate.yml
