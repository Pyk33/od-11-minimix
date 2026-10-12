# Olle's Mini-Mix – OB-4 Magic Tape & Looper

Inspirerad av Teenage Engineerings ikoniska **OB-4 "Magic Radio"** är Olle's Mini-Mix utrustad med en kontinuerlig 15-minuters rullande bandbuffert i minnet och realtids-DSP som gör det möjligt att spola i realtidsljud, loopa och sömlöst fortsätta lyssna.

---

## 🎛️ Lägen & Kontroller

Mini-Mix har tre rena driftslägen:
- **`VOL`**: Normal lyssning med volymkontroll.
- **`TAPE`**: 1:1 vinyl slipmat scratch, spolning och snabb framåtspolning till LIVE (t-0).
- **`LOOP`**: Instant looper med framåtriktad tidsförlängning och flyttbart loopfönster.

```
[ VOL ] ──(Håll Next >0.5s)──> [ TAPE ] ──(Klicka Next)──> [ LOOP ]
   ▲                              │                           │
   └────────(Håll Next >0.5s)─────┴───────────────────────────┘
```

---

### 1. `VOL` (Standardläge / Normal Lyssning)
Normal uppspelning från Spotify Connect eller AirPlay.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder** | Vrid medurs / moturs | Höj / sänk volym (0–85 %). Stor TE-volymoverlay visas på skärmen. |
| **Play/Pause (`IO22`)** | Klick | Play / Pause (Spotify / AirPlay). |
| | Håll (>0.5 s) | Mute / Unmute (eller hoppa till LIVE om du lyssnar med bandfördröjning). |
| **Next (`IO23`)** | Klick | Nästa låt (Spotify / AirPlay). |
| | Håll (>0.5 s) | **Gå in i OB-4 `TAPE` Mode!** |

---

### 2. `TAPE` (OB-4 Magic Tape: Scrub, Rewind & Spool till LIVE)
En kontinuerlig 15-minuters bandbuffert spelar in all musik i realtid i 48 kHz stereo. I detta läge kan du spola bakåt och framåt i tiden med autentisk 1:1 slipmat-känsla och mekanisk tröghet.

- **Display:** Visar två animerade rullbandshjul som snurrar i takt med bandhastigheten, tidsskillnad mot live (`LIVE` eller `-MM:SS`), och bandhuvud.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder** | Vrid moturs | **Scratcha bakåt i musikhistorien!** (1:1 autentisk vinylkänsla). |
| | Vrid medurs | **Super Spool framåt mot LIVE:** Snabb vridning accelererar spolningen exponentiellt (upp till 30x) så du sveper 30–60 sekunder på nolltid. Spärras och fastnar bergfast vid LIVE (t-0). |
| **Play/Pause (`IO22`)** | Klick | **1-KLICK DJ MERGE TO LIVE!** Om du ligger bakom nutid görs en mjuk equal-power DJ-crossfade som stilrent mixar bandet in i realtidsströmmen! Vid LIVE: Tape Stop motorbroms. |
| | Håll (>0.5 s) | **Direkt snitt till LIVE:** Omedelbart klipp fram till realtidsströmmen utan fade. |
| **Next (`IO23`)** | Klick | Växla till **`LOOP` Mode**. |
| | Håll (>0.5 s) | **Återgå till `VOL` Mode:** Låten fortsätter spela sömlöst framåt från exakt den punkt nålen befinner sig på! |

---

### 3. `LOOP` (Instant Looper: Framåt-expansion & Glidande Fönster)
Fångar omedelbart en slinga av musiken och upprepar den med klickfria equal-power crossfades.

- **Display:** Visar aktiv slinga, looplängd i sekunder, aktivt rattläge (`[SIZE] MOVE` eller `SIZE [MOVE]`), samt en faslåst loopindikator som rör sig i perfekt takt med takten i högtalaren.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Play/Pause (`IO22`)** | Klick | **Växla rattläge mellan `SIZE` och `MOVE`!** |
| | Håll (>0.5 s) | **Reverse Loop:** Spela loopen baklänges (`REV`)! |
| **Rotary Encoder (i `SIZE`)** | Vrid | **Öka / minska looptid:** När du ökar längden läggs den nya tiden till **framåt i låten** så att kommande takter kommer in i loopen! Stegar mellan 0.125 s upp till 16.0 s. |
| **Rotary Encoder (i `MOVE`)** | Vrid | **Flytta loopen längs tidslinjen:** Skjuter hela loopfönstret framåt eller bakåt genom musiken så du kan hitta det perfekta partiet att loopa. |
| **Next (`IO23`)** | Klick | Växla tillbaka till **`TAPE` Mode**. |
| | Håll (>0.5 s) | **Återgå till `VOL` Mode:** Musiken fortsätter spela sömlöst framåt från loopens position in i resten av låten! |

---

## ⚡ Säker avstängning
Oavsett vilket läge du befinner dig i:
- **Håll båda knapparna samtidigt i 3 sekunder**: Skärmen visar *"SHUTTING DOWN..."* och Pi:n stängs av säkert (`sudo shutdown -h now`).
