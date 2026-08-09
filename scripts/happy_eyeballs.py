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
import os, socket, threading, queue, time

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

# --- remembered pools -------------------------------------------------------
# 2026-08-09. DNS hands out eight addresses that always share one /24, so the
# eight are one POP, and 4.7% of the day that POP answers nobody: every dial
# fails together at exactly TOTAL + hedge = 7.00s. A reader waits 6.25s
# (wall.RADAR_WAIT_UNKNOWN), so a fallback that starts AFTER the failure is
# 0.75s too late for the reader who triggered it -- measured, not assumed.
# The only shape that can help them is to put the previously-good addresses in
# the SAME race. Measured 8/9: bytes fetched from the previous pool during an
# outage rendered 44/44 across eleven episodes and eight radars, so an old
# address is not a degraded source, it is the same CDN reached another way.
#
# Two traps this code exists to avoid:
#   * racers used to be infos[:MAX_PARALLEL] and DNS returns exactly 8 with
#     MAX_PARALLEL = 8, so anything appended before the slice is dropped in
#     silence and the whole feature looks inert. Extras are added AFTER.
#   * install() replaces socket.create_connection process-wide, so an
#     unscoped change would also alter the weather fetch on the reader path.
#     Only hosts in _MEM_HOSTS get remembered or augmented.
_MEM_HOSTS = set(h.strip() for h in os.environ.get(
    "RUNEMAP_POOL_MEMORY_HOSTS", "meteorology.caiyuncdn.com").split(",") if h.strip())
_MEM_KEEP = int(os.environ.get("RUNEMAP_POOL_MEMORY_KEEP", "2"))
_MEM = {}
_MEM_LOCK = threading.Lock()


def _remember(host, entry):
    """Record an address that just completed a connect, newest first."""
    if host not in _MEM_HOSTS:
        return
    sa = entry[4]
    with _MEM_LOCK:
        kept = [e for e in _MEM.get(host, []) if e[4] != sa]
        kept.insert(0, entry)
        _MEM[host] = kept[:_MEM_KEEP]


def _extras(host, racers):
    """Remembered addresses that today's DNS did not offer."""
    if host not in _MEM_HOSTS:
        return []
    with _MEM_LOCK:
        mem = list(_MEM.get(host, []))
    have = set(r[4] for r in racers)
    return [e for e in mem if e[4] not in have]


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
    if len(infos) <= 1 and not _extras(host, infos):
        # One address and nothing remembered: the race has a single runner, so
        # let the stdlib do it. With extras there IS a race, and taking this
        # shortcut would skip them in silence -- the failure mode being fixed.
        #
        # The winner is still recorded here. Without this the memory could only
        # ever bootstrap while DNS was handing out two or more addresses, so a
        # host that answered with one address would be forgotten the moment it
        # stopped resolving -- and nothing would look broken, which is how this
        # kind of gap survives.
        conn = _real(address, timeout, source_address, **kw)
        try:
            _remember(host, (conn.family, conn.type, conn.proto, "", conn.getpeername()))
        except OSError:
            pass
        return conn

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
            q.put((True, s, sa))
        except OSError as e:
            try:
                s.close()
            except OSError:
                pass
            q.put((False, e, sa))

    racers = infos[:MAX_PARALLEL] + _extras(host, infos[:MAX_PARALLEL])
    for fam, typ, proto, _canon, sa in racers:
        threading.Thread(target=dial, args=(fam, typ, proto, sa), daemon=True).start()

    deadline = time.time() + total
    last_err = None
    for _ in range(len(racers)):
        left = deadline - time.time()
        if left <= 0:
            break
        try:
            ok, val, sa = q.get(timeout=left)
        except queue.Empty:
            break
        if ok:
            done.set()
            val.settimeout(t)
            _remember(host, (val.family, val.type, val.proto, "", sa))
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
