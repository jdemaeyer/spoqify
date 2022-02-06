import datetime
import http.server
import json
import logging
import os
import re
import sys
import time
from contextlib import suppress
from functools import cache
from urllib.parse import urlencode

import requests


__version__ = '0.0.2'

AUTH_FILE_PATH = 'data/auth'
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, '
    'like Gecko) Chrome/92.0.4515.131 Safari/537.36')


logger = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


@cache
def get_config():
    config = {
        'client_id': os.getenv('SPOTIFY_CLIENT_ID'),
        'client_secret': os.getenv('SPOTIFY_CLIENT_SECRET'),
        'user_id': os.getenv('SPOTIFY_USER_ID'),
    }
    if not all(config.values()):
        raise ConfigError(
            "Please set the SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, and "
            "SPOTIFY_USER_ID environment variables")
    return config


def load_playlist(playlist_id):
    resp = requests.get(
        f'https://open.spotify.com/playlist/{playlist_id}',
        headers={'User-Agent': USER_AGENT})
    resp.raise_for_status()
    return parse_playlist(resp.text)


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


def get_token(cache={}):
    config = get_config()
    if not cache:
        with suppress(Exception):
            with open(AUTH_FILE_PATH) as f:
                cache.update(json.load(f))
        if not cache:
            raise ConfigError("Please run `python spoqify.py init` first")
    if cache.get('expires', 0) < time.time() - 60:
        if 'code' in cache:
            logger.debug("Authenticating with code")
            data = {
                'grant_type': 'authorization_code',
                'code': cache.pop('code'),
                'redirect_uri': 'http://localhost:8808/',
            }
        elif 'refresh_token' in cache:
            logger.debug("Authenticating with refresh token")
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': cache['refresh_token'],
            }
        else:
            raise ConfigError(
                "Malconfigured auth data, please run `python spoqify.py init`")
        resp = requests.post(
            'https://accounts.spotify.com/api/token',
            data=data,
            auth=(config['client_id'], config['client_secret']),
        )
        resp.raise_for_status()
        data = resp.json()
        cache['token'] = data['access_token']
        cache['expires'] = time.time() + data['expires_in']
        if 'refresh_token' in data:
            cache['refresh_token'] = data['refresh_token']
        with open(AUTH_FILE_PATH, 'w') as f:
            json.dump(cache, f)
    return cache['token']


def call_api(endpoint, data=None):
    resp = requests.request(
        method='GET' if data is None else 'POST',
        url=f'https://api.spotify.com/v1/{endpoint}',
        json=data,
        headers={'Authorization': f'Bearer {get_token()}'.encode()},
    )
    resp.raise_for_status()
    return resp.json()


def create_playlist(title, description, tracks):
    config = get_config()
    user_id = config['user_id']
    data = call_api(
        f'users/{user_id}/playlists',
        data={
            'name': title,
            'description': description,
        },
    )
    playlist_id = data['id']
    call_api(
        f'playlists/{playlist_id}/tracks',
        data={'uris': [f'spotify:track:{track_id}' for track_id in tracks]},
    )
    return data['external_urls']['spotify']


def anonymize_playlist(playlist_id):
    data = load_playlist(playlist_id)
    description = (
        "Anonymized via spoqify.com on "
        f"{datetime.date.today().strftime('%d %B %Y').lstrip('0')}. | "
        f"Original playlist: {data['url']} | "
        "Freshly anonymized playlist: "
        f"{data['url'].replace('spotify.com', 'spoqify.com')}")
    return create_playlist(
        data['title'],
        description,
        data['tracks'],
    )


def init_token(manual=False):
    config = get_config()
    params = {
        'client_id': config['client_id'],
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
    os.makedirs(os.path.dirname(AUTH_FILE_PATH), exist_ok=True)
    with open(AUTH_FILE_PATH, 'w') as f:
        json.dump(data, f)


def configure_logging():
    logging.basicConfig(
        format='%(asctime)s %(name)s %(levelname)s  %(message)s',
        level=logging.DEBUG,
    )
    # Disable some third-party noise
    logging.getLogger('urllib3').setLevel(logging.WARNING)


if __name__ == '__main__':
    configure_logging()
    if len(sys.argv) > 1 and sys.argv[1] == 'init':
        manual = len(sys.argv) > 2 and sys.argv[2] == '--manual'
        init_token(manual=manual)
        print(call_api('me'))
    # https://open.spotify.com/playlist/37i9dQZF1E8GPlttUvOQfg
    print(anonymize_playlist('37i9dQZF1DX39Q9ceUSQK1'))
