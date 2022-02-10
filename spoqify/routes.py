import asyncio
import re

import quart

from spoqify.app import app
from spoqify.anonymization import anonymize_playlist


api_worker_limit = asyncio.Semaphore(4)


def encode_event(event, data):
    return f"event: {event}\ndata: {data}\r\n\r\n".encode()


async def limited_anonymize_playlist(playlist_id, station=False):
    async with api_worker_limit:
        return (await anonymize_playlist(playlist_id, station=station))


def _get_task(playlist_id, station=False):
    if playlist_id not in app.tasks:
        app.logger.debug("Creating task for playlist %s", playlist_id)
        app.tasks[playlist_id] = asyncio.create_task(
            limited_anonymize_playlist(playlist_id, station=station))

        def _remove_task(task):
            app.tasks.pop(playlist_id, None)
            app.logger.debug("Finished task for playlist %s", playlist_id)

        app.tasks[playlist_id].add_done_callback(_remove_task)
    else:
        app.logger.debug("Using existing task for playlist %s", playlist_id)
    return app.tasks[playlist_id]


@app.route('/anonymize/<playlist_id>')
@app.route('/anonymize/<playlist_id>/station', defaults={'station': True})
async def anonymize(playlist_id, station=False):
    if not re.match(r'[a-zA-Z0-9]+$', playlist_id):
        return quart.abort(400, "Invalid playlist ID")

    async def make_events():
        task = _get_task(playlist_id, station=station)
        while True:
            if len(app.tasks) >= 5:
                task_idx = len(app.tasks) - 1
                yield encode_event('queued', task_idx)
            try:
                url = await asyncio.wait_for(asyncio.shield(task), 5)
            except asyncio.TimeoutError:
                try:
                    task_idx = list(app.tasks).index(playlist_id)
                except ValueError:
                    task_idx = 0
                yield encode_event('queued', task_idx)
            except Exception as e:
                app.logger.error(
                    "Request for playlist %s resulted in error: %s",
                    playlist_id, e,
                    exc_info=True,
                )
                yield encode_event('error', str(e))
                break
            else:
                app.logger.info("Anonymized playlist %s: %s", playlist_id, url)
                yield encode_event('done', url)
                break

    response = await quart.make_response(
        make_events(),
        {
            'Access-Control-Allow-Origin': 'https://spoqify.com',
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Transfer-Encoding': 'chunked',
        },
    )
    response.timeout = None
    return response


@app.route('/redirect')
async def redirect():
    playlist_str = quart.request.args.get('playlist')
    playlist_id = playlist_str.split('?')[0].split('/')[-1].split(':')[-1]
    if not re.match(r'[a-zA-Z0-9]+$', playlist_id):
        return quart.abort(400, "Invalid playlist ID")
    station = bool(re.search('station[/:]', playlist_str))
    task = _get_task(playlist_id, station=station)
    url = await asyncio.shield(task)
    return quart.redirect(url)


@app.route('/playlist/<playlist_id>')
@app.route('/station/playlist/<playlist_id>')
async def playlist(playlist_id):
    app.logger.debug(
        "Handling '%s' for user agent '%s'",
        quart.request.url,
        quart.request.headers.get('user-agent'),
    )
    return quart.redirect(
        f'https://spoqify.com/anonymize/?playlist={playlist_id}')


@app.route('/')
async def index():
    return quart.redirect('https://spoqify.com/')
