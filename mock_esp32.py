"""Terminal-only simulated ESP32; no hardware or external feeds required."""
import argparse
import asyncio
import json
import time
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

SAMPLES = [
    ('cybersecurity', '[SIMULATED] Critical remote access vulnerability', 'CISA KEV', 9.8),
    ('networking', '[SIMULATED] Operators discuss IPv6 rollout lessons', 'APNIC', None),
    ('tech', '[SIMULATED] Open source tools lead today’s tech discussion', 'Hacker News', None),
    ('privacy', '[SIMULATED] A closer look at data retention policies', 'EFF', None),
    ('cybersecurity', '[SIMULATED] High severity service vulnerability', 'NVD', 7.5),
]


async def main(args):
    started = time.monotonic()
    async def client(ws):
        connected = time.monotonic()
        last_beat = -100.0
        index = 0
        try:
            while True:
                elapsed = time.monotonic() - connected
                if args.drop_after and elapsed >= args.drop_after:
                    await ws.close(code=1012, reason='Simulated WiFi loss')
                    return
                if time.monotonic() - last_beat >= args.heartbeat and not (args.silent_after and elapsed >= args.silent_after):
                    await ws.send(json.dumps({'type': 'heartbeat', 'protocol': 1,
                        'uptime': int(time.monotonic()-started), 'timestamp': int(time.time()),
                        'feeds': {k: 'simulated' for k in ('hn', 'nvd', 'cisa', 'register', 'apnic', 'eff')}}))
                    last_beat = time.monotonic()
                category, title, source, score = SAMPLES[index % len(SAMPLES)]
                await ws.send(json.dumps({'type': 'item', 'protocol': 1,
                    'id': f'demo-{index}', 'category': category, 'title': title,
                    'source': source, 'url': f'https://example.com/news/{index}',
                    'severity': score, 'timestamp': int(time.time()), 'replay': False}))
                index += 1
                await asyncio.sleep(args.interval)
        except ConnectionClosed:
            pass
    async with serve(client, '127.0.0.1', args.port):
        print(f'Simulated ESP32 at ws://127.0.0.1:{args.port}/ (Ctrl+C to stop)', flush=True)
        await asyncio.Future()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--interval', type=float, default=3)
    p.add_argument('--heartbeat', type=float, default=30)
    p.add_argument('--drop-after', type=float, default=0, help='Close connection after N seconds')
    p.add_argument('--silent-after', type=float, default=0, help='Stop heartbeats but keep sending items')
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
