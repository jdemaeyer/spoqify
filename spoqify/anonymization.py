import base64
import datetime
import hashlib
import json
import os
import re
import time

import aiohttp
import pyotp

from spoqify.app import app
from spoqify.spotify import create_playlist


class Rejected(Exception):
    pass


async def anonymize_playlist(playlist_id, client_id=None, token=None):
    if client_id is None:
        client_id, token = await get_token()
    data = await load_playlist(playlist_id, client_id, token)
    app.logger.debug(
        "Found %d tracks for playlist %s",
        len(data['tracks']), playlist_id)
    if not data['tracks']:
        raise Rejected("Unable to retrieve tracks. Probably a daylist?")
    date_str = datetime.date.today().strftime('%d %B %Y').lstrip('0')
    description = (
        f"Anonymized on {date_str} via spoqify.com · Original playlist: "
        f"{data['url']} · Donate: https://donate.spoqify.com")
    url = await create_playlist(data['title'], description, data['tracks'])
    return url


async def anonymize_from_seed(seed_type, seed_id):
    client_id, token = await get_token()
    playlist_id = await get_radio_playlist_id(seed_type, seed_id, token)
    return await anonymize_playlist(playlist_id, client_id, token)


totp_secret = os.getenv('SPOTIFY_TOTP_SECRET')
totp_version = os.getenv('SPOTIFY_TOTP_VERSION')


def _generate_totp():
    return pyotp.hotp.HOTP(
        s=totp_secret,
        digits=6,
        digest=hashlib.sha1,
    ).at(
        int(time.time() / 30),
    )


async def get_token():
    totp = _generate_totp()
    resp = await app.session.get(
        'https://open.spotify.com/api/token',
        headers={
            'Accept': 'application/json',
            'User-Agent': app.config['USER_AGENT'],
        },
        params={
            'reason': 'init',
            'productType': 'web-player',
            'totp': totp,
            'totpServer': totp,
            'totpVer': totp_version,
        },
        allow_redirects=False,
    )
    async with resp:
        data = await resp.json()
        client_id = data['clientId']
        token = data['accessToken']
    return client_id, token


async def get_client_token(client_id, token):
    url = 'https://open.spotify.com/'
    resp = await app.session.get(url)
    text = await resp.text()
    config_regex = r'id="appServerConfig"[^>]+>([\w=]+)</script>'
    config_raw = base64.b64decode(re.search(config_regex, text).group(1))
    config = json.loads(config_raw.decode())
    device_id = config['correlationId']
    resp = await app.session.post(
        'https://clienttoken.spotify.com/v1/clienttoken',
        headers={
            'accept': 'application/json',
        },
        json={
            'client_data': {
                'client_id': client_id,
                'client_version': '1.2.72.110.g3c42800a',
                'js_sdk_data': {
                    'device_brand': 'unknown',
                    'device_id': device_id,
                    'device_model': 'unknown',
                    'device_type': 'computer',
                    'os': 'linux',
                    'os_version': 'unknown',
                },
            },
        },
    )
    data = await resp.json()
    return data['granted_token']['token']


async def load_playlist(playlist_id, client_id, token):
    app.logger.debug("Loading tracks for playlist %s", playlist_id)
    client_token = await get_client_token(client_id, token)
    try:
        resp = await app.session.post(
            'https://api-partner.spotify.com/pathfinder/v2/query',
            headers={
                'authorization': f'Bearer {token}',
                'client-token': client_token,
                'User-Agent': app.config['USER_AGENT'],
            },
            json={
                'variables': {
                    'uri': f'spotify:playlist:{playlist_id}',
                    'offset': 0,
                    'limit': 50,
                    'enableWatchFeedEntrypoint': False,
                },
                'operationName':'fetchPlaylist',
                'extensions': {
                    'persistedQuery': {
                        'version':1,
                        'sha256Hash':'837211ef46f604a73cd3d051f12ee63c81aca4ec6eb18e227b0629a7b36adad3',  # noqa
                    },
                },
            }
        )
        resp.raise_for_status()
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            raise Rejected("Unable to find playlist. It's probably private?")
        app.logger.error("Unexpected API error for playlist %s", playlist_id)
        raise ValueError("Unexpected error")
    else:
        data = await resp.json()
    playlist = data['data']['playlistV2']
    if playlist['__typename'] == 'NotFound':
        raise Rejected("Unable to find playlist. It's probably private?")
    if playlist['ownerV2']['data']['username'] != 'spotify':
        raise Rejected(
            "Spoqify only works on auto-generated playlists like Song Radio. "
            "Please try again with a song radio URL!"
        )
    tracks = playlist['content']['items']
    return {
        'url': playlist['sharingInfo']['shareUrl'].split('?')[0],
        'title': playlist['name'],
        'description': playlist['description'],
        'tracks': [t['itemV2']['data']['uri'].split(':')[-1] for t in tracks],
    }


async def get_radio_playlist_id(seed_type, seed_id, token):
    resp = await app.session.get(
        f'https://spclient.wg.spotify.com/'
        f'inspiredby-mix/v2/seed_to_playlist/spotify:{seed_type}:{seed_id}',
        params={'response-format': 'json'},
        headers={
            'Authorization': f'Bearer {token}',
            'User-Agent': app.config['USER_AGENT'],
        },
        allow_redirects=False,
    )
    async with resp:
        data = await resp.json()
        playlist_id = data['mediaItems'][0]['uri'].split(':')[-1]
    return playlist_id
