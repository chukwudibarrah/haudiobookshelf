# Changelog

## Unreleased

- Added a *Reconfigure* option to change the server URL, API token or SSL
  setting without removing the integration. Leave the token blank to keep the
  current one; a token for a different Audiobookshelf user is refused.
- Fixed the card's documentation link, which still pointed at the old
  repository name.

## 1.0.0

First release.

- Config flow setup with an Audiobookshelf server URL and API token, plus
  reauthentication when a token stops working.
- Sensors for the current book (title, author, progress, time remaining), the
  last finished book, books in progress and finished, recently added items,
  listening time today/this week/total, and a listening day streak.
- `binary_sensor` for active listening, based on how recently a player synced
  progress.
- `image` entities for the current and last finished cover art.
- Services: `mark_finished`, `mark_unfinished`, `set_progress` and `refresh`.
- The `custom:audiobookshelf-card` Lovelace card, served by the integration so
  there is no Lovelace resource to register, with a visual editor and sections
  for continue listening, in progress, recently finished, recently added and
  listening statistics.
- Cover art is proxied through an authenticated Home Assistant endpoint, so the
  Audiobookshelf token never reaches the browser.
- Diagnostics with the URL and token redacted.
