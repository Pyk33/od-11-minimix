#!/usr/bin/env python3
"""
Bygger hitster_songs.json åt Hitster-minispelet.

Användning:
    python3 hitster_import.py --official                 # Importerar alla 4 officiella Hitster-spellistor (~400 låtar)
    python3 hitster_import.py <spellista-URL | CSV-fil>  # Importerar specifik spellista eller CSV

Hämtar låtar:
  * Officiella Hitster-spellistor direkt via Spotifys embed-infrastruktur (kräver INGA API-nycklar!)
  * Exportify-CSV (https://exportify.net)
  * Spotify API / Client Credentials (om konfigurerat)

Rätt utgivningsår:
  För att garantera korrekta original-årtal (och undvika att remasters och 'Greatest Hits'-album
  från 2011 förstör låtar från 1975) slår scriptet upp låtens ursprungliga inspelnings-/utgivningsår
  via Apple Music/iTunes och MusicBrainz. Egna justeringar kan läggas i hitster_overrides.json.
"""
import argparse
import csv
import json
import os
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from pathlib import Path

HERE = Path(__file__).resolve().parent
MB_CACHE_FILE = HERE / "hitster_mb_cache.json"
ITUNES_CACHE_FILE = HERE / "hitster_itunes_cache.json"
OVERRIDES_FILE = HERE / "hitster_overrides.json"

OFFICIAL_PLAYLISTS = [
    ("Hitster Original", "0Mpj1KwRmY2pHzmj7mfbdh"),
    ("Hitster Bingo", "0BRAHVe41SRLfK1EVsmGyH"),
    ("Hitster Guilty Pleasures", "3wUKjSzUUyJyy8OXO4AtJ7"),
    ("Hitster Summer Party", "2hZhVv7z6cpGcRBEgvlXLz"),
]

SUSPECT_ALBUM = re.compile(
    r"remaster|greatest|best of|hits|collection|anthology|essential|deluxe|anniversary|"
    r"compilation|gold|platinum|ultimate|definitive|\blive\b|karaoke|tribute|the very best|"
    r"expanded|legacy|years|decade|\bnow\b|top \d+|#1",
    re.I,
)
BAD_RECORDING = re.compile(
    r"\b(live|demo|karaoke|instrumental|acoustic|remix|cover|a cappella|session)\b", re.I
)

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()


# --------------------------------------------------------------------------- #
# Hjälpfunktioner
# --------------------------------------------------------------------------- #
def load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s)


def clean_title(title: str) -> str:
    t = title or ""
    t = re.sub(
        r"\s*[-–]\s*(\d{4}\s+)?(remaster(ed)?|digitally remastered|single version|"
        r"radio edit|mono|stereo|album version|original mix).*$",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"\s*[\(\[](feat\.?|ft\.?|with|remaster(ed)?|\d{4} remaster|live|mono|stereo)[^\)\]]*[\)\]]",
        "",
        t,
        flags=re.I,
    )
    return t.strip()


def parse_year(date: str):
    m = re.match(r"(\d{4})", date or "")
    return int(m.group(1)) if m else None


