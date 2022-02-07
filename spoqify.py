import asyncio
import datetime
import http.server
import json
import logging
import os
import re
import time
from contextlib import suppress
from urllib.parse import urlencode

import aiohttp
import click
import quart


__version__ = '0.0.5'


if __name__ == '__main__':
    with suppress(FileNotFoundError):
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    os.environ.setdefault(*line.split('=', 1))


app = quart.Quart('spoqify')

app.config['AUTH_FILE_PATH'] = 'data/auth'
app.config['USER_AGENT'] = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, '
    'like Gecko) Chrome/92.0.4515.131 Safari/537.36')
app.config['SPOTIFY_CLIENT_ID'] = os.environ['SPOTIFY_CLIENT_ID']
app.config['SPOTIFY_CLIENT_SECRET'] = os.environ['SPOTIFY_CLIENT_SECRET']
app.config['SPOTIFY_USER_ID'] = os.environ['SPOTIFY_USER_ID']
app.tasks = {}

api_calls_allowed = asyncio.Event()
api_calls_allowed.set()
api_worker_limit = asyncio.Semaphore(4)


async def load_playlist(playlist_id):
    app.logger.debug("Loading tracks for playlist %s", playlist_id)
    resp = await app.session.get(
        f'https://open.spotify.com/playlist/{playlist_id}',
        headers={'User-Agent': app.config['USER_AGENT']})
    async with resp:
        return parse_playlist(await resp.text())


def parse_playlist(body):
    url = re.search(
        '<meta property="og:url" content="(.*?)" ?/>', body).group(1)
    title = re.search(
        '<meta property="og:title" content="(.*?)" ?/>', body).group(1)
    description = re.search(
        '<meta name="description" content="(.*?)" ?/>', body).group(1)
    tracks = re.findall(
        '<meta property="music:song" '
        'content="https://open.spotify.com/track/(.*?)" ?/>',
        body,
    )
    assert tracks, "Unable to find tracks"
    return {
        'url': url,
        'title': title,
        'description': description,
        'tracks': tracks,
    }


async def get_token(cache={}):
    if not cache:
        with suppress(Exception):
            with open(app.config['AUTH_FILE_PATH']) as f:
                cache.update(json.load(f))
        if not cache:
            raise SystemExit("Please run `python spoqify.py init` first")
    if cache.get('expires', 0) < time.time() - 60:
        if 'code' in cache:
            app.logger.debug("Authenticating with code")
            data = {
                'grant_type': 'authorization_code',
                'code': cache.pop('code'),
                'redirect_uri': 'http://localhost:8808/',
            }
        elif 'refresh_token' in cache:
            app.logger.debug("Authenticating with refresh token")
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': cache['refresh_token'],
            }
        else:
            raise SystemExit(
                "Malconfigured auth data, please run `python spoqify.py init`")
        resp = await app.session.post(
            'https://accounts.spotify.com/api/token',
            data=data,
            auth=aiohttp.helpers.BasicAuth(
                app.config['SPOTIFY_CLIENT_ID'],
                app.config['SPOTIFY_CLIENT_SECRET'],
            ),
        )
        async with resp:
            data = await resp.json()
        cache['token'] = data['access_token']
        cache['expires'] = time.time() + data['expires_in']
        if 'refresh_token' in data:
            cache['refresh_token'] = data['refresh_token']
        with open(app.config['AUTH_FILE_PATH'], 'w') as f:
            json.dump(cache, f)
    return cache['token']


async def call_api(endpoint, data=None):
    while True:
        await api_calls_allowed.wait()
        app.logger.debug("Requesting %s", endpoint)
        try:
            return (await _call_api(endpoint, data=data))
        except aiohttp.ClientResponseError as e:
            if e.status == 429:
                api_calls_allowed.clear()
                delay = float(e.headers.get('Retry-After', 5))
                app.logger.warning("Got 429, will retry in %s seconds", delay)
                await asyncio.sleep(delay)
                api_calls_allowed.set()
            else:
                raise
        else:
            break


async def _call_api(endpoint, data=None):
    resp = await app.session.request(
        method='GET' if data is None else 'POST',
        url=f'https://api.spotify.com/v1/{endpoint}',
        json=data,
        headers={'Authorization': f'Bearer {await get_token()}'},
    )
    async with resp:
        return (await resp.json())


