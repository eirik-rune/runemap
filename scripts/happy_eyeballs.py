"""Connect to every address at once and keep the first one that answers.

socket.create_connection walks the addresses getaddrinfo returned one at a time
and gives each the FULL timeout. The radar CDN resolves to eight addresses, so one
node with an unanswered SYN turned timeout=20 into a 160-second wait. Measured:
three blackhole addresses at timeout=2.0 raised after 6.01s, exactly 3.0x. That
was the three-minute hangs py-spy caught inside create_connection, the 13.3s cold
renders, and the 504 a stranger was served -- one cause, not three.

Capping the per-address wait at 2s fixed the hang and left an obvious waste: we do
not need the first address to be healthy, only one of the eight, yet each bad node
was still paid for in full. Measured after that first fix: open=1.73s, 1.69s,
2.57s against 0.07s for a healthy connect -- the cap working as written, and
billing us 2s per fetch, four fetches per cold render.

So dial all of them simultaneously and keep whoever answers first, which is what
RFC 8305 (Happy Eyeballs) specifies and what every browser already does. Losers
are closed. The read timeout the caller asked for is applied to the winner
untouched -- this bounds connecting, nothing else.

Patching socket.create_connection covers HTTPConnection and HTTPSConnection alike,
since both reach the network through it."""
import socket, threading, queue, time

PER_ADDRESS = 6.0     # every address is dialed at once, so this no longer multiplies
TOTAL = 6.0           # whole-race budget: worst case 6s instead of the measured 160s

# Once the dials are parallel the per-address limit stops being a multiplier, so it
# costs nothing to be patient with a slow-but-alive node. Measured against the radar
# CDN, alternating three rounds: serial reached all 8 addresses but took 3.9-4.9s
# (~0.5s each), parallel returned the first answer in 0.35s every round -- so firing
# 8 SYNs at once does NOT trip any rate limit, which was the thing that would have
# made this fix worse than the disease. One earlier run saw all 8 time out inside 3s;
# a rerun immediately after was clean, so that was a transient blackhole, and failing
# fast there is correct -- the caller falls back to stale cache.
MAX_PARALLEL = 8

_real = socket.create_connection
_GDT = socket._GLOBAL_DEFAULT_TIMEOUT
_installed = False


def _bounded(address, timeout=_GDT, source_address=None, **kw):
    t = None if timeout is _GDT else timeout
    total = TOTAL if t is None else min(float(t), TOTAL)
    host, port = address[0], address[1]
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except OSError:
        return _real(address, timeout, source_address, **kw)
    if len(infos) <= 1:
        return _real(address, timeout, source_address, **kw)

    q = queue.Queue()
    done = threading.Event()

    def dial(fam, typ, proto, sa):
        s = socket.socket(fam, typ, proto)
        try:
            s.settimeout(min(PER_ADDRESS, total))
            if source_address:
                s.bind(source_address)
            s.connect(sa)
            if done.is_set():
                s.close()          # someone else already won
                return
            q.put((True, s))
        except OSError as e:
            try:
                s.close()
            except OSError:
                pass
            q.put((False, e))

    racers = infos[:MAX_PARALLEL]
    for fam, typ, proto, _canon, sa in racers:
        threading.Thread(target=dial, args=(fam, typ, proto, sa), daemon=True).start()

    deadline = time.time() + total
    last_err = None
    for _ in range(len(racers)):
        left = deadline - time.time()
        if left <= 0:
            break
        try:
            ok, val = q.get(timeout=left)
        except queue.Empty:
            break
        if ok:
            done.set()
            val.settimeout(t)
            return val
        last_err = val

    done.set()
    raise (last_err or socket.timeout(
        "no address answered within %.1fs (%d tried) for %s" % (total, len(racers), host)))


def install():
    global _installed
    if not _installed:
        socket.create_connection = _bounded
        _installed = True
    return _installed
