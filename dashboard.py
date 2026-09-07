"""NEWSWIRE: a terminal-only, four-channel ESP32 broadcast receiver."""
from __future__ import annotations

import argparse
import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import time
import unicodedata
from urllib.parse import urlsplit

from pyfiglet import Figlet
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, ListItem, ListView, Static
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

CATEGORIES = {
    'cybersecurity': 'CYBERSECURITY ALERTS',
    'networking': 'NETWORKING',
    'tech': 'GENERAL TECH',
    'privacy': 'PRIVACY / DATA',
}
COLORS = {'cybersecurity': '#ff6174', 'networking': '#57dcf5',
          'tech': '#65f5a2', 'privacy': '#e18bff'}
MAX_ITEMS = 200


def clean_text(value: str, limit: int = 1200) -> str:
    # Treat all remote content as literal text. Strip terminal control sequences,
    # bidi controls, and newlines that could impersonate dashboard regions.
    return ''.join(c if not unicodedata.category(c).startswith('C') else ' '
                   for c in value)[:limit].strip()


@dataclass(frozen=True)
class NewsItem:
    id: str
    category: str
    title: str
    source: str
    url: str
    severity: float | None
    timestamp: float
    replay: bool = False

    @classmethod
    def parse(cls, message: dict) -> NewsItem:
        if message.get('protocol') != 1 or message.get('type') != 'item':
            raise ValueError('Unsupported item protocol')
        for key in ('id', 'category', 'title', 'source', 'url'):
            if not isinstance(message.get(key), str) or not message[key].strip():
                raise ValueError(f'Missing {key}')
        if message['category'] not in CATEGORIES:
            raise ValueError('Unknown category')
        url = message['url']
        if len(url) > 2048 or any(unicodedata.category(c).startswith('C') for c in url):
            raise ValueError('Invalid URL')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
            raise ValueError('Invalid URL')
        score = message.get('severity')
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))
                                  or not math.isfinite(score) or not 0 <= score <= 10):
            raise ValueError('Invalid CVSS')
        if message['category'] == 'cybersecurity' and score is None:
            raise ValueError('Cybersecurity items require a verified score')
        stamp = message.get('timestamp')
        if isinstance(stamp, bool) or not isinstance(stamp, (float, int)) or not math.isfinite(stamp):
            raise ValueError('Invalid timestamp')
        if not 0 < stamp < 253402300800:
            raise ValueError('Timestamp out of range')
        replay = message.get('replay', False)
        if not isinstance(replay, bool):
            raise ValueError('Invalid replay flag')
        if len(message['id']) > 128:
            raise ValueError('ID too long')
        return cls(message['id'], message['category'], clean_text(message['title']),
                   clean_text(message['source'], 80), url, score, float(stamp), replay)

    @property
    def critical(self) -> bool:
        return self.category == 'cybersecurity' and self.severity is not None and self.severity >= 9

    def render_row(self) -> Text:
        prefix = '[!] ' if self.critical else ''
        score = f'  CVSS {self.severity:.1f}' if self.severity is not None else ''
        stamp = datetime.fromtimestamp(self.timestamp, timezone.utc).strftime('%m-%d %H:%MZ')
        text = Text(prefix + self.title, style=COLORS[self.category])
        if self.category == 'cybersecurity':
            text.stylize('bold')
        text.append(f'\n{self.source}  ·  {stamp}{score}', style='dim')
        return text


class NewsRow(ListItem):
    def __init__(self, item: NewsItem):
        super().__init__(Label(item.render_row()), classes='critical' if item.critical else '')
        self.item = item


class Detail(ModalScreen):
    BINDINGS = [Binding('escape', 'dismiss', 'Close'), Binding('enter', 'dismiss', 'Close'),
                Binding('o', 'open_url', 'Open URL')]

    def __init__(self, item: NewsItem):
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        with Vertical(id='detail-box'):
            yield Static(CATEGORIES[self.item.category], id='detail-heading')
            with VerticalScroll():
                yield Static(self.item.render_row())
                yield Static(Text('\n' + self.item.url), id='detail-url')
            yield Static('ESC / ENTER  close     O  open in configured terminal browser')

    async def action_open_url(self) -> None:
        await self.app.open_item_url(self.item)