def http_json(url, headers=None, data=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# Spotify spellist-hämtare
# --------------------------------------------------------------------------- #
def playlist_id(s: str) -> str:
    m = re.search(r"playlist[/:]([A-Za-z0-9]+)", s)
    return m.group(1) if m else s.strip()


def fetch_embed_playlist(pid: str):
    """Hämtar låtar direkt från Spotifys öppna embed-data (kräver inga API-nycklar)."""
    url = f"https://open.spotify.com/embed/playlist/{pid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=15, context=SSL_CTX).read().decode("utf-8")
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not m:
            return []
        data = json.loads(m.group(1))
        tl = data["props"]["pageProps"]["state"]["data"]["entity"].get("trackList", [])
        out = []
        for t in tl:
            uri = t.get("uri")
            if uri and uri.startswith("spotify:track:"):
                out.append({
                    "uri": uri,
                    "title": t.get("title", ""),
                    "artist": t.get("subtitle", "").replace("\xa0", " "),
                    "duration_ms": t.get("duration") or 0,
                    "album": "",
                    "spotify_year": None,
                })
        return out
    except Exception as e:
        print(f"Kunde inte läsa embed för {pid}: {e}")
        return []


def read_exportify_csv(path: str):
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            def g(*names):
                for n in names:
                    if row.get(n):
                        return row[n]
                return ""
            uri = g("Track URI", "Spotify URI", "uri")
            if not uri.startswith("spotify:track:"):
                continue
            artists = g("Artist Name(s)", "Artist Name", "Artists").replace(";", ", ")
            out.append({
                "uri": uri,
                "title": g("Track Name", "Name", "Title"),
                "artist": artists,
                "album": g("Album Name", "Album"),
                "spotify_year": parse_year(g("Album Release Date", "Release Date")),
                "duration_ms": int(g("Duration (ms)", "Duration_ms") or 0),
            })
    return out


# --------------------------------------------------------------------------- #
# Årtal-uppslagning (iTunes original master + MusicBrainz)
# --------------------------------------------------------------------------- #
class YearResolver:
    def __init__(self):
        self.itunes_cache = {}
        if ITUNES_CACHE_FILE.exists():
            try:
                self.itunes_cache = json.loads(ITUNES_CACHE_FILE.read_text())
            except Exception:
                self.itunes_cache = {}

        self.mb_cache = {}
        if MB_CACHE_FILE.exists():
            try:
                self.mb_cache = json.loads(MB_CACHE_FILE.read_text())
            except Exception:
                self.mb_cache = {}

        self._last_mb = 0.0

    def save(self):
        ITUNES_CACHE_FILE.write_text(json.dumps(self.itunes_cache, ensure_ascii=False, indent=0))
        MB_CACHE_FILE.write_text(json.dumps(self.mb_cache, ensure_ascii=False, indent=0))

    def lookup_itunes(self, artist: str, title: str):
        """Hämtar originalutgivningsår från Apple Music / iTunes."""
        primary_artist = artist.split(",")[0].split("&")[0].strip()
        ctitle = clean_title(title)
        cache_key = f"{norm(primary_artist)}|{norm(ctitle)}"
        if cache_key in self.itunes_cache:
            return self.itunes_cache[cache_key]

        term = urllib.parse.quote(f"{primary_artist} {ctitle}")
        url = f"https://itunes.apple.com/search?term={term}&entity=song&limit=5"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
                data = json.loads(r.read().decode("utf-8"))
            results = data.get("results", [])
            matched_year = None
            nt = norm(ctitle)
            for item in results:
                tname = norm(clean_title(item.get("trackName", "")))
                aname = norm(item.get("artistName", ""))
                if (nt in tname or tname in nt) and (norm(primary_artist) in aname or aname in norm(primary_artist)):
                    rel = item.get("releaseDate", "")
                    y = parse_year(rel)
                    if y and 1920 <= y <= time.gmtime().tm_year:
                        matched_year = y
                        break
            self.itunes_cache[cache_key] = matched_year
            return matched_year
        except Exception:
            return None

    def lookup_musicbrainz(self, artist: str, title: str):
        """Hämtar tidigaste studioinspelningsår från MusicBrainz."""
        primary = artist.split(",")[0].split("&")[0].strip()
        ctitle = clean_title(title)
        key = f"{norm(primary)}|{norm(ctitle)}"
        if key in self.mb_cache:
            return self.mb_cache[key]

        wait = 1.1 - (time.monotonic() - self._last_mb)
        if wait > 0:
            time.sleep(wait)
        self._last_mb = time.monotonic()

        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        q = f'recording:"{esc(ctitle)}" AND artist:"{esc(primary)}"'
        url = (
            "https://musicbrainz.org/ws/2/recording?fmt=json&limit=100&query="
            + urllib.parse.quote(q)
        )
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "OD11Minimix/1.0 (hitster year lookup; github.com/Pyk33/od-11-minimix)"},
            )
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
                d = json.loads(r.read().decode("utf-8"))
            years = []
            nt, na = norm(ctitle), norm(primary)
            for rec in d.get("recordings", []):
                if rec.get("score", 0) < 85:
                    continue
                rtitle = norm(rec.get("title", ""))
                if nt not in rtitle and rtitle not in nt:
                    continue
                if BAD_RECORDING.search(rec.get("disambiguation", "") or ""):
                    continue
                y = parse_year(rec.get("first-release-date"))
                if y and 1920 <= y <= time.gmtime().tm_year:
                    years.append(y)
            years.sort()
            res = years[0] if years else None
            self.mb_cache[key] = res
            return res
        except Exception:
            return None

    def resolve(self, song, override=None):
        if override:
            return override, True, "override"

        # 1. Försök med iTunes (har originalsingel-datum även på samlingsalbum)
        it_y = self.lookup_itunes(song["artist"], song["title"])

        # 2. Om iTunes hittades och verkar rimligt
        if it_y:
            return it_y, True, f"iTunes {it_y}"

        # 3. Fallback: MusicBrainz
        mb_y = self.lookup_musicbrainz(song["artist"], song["title"])
        if mb_y:
            return mb_y, True, f"MusicBrainz {mb_y}"

        # 4. Fallback: Spotify år om ej misstänkt album
        sy = song.get("spotify_year")
        suspect = bool(SUSPECT_ALBUM.search(song.get("album", "")))
        if sy and not suspect:
            return sy, True, f"Spotify {sy}"

        return sy or None, False, "osäker"


