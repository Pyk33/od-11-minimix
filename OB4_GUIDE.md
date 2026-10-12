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

## 🖥️ Dedikerad 1 cm Kontroll-Sidebar (Alltid på skärmen)
Till höger på OLED-skärmen finns en dedikerad 1 cm bred kolumn (`x=84..127`) som alltid visar vad de 5 kontrollerna gör i det aktuella läget:
1. `[◎]` **Rotor (Ratten):** Styr volym, bandspolning eller looplängd/position.
2. `[■|□]` **Övre kort (Tap):** Primär åtgärd (Play/Pause, DJ Merge to LIVE, växla loopläge).
3. `[■|□]_` **Övre långt (Hold):** Sekundär åtgärd (Mute, direkt snitt till LIVE, Reverse loop).
4. `[□|■]` **Nedre kort (Tap):** Nästa låt eller hoppa mellan kreativa lägen (`TAPE` ↔ `LOOP`).
5. `[□|■]_` **Nedre långt (Hold):** Växla in i `TAPE` eller återgå till `VOL`.

---

### 1. `VOL` (Standardläge / Normal Lyssning)
Normal uppspelning från Spotify Connect eller AirPlay.

| Kontroll | Symbol | Åtgärd | Funktion |
|---|---|---|---|
| **Rotary Encoder** | `[◎]` | Vrid | Höj / sänk volym (0–85 %). Stor TE-volymoverlay. |
| **Övre knapp (`IO22`)** | `[■|□]` | Klick | Play / Pause. |
| | `[■|□]_` | Håll (>0.5 s) | Mute / Unmute (eller LIVE vid eftersläpning). |
| **Nedre knapp (`IO23`)** | `[□|■]` | Klick | Nästa låt (Spotify / AirPlay). |
| | `[□|■]_` | Håll (>0.5 s) | **Gå in i OB-4 `TAPE` Mode!** |

---

### 2. `TAPE` (OB-4 Magic Tape: Scrub, Rewind & Spool till LIVE)
En kontinuerlig 15-minuters bandbuffert spelar in all musik i realtid i 48 kHz stereo.

- **Vänster visning (`0..84 px`):** Visar animerade rullbandshjul som snurrar i takt med bandhastigheten samt tidsskillnad mot live (`LIVE` eller `-MM:SS`).
- **Höger sidebar (`85..127 px`):** Visar `SCRUB`, `LIVE`/`PAUS`, `CUT`, `LOOP`, `VOL`.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder** | Vrid moturs | **Scratcha bakåt i musikhistorien!** (1:1 autentisk vinylkänsla). |
| | Vrid medurs | **Super Spool framåt mot LIVE:** Snabb vridning accelererar spolningen exponentiellt (upp till 30x) så du sveper 30–60 sekunder på nolltid. Spärras och fastnar bergfast vid LIVE (t-0). |
| **Övre knapp (`IO22`)** | Klick | **1-KLICK DJ MERGE TO LIVE!** Om du ligger bakom nutid görs en mjuk equal-power DJ-crossfade som stilrent mixar bandet in i realtidsströmmen! Vid LIVE: Vanlig **Play / Pause** (pausar musiken och visar `PAUSED`). |
| | Håll (>0.5 s) | **Direkt snitt till LIVE:** Omedelbart klipp fram till realtidsströmmen utan fade. |
| **Nedre knapp (`IO23`)** | Klick | Växla till **`LOOP` Mode**. |
| | Håll (>0.5 s) | **Återgå till `VOL` Mode:** Låten fortsätter spela sömlöst framåt från exakt den punkt nålen befinner sig på! |

---

### 3. `LOOP` (Instant Looper: Framåt-expansion & Glidande Fönster)
Fångar omedelbart en slinga av musiken och upprepar den med klickfria equal-power crossfades.

- **Display:** Visar aktiv slinga, looplängd i sekunder, aktivt rattläge (`[SIZE] MOVE` eller `SIZE [MOVE]`), samt en faslåst loopindikator som rör sig i perfekt takt med takten i högtalaren.
- **Trafikljusikon (nedre högra hörnet):**
  - Övre knapp fylld + `SWAP`: Klicka övre knappen för att växla ratten mellan `[SIZE]` (längd) och `[MOVE]` (flytta loopen).

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Övre knapp (`IO22`)** | Klick | **Växla rattläge mellan `SIZE` och `MOVE` (`SWAP`)!** |
| | Håll (>0.5 s) | **Reverse Loop:** Spela loopen baklänges (`REV`)! |
| **Rotary Encoder (i `SIZE`)** | Vrid | **Öka / minska looptid:** När du ökar längden läggs den nya tiden till **framåt i låten** så att kommande takter kommer in i loopen! Stegar mellan 0.125 s upp till 16.0 s. |
| **Rotary Encoder (i `MOVE`)** | Vrid | **Flytta loopen längs tidslinjen:** Skjuter hela loopfönstret framåt eller bakåt genom musiken så du kan hitta det perfekta partiet att loopa. |
| **Nedre knapp (`IO23`)** | Klick | Växla tillbaka till **`TAPE` Mode**. |
| | Håll (>0.5 s) | **Återgå till `VOL` Mode:** Musiken fortsätter spela sömlöst framåt från loopens position in i resten av låten! |

---

## ⚡ Säker avstängning
Oavsett vilket läge du befinner dig i:
- **Håll båda knapparna samtidigt i 3 sekunder**: Skärmen visar *"SHUTTING DOWN..."* och Pi:n stängs av säkert (`sudo shutdown -h now`).
