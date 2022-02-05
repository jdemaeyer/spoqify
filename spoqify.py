import re

import requests


__version__ = '0.0.1'

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, '
    'like Gecko) Chrome/92.0.4515.131 Safari/537.36')


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
    return {
        'url': url,
        'title': title,
        'description': description,
        'tracks': tracks,
    }


if __name__ == '__main__':
    # https://open.spotify.com/playlist/37i9dQZF1E8GPlttUvOQfg
    print(load_playlist('37i9dQZF1E8GPlttUvOQfg'))
