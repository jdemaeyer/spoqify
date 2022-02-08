import logging
import os

import aiohttp
import quart


app = quart.Quart('spoqify')

app.config['AUTH_FILE_PATH'] = 'data/auth'
app.config['USER_AGENT'] = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, '
    'like Gecko) Chrome/92.0.4515.131 Safari/537.36')
app.config['SPOTIFY_CLIENT_ID'] = os.getenv('SPOTIFY_CLIENT_ID')
app.config['SPOTIFY_CLIENT_SECRET'] = os.getenv('SPOTIFY_CLIENT_SECRET')
app.config['SPOTIFY_USER_ID'] = os.getenv('SPOTIFY_USER_ID')


@app.before_serving
async def startup():
    app.logger.setLevel(logging.DEBUG)
    # Disable some third-party noise
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    app.session = aiohttp.ClientSession(raise_for_status=True)
    app.tasks = {}


@app.after_serving
async def shutdown():
    await app.session.close()


import spoqify.cli  # noqa
import spoqify.routes  # noqa
