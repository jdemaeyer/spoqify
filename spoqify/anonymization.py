import datetime
import html
import random
import re

import aiohttp
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


async def load_recommendations(tracks=None, artists=None):
    if tracks:
        seed_name = 'tracks'
        ids = tracks
    elif artists:
        seed_name = 'artists'
        ids = artists
    else:
        raise ValueError("Please supply at least one argument")
    app.logger.debug(
        "Loading API recommendations for %s %s", seed_name, tracks)
    assert all(re.match(r'[a-zA-Z0-9]+$', id_) for id_ in ids)
    ids_str = ','.join(ids)
    data = await call_api(
        f'recommendations?seed_{seed_name}={ids_str}&limit=50',
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
        sample_tracks = random.sample(
            data['tracks'],
            min(5, len(data['tracks'])))
        data['tracks'] = await load_recommendations(tracks=sample_tracks)
    date_str = datetime.date.today().strftime('%d %B %Y').lstrip('0')
    reanon_url = data['url'].replace('spotify.com', 'spoqify.com')
    description = (
        f"Anonymized on {date_str} via spoqify.com · Original playlist: "
        f"{data['url']} · Freshly anonymized playlist: {reanon_url}")
    url = await create_playlist(data['title'], description, data['tracks'])
    return url


async def make_recommendations_playlist(
        track_id=None, artist_id=None, album_id=None):
    tracks = None
    artists = None
    if album_id:
        assert re.match(r'[a-zA-Z0-9]+$', album_id)
        data = await call_api(f'albums/{album_id}', use_client_token=True)
        artist_id = data['artists'][0]['id']
    if track_id:
        assert re.match(r'[a-zA-Z0-9]+$', track_id)
        data = await call_api(f'tracks/{track_id}', use_client_token=True)
        title = data['name'] + ' Radio'
        tracks = [track_id]
    elif artist_id:
        assert re.match(r'[a-zA-Z0-9]+$', artist_id)
        data = await call_api(f'artists/{artist_id}', use_client_token=True)
        title = data['name'] + ' Radio'
        artists = [artist_id]
    else:
        raise ValueError("Please supply at least one argument")
    tracks = await load_recommendations(tracks=tracks, artists=artists)
    if not tracks:
        raise ValueError(
            f"Spotify's API did not return any recommendations for "
            f"'{data['name']}'. This can sometimes happen for little-known "
            "songs or artists. Please try again with a song radio URL.")
    date_str = datetime.date.today().strftime('%d %B %Y').lstrip('0')
    description = f"Anonymized on {date_str} via spoqify.com."
    url = await create_playlist(title, description, tracks)
    return url
