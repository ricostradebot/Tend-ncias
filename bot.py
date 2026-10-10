import os, json, time, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

COINS = ["NEAR", "SUI", "HYPE", "UNI", "SOL", "AVAX", "ADA", "DOT", "LINK", "AAVE"]
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")
STATE_FILE = "state.json"
COOLDOWN = 4 * 3600
TZ = ZoneInfo("America/Sao_Paulo")
BEATS = [(8, 30), (16, 0), (21, 0)]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def candles(coin, bar):
    url = f"https://www.okx.com/api/v5/market/candles?instId={coin}-USDT&bar={bar}&limit=120"
    d = [c for c in get(url)["data"] if c[8] == "1"]  # só candles fechados
    d.reverse()
    return [(float(c[1]), float(c[4]), float(c[5])) for c in d]  # (abertura, fechamento, volume)


def rsi(cl, n=14):
    g = l = 0
    for i in range(1, n + 1):
        d = cl[i] - cl[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    g /= n
    l /= n
    out = [None] * n
    out.append(100 if l == 0 else 100 - 100 / (1 + g / l))
    for i in range(n + 1, len(cl)):
        d = cl[i] - cl[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        out.append(100 if l == 0 else 100 - 100 / (1 + g / l))
    return out


def ema(v, n):
    k = 2 / (n + 1)
    e = [v[0]]
    for x in v[1:]:
        e.append(x * k + e[-1] * (1 - k))
    return e


def analyze(coin):
    c1 = candles(coin, "1H")
    c4 = candles(coin, "4H")
    if len(c1) < 40 or len(c4) < 20:
        return None
    cl = [x[1] for x in c1]
    o, c, v = c1[-1]
    avg = sum(x[2] for x in c1[-21:-1]) / 20
    r = rsi(cl)
    r4 = rsi([x[1] for x in c4])[-1]
    e = ema(cl, 9)
    up = e[-1] > e[-2]
    volx = v / avg if avg else 0

    side = level = None
    if r[-1] < 32 and r[-1] > r[-2]:
        side, level = "COMPRA", "PRE"
    if r[-2] < 30 <= r[-1] and c > o and up and volx > 1 and r4 < 40:
        side, level = "COMPRA", "MOMENTO"
    if r[-1] > 68 and r[-1] < r[-2]:
        side, level = "VENDA", "PRE"
    if r[-2] > 70 >= r[-1] and c < o and not up and volx > 1 and r4 > 60:
        side, level = "VENDA", "MOMENTO"
    if not side:
        return None
    return side, level, c, r[-1], volx


def send(text, silent=False):
    if not TOKEN or not CHAT:
        print(text)
        return
    data = urllib.parse.urlencode({
        "chat_id": CHAT,
        "text": text,
        "disable_notification": "true" if silent else "false",
    }).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data, timeout=20)


def load():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("alerts", {})
    s.setdefault("hb", [])
    return s


def save(st):
    new = json.dumps(st, indent=1)
    try:
        with open(STATE_FILE) as f:
            if f.read() == new:
                return
    except Exception:
        pass
    with open(STATE_FILE, "w") as f:
        f.write(new)


def heartbeat(now, st):
    for h, m in BEATS:
        key = f"{now:%Y-%m-%d}-{h}{m}"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if 0 <= (now - target).total_seconds() < 3600 and key not in st["hb"]:
            send("✅ Estou rodando")
            st["hb"] = (st["hb"] + [key])[-10:]


def main():
    now = datetime.now(TZ)
    ts = time.time()
    st = load()
    heartbeat(now, st)

    try:
        btc = candles("BTC", "1H")
        btc_drop = btc[-1][1] / btc[-5][1] - 1
    except Exception:
        btc_drop = 0

    for coin in COINS:
        try:
            res = analyze(coin)
        except Exception as ex:
            print(coin, "erro:", ex)
            continue
        if not res:
            continue
        side, level, price, r1, volx = res
        if side == "COMPRA" and btc_drop < -0.03:
            continue  # BTC despencando: segura compras
        last = st["alerts"].get(coin)
        if last and ts - last["t"] < COOLDOWN and not (level == "MOMENTO" and last["l"] == "PRE"):
            continue

        titulo = f"🚨 MOMENTO DE {side}" if level == "MOMENTO" else f"🔥 TÁ QUENTE ({side})"
        msg = (f"{titulo}\n{coin} (1h)\nPreço: US$ {price:,.4f}\n"
               f"RSI: {r1:.0f}\nVolume: {volx:.1f}x a média")
        silent = (0 <= now.hour < 7) and level == "PRE"
        send(msg, silent)
        st["alerts"][coin] = {"t": ts, "l": level}

    save(st)


if __name__ == "__main__":
    main()
