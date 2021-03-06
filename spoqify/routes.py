import asyncio
import re

import quart

import spoqify
from spoqify.app import app
from spoqify.anonymization import (
    anonymize_playlist, make_recommendations_playlist)


api_worker_limit = asyncio.Semaphore(4)


def encode_event(event, data):
    return f"event: {event}\ndata: {data}\r\n\r\n".encode()


async def limit(f, *args, **kwargs):
    async with api_worker_limit:
        return (await f(*args, **kwargs))


def _make_task(url):
    app.logger.debug("Creating task for %s", url)
    if m := re.search(r'playlist[/:]([A-Za-z0-9]+)', url):
        f = anonymize_playlist
        kwargs = {
            'playlist_id': m.group(1),
            'station': bool(re.search('station[/:]', url)),
        }
    elif m := re.search(r'(artist|album|track)[/:]([A-Za-z0-9]+)', url):
        f = make_recommendations_playlist
        kwargs = {
            m.group(1) + '_id': m.group(2),
        }
    else:
        f = anonymize_playlist
        # Use best guess for 'abc123', 'abc123?si=xy' and 'abc123/station'
        playlist_id = url.split('/')[0].split('?')[0]
        if not re.match(r'[a-zA-Z0-9]+$', playlist_id):
            raise ValueError("Invalid playlist ID")
        kwargs = {
            'playlist_id': playlist_id,
            'station': 'station' in url,
        }
    return asyncio.create_task(limit(f, **kwargs))


def _get_task(url):
    app.recent_reqs.record()
    if url not in app.tasks:
        app.tasks[url] = _make_task(url)

        def _remove_task(task):
            app.tasks.pop(url, None)
            app.logger.debug("Finished task for %s", url)

        app.tasks[url].add_done_callback(_remove_task)
    else:
        app.logger.debug("Using existing task for %s", url)
    return app.tasks[url]


@app.route('/anonymize')
@app.route('/redirect', defaults={'stream': False})
async def anonymize(stream=True):
    # Fallback to 'playlist' for legacy support
    url = quart.request.args.get('url', quart.request.args.get('playlist'))
    if stream:
        response = await quart.make_response(
            stream_task_status(url),
            {
                'Access-Control-Allow-Origin': 'https://spoqify.com',
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                'Transfer-Encoding': 'chunked',
            },
        )
        response.timeout = None
        return response
    else:
        try:
            task = _get_task(url)
        except ValueError as e:
            return quart.abort(400, str(e))
        result_url = await asyncio.shield(task)
        return quart.redirect(result_url)


async def stream_task_status(url):
    try:
        task = _get_task(url)
    except ValueError as e:
        yield encode_event('error', str(e))
        return
    while True:
        if len(app.tasks) >= 5:
            task_idx = len(app.tasks) - 1
            yield encode_event('queued', task_idx)
        try:
            result_url = await asyncio.wait_for(asyncio.shield(task), 5)
        except asyncio.TimeoutError:
            try:
                task_idx = list(app.tasks).index(url)
            except ValueError:
                task_idx = 0
            yield encode_event('queued', task_idx)
        except Exception as e:
            app.logger.error(
                "Request for %s resulted in error: %s",
                url, e,
                exc_info=True,
            )
            yield encode_event('error', str(e))
            break
        else:
            app.logger.info("Anonymized %s: %s", url, result_url)
            yield encode_event('done', result_url)
            break


@app.route('/anonymize/<playlist_id>')
@app.route('/anonymize/<playlist_id>/station', defaults={'station': True})
async def anonymize_legacy(playlist_id, station=False):
    quart.request.args = {'url': playlist_id + ('/station' if station else '')}
    return (await anonymize())


@app.route('/playlist/<playlist_id>')
@app.route('/station/playlist/<playlist_id>')
@app.route('/track/<track_id>')
@app.route('/artist/<artist_id>')
@app.route('/album/<album_id>')
async def spotify_urls(**kwargs):
    app.logger.debug(
        "Handling '%s' for user agent '%s'",
        quart.request.url,
        quart.request.headers.get('user-agent'),
    )
    return quart.redirect(
        f'https://spoqify.com/anonymize/?url={quart.request.url}')


@app.route('/status')
async def status():
    return {
        'status': 'ok',
        'version': spoqify.__version__,
        'recent_requests': app.recent_reqs.get()
    }


@app.route('/')
async def index():
    return quart.redirect('https://spoqify.com/')
