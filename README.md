# Spoqify

<img alt="Spoqify logo" align="right" src="docs/icon.png">

### Spotify playlist anonymizer.

Spotify [heavily personalizes](https://engineering.atspotify.com/2021/12/02/how-spotify-uses-ml-to-create-the-future-of-personalization/)
auto-generated playlists like Song Radio based on the music you've listened to
in the past. But sometimes you want to listen to Song Radio precisely to hear
some _fresh songs_ outside of your habitual listening realm!

**Spoqify** is an MIT-licensed dead-simple service that allows you to access
Spotify playlists like an anonymous user. When looking at a Spotify playlist,
just replace the `t` in `spotify.com` with a `q`, so that your address bar
reads `https://open.spoqify.com/...`, then hit Return and you will be forwarded
to an anonymized version of that playlist.

Alternatively, use the form at [spoqify.com](https://spoqify.com/).


## Hacking

To run Spoqify locally, follow these steps:

1. Create and activate a virtual environment:
   `python -m virtualenv .venv && source .venv/bin/activate`
2. Install Spoqify's requirements:
   `pip install -r requirements.txt`
3. Copy `.env-example` to `.env` and replace the variable values with your app
   and user credentials (you can see the Spotify Client ID and Secret at your
   app dashboard, and your Spotify User ID in the URL of your Spotify profile)
4. Run `QUART_APP=spoqify.app:app python -m quart init` and follow the
   instructions to authenticate your Spoqify instance against Spotify (this
   should only be necessary once)
5. Start the development server via `python -m spoqify`
6. You should now be good to go! Try running this command:
   `curl http://localhost:5000/anonymize/37i9dQZF1E8GPlttUvOQfg`
7. If you want to play around with the "user interface", modify the files in
   the `docs` folder, replacing `open.spoqify.com` with `localhost:5000` (or
   your own domain if you have publicly deployed your Spoqify instance), and
   adjust the `Access-Control-Allow-Origin` value in
   `spoqify.routes.anonymize()` to `null` (if you open your files locally) or
   your domain (if set up) or `*` (if you can't be arsed to figure out the
   correct setting ;))
