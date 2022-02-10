import datetime
import html
import random
import re

import aiohttp
from spoqify.app import app
from spoqify.spotify import call_api


async def load_web_playlist(playlist_id):
    app.logger.debug("Loading web tracks for playlist %s", playlist_id)
    resp = await app.session.get(
        f'https://open.spotify.com/playlist/{playlist_id}',
        headers={'User-Agent': app.config['USER_AGENT']},
        allow_redirects=False,
    )
    async with resp:
        try:
            return parse_web_playlist(await resp.text())
        except AttributeError:
            raise ValueError("Unable to find playlist.")


def parse_web_playlist(body):
    url = re.search(
        '<meta property="og:url" content="(.*?)" ?/>', body).group(1)
    title = html.unescape(re.search(
        '<meta property="og:title" content="(.*?)" ?/>', body).group(1))
    description = html.unescape(re.search(
        '<meta name="description" content="(.*?)" ?/>', body).group(1))
    tracks = re.findall(
        '<meta property="music:song" '
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
            raise ValueError("Unable to find playlist")
        app.logger.error("Unexpected API error for playlist %s", playlist_id)
        raise ValueError("Unexpected error")
    return {
        'url': data['external_urls']['spotify'],
        'title': data['name'],
        'description': data['description'],
        'tracks': [t['track']['id'] for t in data['tracks']['items']],
    }


async def load_recommendations(tracks):
    app.logger.debug("Loading API recommendations for tracks %s", tracks)
    assert all(re.match(r'[a-zA-Z0-9]+$', track) for track in tracks)
    tracks_str = ','.join(tracks)
    data = await call_api(
        f'recommendations?seed_tracks={tracks_str}&limit=50',
        use_client_token=True,
    )
    return [track['id'] for track in data['tracks']]


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


async def anonymize_playlist(playlist_id, station=False):
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
    app.logger.debug(
        "Found %d tracks for playlist %s",
        len(data['tracks']), playlist_id)
    if station:
        app.logger.debug(
            "Loading recommendations based on five songs from playlist %s",
            playlist_id)
        data['title'] = f"Playlist Radio based on {data['title']}"
        data['tracks'] = await load_recommendations(
            random.sample(data['tracks'], 5))
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
