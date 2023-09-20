import asyncio
import http.server
import json
import os
from urllib.parse import urlencode

import click

from spoqify.app import app, shutdown, startup
from spoqify.spotify import call_api


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
    os.makedirs(os.path.dirname(app.config['AUTH_FILE_PATH']), exist_ok=True)
    with open(app.config['AUTH_FILE_PATH'], 'w') as f:
        json.dump(data, f)


@click.option(
    '--check',
    help="Print playlist count without deleting anything",
    is_flag=True,
    default=False)
@app.cli.command('housekeep', help="Delete 50 old playlists")
def housekeep(check=False):
    def _await(promise):
        return asyncio.get_event_loop().run_until_complete(promise)

    def _call(*args, **kwargs):
        return _await(call_api(*args, **kwargs))

    _await(startup())
    playlists = _call('me/playlists?limit=50&offset=1000')
    app.logger.info("Total playlists: %d", playlists['total'])
    if not check:
        for playlist in playlists['items']:
            # Playlists will remain available for users who followed them
            _call(f'playlists/{playlist["id"]}/followers', method='DELETE')
    _await(shutdown())
