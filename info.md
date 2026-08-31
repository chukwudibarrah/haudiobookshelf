# Audiobookshelf

Your Audiobookshelf library in Home Assistant — currently listening, recently
finished, recently added, and listening statistics.

Installs as one package: the integration talks to your server, and it serves
the `custom:audiobookshelf-card` Lovelace card for you. No Lovelace resource to
register, and your API token never reaches the browser.

**After installing:** restart Home Assistant, then add the integration from
**Settings → Devices & Services**. You will need your Audiobookshelf server URL
and an API token (Audiobookshelf → Settings → API Keys, or Settings → Users on
older versions).

See the [README](https://github.com/chukwudibarrah/haudiobookshelf)
for entities, card options and services.
