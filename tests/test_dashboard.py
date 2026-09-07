import asyncio
import json
import time
from unittest.mock import patch

import pytest
from textual.widgets import ListView
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from dashboard import Detail, NewsItem, Newswire, clean_text


def item(identifier='a', category='cybersecurity', score=9.8, **extra):
    return dict(type='item', protocol=1, id=identifier, category=category,
                title='Literal [bold] headline', source='NVD',
                url='https://example.com/story', severity=score,
                timestamp=1788739200, **extra)


@pytest.mark.parametrize('change', [dict(severity=11), dict(severity=True),
    dict(severity=float('nan')), dict(category='unknown'), dict(url='javascript:alert(1)'),
    dict(timestamp=-1), dict(timestamp=True), dict(replay='false'), dict(severity=None),
    dict(url='https://example.com/\x1b[2J'), dict(protocol=2)])
def test_invalid_items(change):
    value = item()
    value.update(change)
    with pytest.raises(ValueError):
        NewsItem.parse(value)


def test_literal_and_control_safe():
    assert clean_text('one\x1b\n\u202etwo') == 'one   two'
    assert NewsItem.parse(item()).render_row().plain.startswith('[!] Literal [bold] headline')


@pytest.mark.asyncio
async def test_panels_filter_detail_dedupe_and_notification_queue():
    app = Newswire('ws://127.0.0.1:1', notifications=False, boot=False)
    async with app.run_test(size=(120, 40)) as pilot:
        # Exercise enqueueing separately from native OS calls.
        app.notifications = True
        await app.accept_item(NewsItem.parse(item()))
        await app.accept_item(NewsItem.parse(item()))
        await app.accept_item(NewsItem.parse(item('high', score=7.5)))
        await app.accept_item(NewsItem.parse(item('backlog', score=9.1, replay=True)))
        for category in ('networking', 'tech', 'privacy'):
            await app.accept_item(NewsItem.parse(item(category, category, None)))
        assert len(app.items['cybersecurity']) == 3
        assert app.notification_queue.qsize() == 2
        assert all(len(app.query_one('#'+category, ListView).children) == 1
                   for category in ('networking', 'tech', 'privacy'))
        await pilot.press('f')
        assert app.critical_only
        assert len(app.query_one('#cybersecurity', ListView).children) == 2
        await pilot.press('enter')
        await pilot.pause()
        assert isinstance(app.screen, Detail)
        await pilot.press('escape', 'f')
        assert not app.critical_only
        assert len(app.query_one('#cybersecurity', ListView).children) == 3