# --------------------------------------------------------------------------- #
# Huvudprogram
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", help="Spotify-spellista (URL/ID) eller Exportify-CSV")
    ap.add_argument("--official", action="store_true", help="Hämta automatiskt alla 4 officiella Hitster-spellistor")
    ap.add_argument("--out", default=str(HERE / "hitster_songs.json"))
    args = ap.parse_args()
    load_env()

    raw_tracks = []

    # Om --official eller inga källor angivna: hämta alla officiella Hitster-spellistor
    if args.official or not args.sources:
        print("Hämtar officiella Hitster-spellistor...")
        for name, pid in OFFICIAL_PLAYLISTS:
            pl_tracks = fetch_embed_playlist(pid)
            print(f"  {name}: {len(pl_tracks)} låtar")
            raw_tracks.extend(pl_tracks)

    for src in args.sources:
        if Path(src).is_file() and src.lower().endswith(".csv"):
            raw_tracks.extend(read_exportify_csv(src))
        elif "open.spotify.com" in src or len(src) == 22:
            pid = playlist_id(src)
            pl_tracks = fetch_embed_playlist(pid)
            print(f"  Spellista {pid}: {len(pl_tracks)} låtar")
            raw_tracks.extend(pl_tracks)

    if not raw_tracks:
        sys.exit("Inga låtar hittades att importera.")

    # Deduplicera på URI
    unique_tracks = {}
    for t in raw_tracks:
        if t["uri"] not in unique_tracks:
            unique_tracks[t["uri"]] = t

    tracks = list(unique_tracks.values())
    print(f"\nTotalt {len(tracks)} unika låtar. Slår upp och verifierar original-årtal...")

    overrides = {}
    if OVERRIDES_FILE.exists():
        try:
            overrides = json.loads(OVERRIDES_FILE.read_text())
        except Exception:
            overrides = {}

    resolver = YearResolver()
    results = {}
    confident_count = 0

    for i, t in enumerate(tracks, 1):
        clean_t = clean_title(t["title"])
        year, sure, note = resolver.resolve(t, overrides.get(t["uri"]))

        if year:
            results[t["uri"]] = {
                "uri": t["uri"],
                "title": clean_t,
                "artist": t["artist"],
                "year": year,
                "confident": sure,
                "duration_ms": t["duration_ms"],
                "source_note": note,
            }
            if sure:
                confident_count += 1
            status_tag = "OK" if sure else "??"
            print(f"[{i:3d}/{len(tracks)}] {status_tag} {year}  {t['artist']} - {clean_t}  ({note})")
        else:
            print(f"[{i:3d}/{len(tracks)}] SKIP     {t['artist']} - {clean_t}  ({note})")

        if i % 15 == 0:
            resolver.save()
        time.sleep(0.05)

    resolver.save()

    out_file = Path(args.out)
    out_file.write_text(json.dumps(list(results.values()), ensure_ascii=False, indent=2))
    print(f"\nFärdigt! Sparade {len(results)} låtar till {out_file}.")
    print(f"{confident_count} säkra verifierade låtar redo att spelas i Hitster på din OD-11!")


if __name__ == "__main__":
    main()
