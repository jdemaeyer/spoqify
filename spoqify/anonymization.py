import base64
import datetime
import hashlib
import html
import re
import time

import aiohttp
import pyotp

from spoqify.app import app
from spoqify.spotify import call_api


class Rejected(Exception):
    pass


async def load_web_playlist(playlist_id):
    app.logger.debug("Loading web tracks for playlist %s", playlist_id)
    resp = await app.session.get(
        f'https://open.spotify.com/playlist/{playlist_id}',
        headers={'User-Agent': app.config['USER_AGENT']},
        allow_redirects=False,
        raise_for_status=False,
    )
    async with resp:
        if resp.status == 404:
            raise Rejected("Unable to find playlist. It's probably private?")
        elif resp.status != 200:
            raise Rejected(
                "Spotify gave us an error while we tried to load the playlist."
            )
        try:
            return parse_web_playlist(await resp.text())
        except AttributeError:
            raise ValueError("Unable to find playlist. It's probably private?")


def parse_web_playlist(body):
    url = re.search(
        '<meta property="og:url" content="(.*?)" ?/>', body).group(1)
    title = html.unescape(re.search(
        '<meta property="og:title" content="(.*?)" ?/>', body).group(1))
    description = html.unescape(re.search(
        '<meta name="description" content="(.*?)" ?/>', body).group(1))
    creator = html.unescape(
        re.search(
            '<meta name="music:creator" content="(.*?)" ?/>',
            body,
        ).group(1)
    ).split('/')[-1]
    if creator != 'spotify':
        raise Rejected(
            "Spoqify only works on auto-generated playlists like Song Radio. "
            "Please try again with a song radio URL!"
        )
    tracks = re.findall(
        '<meta name="music:song" '
        'content="https://open.spotify.com/track/(.*?)" ?/>',
        body,
    )
    if not tracks:
        raise ValueError("Unable to find tracks")
    return {
        'url': url,
        'title': title,
        'description': description,
        'tracks': tracks,
    }


async def load_api_playlist(playlist_id):
    app.logger.debug("Loading API tracks for playlist %s", playlist_id)
    try:
        data = await call_api(
            f'playlists/{playlist_id}', use_client_token=True)
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            raise Rejected("Unable to find playlist. It's probably private?")
        app.logger.error("Unexpected API error for playlist %s", playlist_id)
        raise ValueError("Unexpected error")
    return {
        'url': data['external_urls']['spotify'],
        'title': data['name'],
        'description': data['description'],
        'tracks': [t['track']['id'] for t in data['tracks']['items']],
    }


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
    try:
        data = await load_web_playlist(playlist_id)
    except ValueError:
        app.logger.warning(
            "Falling back to Spotify API for playlist %s", playlist_id)
        # XXX: This is not the same as what we see in a Private Browser
        #      session. Possibly it's personalized to the user that created the
        #      Spotify app? We will assume here that the user still prefers
        #      this over their own personalization.
        data = await load_api_playlist(playlist_id)
    if not data['tracks']:
        raise Rejected("Unable to retrieve tracks. Probably a daylist?")
    app.logger.debug(
        "Found %d tracks for playlist %s",
        len(data['tracks']), playlist_id)
    date_str = datetime.date.today().strftime('%d %B %Y').lstrip('0')
    description = (
        f"Anonymized on {date_str} via spoqify.com · Original playlist: "
        f"{data['url']} · Donate: https://donate.spoqify.com")
    url = await create_playlist(data['title'], description, data['tracks'])
    return url


async def anonymize_from_seed(seed_type, seed_id):
    playlist_id = await get_radio_playlist_id(seed_type, seed_id)
    return await anonymize_playlist(playlist_id)


totp_cypher = [
    59, 91, 66, 74, 30, 66, 74, 38, 46, 50, 72, 61, 44, 71, 86, 39, 89,
]
totp_bytes = [e ^ ((t % 33) + 9) for t, e in enumerate(totp_cypher)]
totp_secret = base64.b32encode(
    b''.join(bytes(str(x), 'ascii') for x in totp_bytes),
)
totp_version = 9


def _generate_totp():
    return pyotp.hotp.HOTP(
        s=totp_secret,
        digits=6,
        digest=hashlib.sha1,
    ).at(
        int(time.time() / 30),
    )


async def get_radio_playlist_id(seed_type, seed_id):
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
        token = data['accessToken']
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