@pytest.mark.asyncio
async def test_real_socket_heartbeat_timeout_even_while_items_arrive():
    connections = 0
    async def handler(ws):
        nonlocal connections
        connections += 1
        await ws.send(json.dumps({'type': 'heartbeat', 'protocol': 1, 'uptime': 100}))
        try:
            for i in range(100):
                await ws.send(json.dumps(item(f'{connections}-{i}')))
                await asyncio.sleep(.04)
        except ConnectionClosed:
            pass
    async with serve(handler, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        app = Newswire(f'ws://127.0.0.1:{port}', notifications=False, boot=False, heartbeat_timeout=.25)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(.5)
            assert len(app.items['cybersecurity']) > 0
            assert app.connection_state.startswith('OFFLINE')
            await pilot.pause(1.5)
            assert connections >= 2


@pytest.mark.asyncio
async def test_bad_json_does_not_disconnect_and_notifier_runs():
    hold = asyncio.Event()
    async def handler(ws):
        await ws.send('{oops')
        await ws.send(json.dumps({'type': 'heartbeat', 'protocol': 1, 'uptime': 15}))
        await ws.send(json.dumps(item()))
        await hold.wait()
    async with serve(handler, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        app = Newswire(f'ws://127.0.0.1:{port}', notifications=True, boot=False)
        with patch('plyer.notification.notify') as notify:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause(.4)
                assert app.connection_state == 'ONLINE'
                assert len(app.items['cybersecurity']) == 1
                assert notify.call_count == 1
        hold.set()


@pytest.mark.asyncio
async def test_history_is_bounded(monkeypatch):
    monkeypatch.setattr('dashboard.MAX_ITEMS', 3)
    app = Newswire('ws://127.0.0.1:1', notifications=False, boot=False)
    async with app.run_test(size=(90, 28)):
        await app.action_filter()
        for i in range(6):
            await app.accept_item(NewsItem.parse(item(str(i), score=9.8 if i < 2 else 7.5)))
        assert len(app.items['cybersecurity']) == 3
        assert not app.query_one('#cybersecurity', ListView).children
        await app.action_filter()
        assert len(app.query_one('#cybersecurity', ListView).children) == 3


@pytest.mark.asyncio
async def test_startup_replays_fill_fresh_dashboard_without_notifications():
    hold = asyncio.Event()
    async def handler(ws):
        await ws.send(json.dumps({'type': 'heartbeat', 'protocol': 1, 'uptime': 8}))
        for category in ('cybersecurity', 'networking', 'tech', 'privacy'):
            await ws.send(json.dumps(item(category, category,
                9.8 if category == 'cybersecurity' else None, replay=True)))
        await hold.wait()
    async with serve(handler, '127.0.0.1', 0) as server:
        app = Newswire(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                       notifications=True, boot=False)
        try:
            with patch('plyer.notification.notify') as notify:
                async with app.run_test(size=(100, 30)) as pilot:
                    await pilot.pause(.4)
                    assert all(len(rows) == 1 for rows in app.items.values())
                    assert all(len(app.query_one('#'+category, ListView).children) == 1
                               for category in app.items)
                    notify.assert_not_called()
        finally:
            hold.set()


@pytest.mark.asyncio
async def test_two_networking_sources_and_independent_feed_status():
    hold = asyncio.Event()
    async def handler(ws):
        await ws.send(json.dumps({'type':'heartbeat','protocol':1,'uptime':10,
                                 'feeds':{'register':'ok','apnic':'fetching'}}))
        for identifier, source in [('reg', 'The Register'), ('apnic', 'APNIC')]:
            message=item(identifier,'networking',None,replay=True)
            message['source']=source
            await ws.send(json.dumps(message))
        await ws.send(json.dumps({'type':'feed_status','feed':'apnic','state':'ok'}))
        await hold.wait()
    async with serve(handler,'127.0.0.1',0) as server:
        app=Newswire(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                     notifications=False,boot=False)
        try:
            async with app.run_test(size=(100,30)) as pilot:
                await pilot.pause(.4)
                assert {news.source for news in app.items['networking']} == {'The Register','APNIC'}
                assert app.feeds == {'register':'ok','apnic':'ok'}
        finally:
            hold.set()


@pytest.mark.asyncio
async def test_cyber_burst_keeps_reading_position_and_end_jumps_to_latest():
    app = Newswire('ws://127.0.0.1:1', notifications=False, boot=False)
    async with app.run_test(size=(100, 30)) as pilot:
        panel = app.query_one('#cybersecurity', ListView)
        panel.focus()
        await app.accept_item(NewsItem.parse(item('first')))
        await pilot.pause()
        position = panel.scroll_y
        for i in range(15):
            await app.accept_item(NewsItem.parse(item(str(i))))
        await pilot.pause()
        assert panel.highlighted_child.item.id == 'first'
        assert panel.scroll_y == position
        await pilot.press('end')
        await pilot.pause()
        assert panel.highlighted_child.item.id == '14'
        position = panel.scroll_y
        await app.accept_item(NewsItem.parse(item('next')))
        await pilot.pause()
        assert panel.highlighted_child.item.id == '14'
        assert panel.scroll_y == position


@pytest.mark.asyncio
async def test_cyber_selection_survives_history_eviction(monkeypatch):
    monkeypatch.setattr('dashboard.MAX_ITEMS', 3)
    app = Newswire('ws://127.0.0.1:1', notifications=False, boot=False)
    async with app.run_test(size=(100, 30)) as pilot:
        for identifier in ('a', 'b', 'c'):
            await app.accept_item(NewsItem.parse(item(identifier)))
        panel = app.query_one('#cybersecurity', ListView)
        panel.index = 1
        await pilot.pause()
        await app.accept_item(NewsItem.parse(item('d')))
        await pilot.pause()
        assert panel.highlighted_child.item.id == 'b'
