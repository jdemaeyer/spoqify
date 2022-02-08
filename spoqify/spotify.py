import asyncio
import json
import time
from contextlib import suppress

import aiohttp

from spoqify.app import app


INIT_CMD = 'QUART_APP=spoqify.app:app python -m quart init'


api_calls_allowed = asyncio.Event()
api_calls_allowed.set()


class AuthCache(dict):

    PATH = app.config['AUTH_FILE_PATH']

    def load(self, require_init=False):
        if not self:
            with suppress(Exception):
                with open(self.PATH) as f:
                    self.update(json.load(f))
            if not self and require_init:
                raise SystemExit(f"Please run `{INIT_CMD}` first")

    def store(self):
        with open(self.PATH, 'w') as f:
            json.dump(self, f)


cache = AuthCache()


async def get_token():
    cache.load(require_init=True)
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
                f"Malconfigured auth data, please run `{INIT_CMD}`")
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
        cache.store()
    return cache['token']


async def get_client_token():
    cache.load()
    if cache.get('client_expires', 0) < time.time() - 60:
        resp = await app.session.post(
            'https://accounts.spotify.com/api/token',
            data={
                'grant_type': 'client_credentials',
            },
            auth=aiohttp.helpers.BasicAuth(
                app.config['SPOTIFY_CLIENT_ID'],
                app.config['SPOTIFY_CLIENT_SECRET'],
            ),
        )
        async with resp:
            data = await resp.json()
        cache['client_token'] = data['access_token']
        cache['client_expires'] = time.time() + data['expires_in']
        cache.store()
    return cache['client_token']


async def call_api(endpoint, data=None, use_client_token=False):
    while True:
        await api_calls_allowed.wait()
        try:
            resp = await call_api_now(
                endpoint, data=data, use_client_token=use_client_token)
            return resp
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


async def call_api_now(endpoint, data=None, use_client_token=False):
    if use_client_token:
        token = await get_client_token()
    else:
        token = await get_token()
    app.logger.debug(
        "Requesting %s with %s token",
        endpoint,
        'client' if use_client_token else 'user',
    )
    resp = await app.session.request(
        method='GET' if data is None else 'POST',
        url=f'https://api.spotify.com/v1/{endpoint}',
        json=data,
        headers={'Authorization': f'Bearer {token}'},
    )
    async with resp:
        return (await resp.json())
