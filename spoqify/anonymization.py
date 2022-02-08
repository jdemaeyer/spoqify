import asyncio
import datetime
import re

from spoqify.app import app
from spoqify.spotify import call_api


async def load_web_playlist(playlist_id):
    app.logger.debug("Loading web tracks for playlist %s", playlist_id)
    resp = await app.session.get(
        f'https://open.spotify.com/playlist/{playlist_id}',
        headers={'User-Agent': app.config['USER_AGENT']})
    async with resp:
        try:
            return parse_web_playlist(await resp.text())
        except AttributeError:
            raise ValueError("Unable to find playlist.")


def parse_web_playlist(body):
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


async def load_api_playlist(playlist_id):
    app.logger.debug("Loading API tracks for playlist %s", playlist_id)
    data = await call_api(f'playlists/{playlist_id}', use_client_token=True)
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
    web_tsk = asyncio.create_task(load_web_playlist(playlist_id))
    api_tsk = asyncio.create_task(load_api_playlist(playlist_id))
    done, pending = await asyncio.wait(
        [web_tsk, api_tsk],
        return_when=asyncio.FIRST_EXCEPTION,
    )
    data = web_tsk.result()
    api_data = api_tsk.result()
    if api_data['tracks'][:len(data['tracks'])] == data['tracks']:
        data['tracks'] = api_data['tracks']
    else:
        app.logger.error(
            "API playlist data for %s seems to be personalized",
            playlist_id)
        # FIXME: Debug prints here
        app.logger.debug(data['tracks'])
        app.logger.debug(api_data['tracks'])
        for x, y in zip(data['tracks'], api_data['tracks']):
            app.logger.debug('%s %s', x, y)
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