class Newswire(App):
    TITLE = 'NEWSWIRE / Broadcast Console'
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = Path(__file__).with_name('dashboard.tcss')
    BINDINGS = [
        Binding('q', 'quit', 'Quit', priority=True),
        Binding('enter', 'expand', 'Expand', priority=True),
        Binding('o', 'open_url', 'Open URL'),
        Binding('f', 'filter', 'Critical filter'),
        Binding('end', 'latest', 'Latest', priority=True),
        Binding('1', 'channel("cybersecurity")', 'Cyber', show=False),
        Binding('2', 'channel("networking")', 'Network', show=False),
        Binding('3', 'channel("tech")', 'Tech', show=False),
        Binding('4', 'channel("privacy")', 'Privacy', show=False),
        Binding('tab', 'focus_next', 'Next panel', priority=True),
    ]

    def __init__(self, uri: str, *, notifications: bool = True,
                 heartbeat_timeout: float = 75, url_command: str | None = None,
                 boot: bool = True):
        super().__init__()
        self.uri = uri
        self.notifications = notifications
        self.heartbeat_timeout = heartbeat_timeout
        self.url_command = url_command
        self.boot = boot
        self.items = {key: deque(maxlen=MAX_ITEMS) for key in CATEGORIES}
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.critical_only = False
        self.connection_state = 'OFFLINE — reconnecting…'
        self.last_heartbeat: float | None = None
        self.last_heartbeat_wall: datetime | None = None
        self.device_uptime: float = 0
        self.feeds: dict[str, str] = {}
        self.note = 'Waiting for ESP32'
        self.notification_queue: asyncio.Queue[NewsItem] = asyncio.Queue(maxsize=256)

    def compose(self) -> ComposeResult:
        yield Static('NEWSWIRE  /  ESP32-S3 BROADCAST CONSOLE', id='masthead')
        yield Static(id='device-status')
        yield Static(Figlet(font='small').renderText('NEWSWIRE').rstrip(), id='boot-banner')
        with Grid(id='channels'):
            for key, title in CATEGORIES.items():
                with Vertical(id=f'panel-{key}', classes='channel'):
                    yield Static(title, id=f'title-{key}', classes='channel-title')
                    yield ListView(id=key)
        yield Static(id='feed-status')
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#boot-banner').display = self.boot
        if self.boot:
            self.set_timer(1.5, lambda: setattr(self.query_one('#boot-banner'), 'display', False))
        self.set_interval(1, self.refresh_status)
        self.refresh_status()
        self.query_one('#cybersecurity', ListView).focus()
        self.run_worker(self.receive_loop(), name='websocket', exclusive=True, group='connection')
        if self.notifications:
            self.run_worker(self.notification_loop(), name='notifications', group='notifications')

    def refresh_status(self) -> None:
        age = time.monotonic() - self.last_heartbeat if self.last_heartbeat is not None else None
        last = self.last_heartbeat_wall.strftime('%H:%M:%S') if self.last_heartbeat_wall else '—'
        online = self.connection_state == 'ONLINE' and age is not None and age < self.heartbeat_timeout
        # Never claim online solely because the TCP connection remains open.
        if self.connection_state == 'ONLINE' and not online:
            self.connection_state = 'OFFLINE — reconnecting…'
        up = int(self.device_uptime + (age if online else 0))
        uptime = f'{up//86400}d {up//3600%24:02}:{up//60%60:02}:{up%60:02}'
        status = self.query_one('#device-status', Static)
        status.set_class(online, 'online')
        status.set_class(not online, 'offline')
        age_text = f'{int(age)}s ago' if age is not None else 'never'
        status.update(Text(f'● {self.connection_state}   │   HB {last} ({age_text})   │   UPTIME {uptime}'))
        feeds = '  '.join(f'{key.upper()}: {value}' for key, value in self.feeds.items())
        self.query_one('#feed-status', Static).update(Text(f'{self.note}   {feeds}'))

    async def receive_loop(self) -> None:
        delay = 1.0
        while True:
            valid_heartbeat = False
            try:
                async with connect(self.uri, open_timeout=10, close_timeout=2,
                                   ping_interval=20, ping_timeout=20,
                                   max_size=16384, max_queue=32, proxy=None) as socket:
                    self.connection_state = 'CONNECTED — awaiting heartbeat'
                    self.note = self.uri
                    deadline = time.monotonic() + self.heartbeat_timeout
                    self.refresh_status()
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('Heartbeat timed out')
                        raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
                        try:
                            message = json.loads(raw)
                            if not isinstance(message, dict):
                                raise ValueError('Expected JSON object')
                            if message.get('type') == 'heartbeat':
                                up = message.get('uptime')
                                if message.get('protocol') != 1 or isinstance(up, bool) or not isinstance(up, (int, float)) or not math.isfinite(up) or up < 0:
                                    raise ValueError('Invalid heartbeat')
                                self.last_heartbeat = time.monotonic()
                                self.last_heartbeat_wall = datetime.now()
                                self.device_uptime = up
                                self.connection_state = 'ONLINE'
                                deadline = self.last_heartbeat + self.heartbeat_timeout
                                valid_heartbeat = True
                                if isinstance(message.get('feeds'), dict):
                                    self.feeds = {k: clean_text(v, 100) for k, v in message['feeds'].items()
                                                  if k in ('hn', 'nvd', 'cisa', 'register', 'apnic', 'eff', 'reddit') and isinstance(v, str)}
                                self.refresh_status()
                            elif message.get('type') == 'item':
                                await self.accept_item(NewsItem.parse(message))
                            elif message.get('type') == 'feed_status':
                                key, state = message.get('feed'), message.get('state')
                                if key in ('hn', 'nvd', 'cisa', 'register', 'apnic', 'eff', 'reddit') and isinstance(state, str):
                                    self.feeds[key] = clean_text(state, 100)
                                    self.refresh_status()
                        except (ValueError, TypeError, OverflowError) as exc:
                            self.note = f'Ignored malformed message: {clean_text(str(exc), 80)}'
            except asyncio.CancelledError:
                raise
            except (OSError, WebSocketException, TimeoutError) as exc:
                self.connection_state = 'OFFLINE — reconnecting…'
                self.note = f'{type(exc).__name__}: retrying connection'
                self.refresh_status()
            if valid_heartbeat:
                delay = 1.0
            await asyncio.sleep(delay + random.uniform(0, delay * .2))
            delay = min(delay * 2, 30)

    async def accept_item(self, item: NewsItem) -> None:
        if item.id in self.seen:
            self.seen.move_to_end(item.id)
            return
        self.seen[item.id] = None
        if len(self.seen) > 10000:
            self.seen.popitem(last=False)
        self.items[item.category].append(item)
        panel = self.query_one(f'#{item.category}', ListView)
        previous = panel.highlighted_child
        follow = item.category != 'cybersecurity' and (
            panel.index is None or panel.index == len(panel.children) - 1)
        if not (item.category == 'cybersecurity' and self.critical_only and not item.critical):
            await panel.append(NewsRow(item))
            if len(panel.children) > MAX_ITEMS:
                await panel.children[0].remove()
            if follow:
                panel.index = len(panel.children) - 1
        # When hidden items evict a displayed item, keep the filtered view bounded
        # to exactly the same history as the unfiltered panel.
        if item.category == 'cybersecurity' and self.critical_only:
            retained = {news.id for news in self.items[item.category]}
            for row in list(panel.children):
                if isinstance(row, NewsRow) and row.item.id not in retained:
                    await row.remove()
        if item.category == 'cybersecurity' and panel.children:
            # Keep reading the same alert while new ones arrive, including
            # when older history is evicted from the bounded list.
            panel.index = (list(panel.children).index(previous)
                           if previous in panel.children else 0)
        self.update_count(item.category)
        if item.category == 'cybersecurity' and self.notifications and not item.replay:
            try:
                self.notification_queue.put_nowait(item)
            except asyncio.QueueFull:
                self.note = 'Notification backlog full; alert remains in Cybersecurity panel'

    def update_count(self, category: str) -> None:
        count = len(self.items[category])
        suffix = '  /  CRITICAL ONLY' if category == 'cybersecurity' and self.critical_only else ''
        self.query_one(f'#title-{category}', Static).update(f'{CATEGORIES[category]}  [{count}]{suffix}')

    async def notification_loop(self) -> None:
        def send(item: NewsItem) -> None:
            from plyer import notification
            notification.notify(title=f'NEWSWIRE | CVSS {item.severity:.1f}',
                                message=f'{item.source}: {item.title}'[:240],
                                app_name='NEWSWIRE', timeout=8)
        while True:
            item = await self.notification_queue.get()
            try:
                await asyncio.to_thread(send, item)
            except Exception as exc:
                self.note = f'Desktop notification unavailable: {type(exc).__name__}'
                self.refresh_status()
            finally:
                self.notification_queue.task_done()

    def selected_item(self) -> NewsItem | None:
        focused = self.screen.focused
        if isinstance(focused, ListView) and isinstance(focused.highlighted_child, NewsRow):
            return focused.highlighted_child.item
        return None

    def action_expand(self) -> None:
        if isinstance(self.screen, Detail):
            self.screen.dismiss()
            return
        if item := self.selected_item():
            self.push_screen(Detail(item))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, NewsRow):
            self.push_screen(Detail(event.item.item))

    async def action_open_url(self) -> None:
        if item := self.selected_item():
            await self.open_item_url(item)

    async def open_item_url(self, item: NewsItem) -> None:
        # No GUI or browser is used by the dashboard. An explicitly invoked
        # terminal browser temporarily owns the terminal, then returns to Textual.
        command = shlex.split(self.url_command, posix=True) if self.url_command else []
        if not command:
            found = next((shutil.which(name) for name in ('w3m', 'lynx', 'links') if shutil.which(name)), None)
            if found:
                command = [found]
        if not command:
            self.notify('Install w3m/lynx/links or set --url-command. URL is available in Expand.', title='Terminal browser unavailable', timeout=8)
            return
        try:
            with self.suspend():
                await asyncio.to_thread(subprocess.run, [*command, item.url], check=False)
        except Exception as exc:
            self.notify(f'Could not open terminal browser: {type(exc).__name__}', severity='error')

    async def action_filter(self) -> None:
        self.critical_only = not self.critical_only
        panel = self.query_one('#cybersecurity', ListView)
        previous = panel.highlighted_child
        selected_id = previous.item.id if isinstance(previous, NewsRow) else None
        await panel.clear()
        visible = [item for item in self.items['cybersecurity'] if not self.critical_only or item.critical]
        await panel.extend(NewsRow(item) for item in visible)
        if visible:
            panel.index = next((i for i, item in enumerate(visible) if item.id == selected_id), 0)
        self.update_count('cybersecurity')

    def action_channel(self, category: str) -> None:
        self.query_one(f'#{category}', ListView).focus()

    def action_latest(self) -> None:
        panel = self.screen.focused
        if isinstance(panel, ListView) and panel.children:
            panel.index = len(panel.children) - 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('uri', nargs='?', default='ws://newswire.local:81/')
    parser.add_argument('--no-notifications', action='store_true')
    parser.add_argument('--no-boot', action='store_true')
    parser.add_argument('--heartbeat-timeout', type=float, default=75)
    parser.add_argument('--url-command', help='Terminal browser command, e.g. "w3m". URL is appended safely.')
    args = parser.parse_args()
    try:
        parsed = urlsplit(args.uri)
        valid = parsed.scheme in ('ws', 'wss') and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid:
        parser.error('uri must be a ws:// or wss:// URL')
    if not math.isfinite(args.heartbeat_timeout) or args.heartbeat_timeout < 35:
        parser.error('--heartbeat-timeout must be at least 35 seconds (device heartbeat is 30s)')
    Newswire(args.uri, notifications=not args.no_notifications,
             heartbeat_timeout=args.heartbeat_timeout, url_command=args.url_command,
             boot=not args.no_boot).run()


if __name__ == '__main__':
    main()