async def create_playlist(title, description, tracks):
    app.logger.debug("Creating new playlist '%s'", title)
    data = await call_api(
        f"users/{app.config['SPOTIFY_USER_ID']}/playlists",
        data={
            'name': title,
            'description': description,
        },
    )
    playlist_id = data['id']
    app.logger.debug(
        "Adding %d tracks to playlist '%s' (%s)",
        len(tracks), title, playlist_id)
    await call_api(
        f'playlists/{playlist_id}/tracks',
        data={'uris': [f'spotify:track:{track_id}' for track_id in tracks]},
    )
    return data['external_urls']['spotify']


async def anonymize_playlist(playlist_id):
    async with api_worker_limit:
        data = await load_playlist(playlist_id)
        app.logger.debug(
            "Found %d tracks for playlist %s",
            len(data['tracks']), playlist_id)
        date_str = datetime.date.today().strftime('%d %B %Y').lstrip('0')
        reanon_url = data['url'].replace('spotify.com', 'spoqify.com')
        description = (
            f"Anonymized on {date_str} via spoqify.com. | Original playlist: "
            f"{data['url']} | Freshly anonymized playlist: {reanon_url}")
        url = await create_playlist(
            data['title'],
            description,
            data['tracks'],
        )
        return url


@click.option(
    '--manual',
    help="Do not start a temporary webserver (use this if you are running "
         "this command on a different machine than your web browser)",
    is_flag=True,
    default=False)
@app.cli.command('init', help="Perform initial Spotify user login")
def init_token(manual=False):
    params = {
        'client_id': app.config['SPOTIFY_CLIENT_ID'],
        'response_type': 'code',
        'redirect_uri': 'http://localhost:8808/',
        'scope': 'playlist-modify-public playlist-modify-private',
    }
    url = 'https://accounts.spotify.com/authorize?' + urlencode(params)
    print("Please log in to Spotify at", url)
    data = {}
    if manual:
        print(
            "Then paste the `code` param of the page you were redirected to "
            "here.")
        data['code'] = input("Code: ")
    else:
        class RequestHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                data['code'] = self.path.split('=')[-1]
                self.send_response(200)
                self.wfile.write(b'All done :)')
        httpd = http.server.HTTPServer(('', 8808), RequestHandler)
        httpd.handle_request()
    os.makedirs(os.path.dirname(app.config['AUTH_FILE_PATH'], exist_ok=True))
    with open(app.config['AUTH_FILE_PATH'], 'w') as f:
        json.dump(data, f)


@app.before_serving
async def startup():
    app.session = aiohttp.ClientSession(raise_for_status=True)
    app.logger.setLevel(logging.DEBUG)
    # Disable some third-party noise
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


@app.after_serving
async def shutdown():
    await app.session.close()


def encode_event(data):
    return f"data: {json.dumps(data)}\r\n\r\n".encode()


def _get_task(playlist_id):
    if playlist_id not in app.tasks:
        app.logger.debug("Creating task for playlist %s", playlist_id)
        app.tasks[playlist_id] = asyncio.create_task(
            anonymize_playlist(playlist_id))

        def _remove_task(task):
            app.tasks.pop(playlist_id, None)
            app.logger.debug("Finished task for playlist %s", playlist_id)

        app.tasks[playlist_id].add_done_callback(_remove_task)
    else:
        app.logger.debug("Using existing task for playlist %s", playlist_id)
    return app.tasks[playlist_id]


@app.route('/anonymize/<playlist_id>')
async def anonymize(playlist_id):
    if not re.match(r'[a-zA-Z0-9]+$', playlist_id):
        return quart.abort(400, "Invalid playlist ID")
    task = _get_task(playlist_id)

    async def make_events():
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(task), 5)
            except asyncio.TimeoutError:
                try:
                    task_idx = list(app.tasks).index(playlist_id)
                except ValueError:
                    task_idx = 0
                yield encode_event({
                    'queue_idx': task_idx,
                    'queue_size': len(app.tasks),
                })
            else:
                if app.tasks.pop(playlist_id, None):
                    app.logger.debug(
                        "Finished task for playlist %s: %s",
                        playlist_id, task.result())
                break
        yield encode_event({'playlist_url': task.result()})

    response = await quart.make_response(
        make_events(),
        {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Transfer-Encoding': 'chunked',
        },
    )
    response.timeout = None
    return response


if __name__ == '__main__':
    app.run()
