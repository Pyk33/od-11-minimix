# Olle's Mini-Mix – OB-4 Magic Tape & Looper

Inspirerad av Teenage Engineerings ikoniska **OB-4 "Magic Radio"** är Olle's Mini-Mix utrustad med en kontinuerlig 15-minuters rullande bandbuffert i minnet och realtids-DSP som gör det möjligt att spola i realtidsljud, loopa och sömlöst fortsätta lyssna.

---

## 🎛️ Lägen & Kontroller

Mini-Mix har tre rena driftslägen:
- **`VOL`**: Normal lyssning med volymkontroll.
- **`TAPE`**: 1:1 vinyl slipmat scratch, spolning och snabb framåtspolning till LIVE (t-0).
- **`LOOP`**: Instant looper med framåtriktad tidsförlängning och flyttbart loopfönster.
- **`DJ`**: Klubb-filter (LPF / HPF) med resonant filterkurva och Turntable Tape Brake (skivbroms).

```
[ VOL ] ──(Håll Next >0.5s)──> [ TAPE ] ──(Klick Next)──> [ LOOP ] ──(Klick Next)──> [ DJ ]
   ▲                              │                           │                          │
   └────────(Håll Next >0.5s)─────┴───────────────────────────┴──────────────────────────┘
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
| **Övre knapp (`IO23`)** | `[■|□]` | Klick | Play / Pause. |
| | `[■|□]_` | Håll (>0.5 s) | Mute / Unmute (eller LIVE vid eftersläpning). |
| **Nedre knapp (`IO22`)** | `[□|■]` | Klick | Nästa låt (Spotify / AirPlay). |
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
| **Övre knapp (`IO23`)** | Klick | **1-KLICK DJ MERGE TO LIVE!** Om du ligger bakom nutid görs en mjuk equal-power DJ-crossfade som stilrent mixar bandet in i realtidsströmmen! Vid LIVE: Vanlig **Play / Pause** (pausar musiken och visar `PAUSED`). |
| | Håll (>0.5 s) | **Direkt snitt till LIVE:** Omedelbart klipp fram till realtidsströmmen utan fade. |
| **Nedre knapp (`IO22`)** | Klick | Växla till **`LOOP` Mode**. |
| | Håll (>0.5 s) | **Återgå till `VOL` Mode:** Låten fortsätter spela sömlöst framåt från exakt den punkt nålen befinner sig på! |

---

### 3. `LOOP` (Instant Looper: Framåt-expansion & Glidande Fönster)
Fångar omedelbart en slinga av musiken och upprepar den med klickfria equal-power crossfades.

- **Display:** 
  - Topprad: `LOOP` märke till vänster och båda lägena till höger med det aktiva markerat: `[SIZE] MOVE` eller `SIZE [MOVE]`.
  - Mitten: Loop-fönster med faslåst playhead och taktnischer som rör sig i perfekt synk med ljudet.
  - Under loopen: `LEN: <längd>` (hur mycket vi loopar, inkl. `REV`).
  - Nederst: **Låtens tidslinje (Timeline)** där loopen visas som en interaktiv box `[ ■ ]`. När du vrider i `MOVE` glider boxen längs låtens tidslinje, och i `SIZE` expanderar/krymper boxen!
- **Höger kommandokolumn (sidebar):**
  - `◎ SIZE/MOVE`: Rattstyrning (ändra looplängd eller flytta loopfönstret).
  - `▲ SWAP`: Kort tryck på övre knappen växlar ratten mellan `SIZE` och `MOVE`.
  - `↳ REV`: Håll övre knappen för att spela loopen baklänges!
  - `▼ DJ`: Kort tryck på nedre knappen växlar till `DJ`.
  - `↳ VOL`: Håll nedre knappen för att återgå till standard volymläge.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Övre knapp (`IO23`)** | Klick | **Växla rattläge mellan `SIZE` och `MOVE` (`SWAP`)!** |
| | Håll (>0.5 s) | **Reverse Loop:** Spela loopen baklänges (`REV`)! |
| **Rotary Encoder (i `SIZE`)** | Vrid | **Öka / minska looptid:** När du ökar längden läggs den nya tiden till **framåt i låten** så att kommande takter kommer in i loopen! Stegar mellan 0.125 s upp till 16.0 s. |
| **Rotary Encoder (i `MOVE`)** | Vrid | **Flytta loopen längs tidslinjen:** Skjuter hela loopfönstret framåt eller bakåt genom musiken så du kan hitta det perfekta partiet att loopa. |
| **Nedre knapp (`IO22`)** | Klick | Växla till **`DJ` Mode**. |
| | Håll (>0.5 s) | **Återgå till `VOL` Mode:** Musiken fortsätter spela sömlöst framåt från loopens position in i resten av låten! |

---

### 4. `DJ` (DJ Color Filter & Turntable Tape Brake)
Ett kraftfullt och festanpassat DJ-verktyg utformat för att bygga upp stämning, skapa episka beat drops och köra turntable-bromsar.

- **Display:**
  - Topprad: `DJ` märke till vänster och aktiv filterstatus till höger (`CLEAN`, `LPF -45%`, `HPF +60%`, eller `[BRAKE]`).
  - Mitten: **Levande frekvenskurva** som animeras och visar exakt hur bas eller diskant skärs bort, med rytmiskt dansande spektrumprickar.
  - Nederst: Bi-polär filtermätare med mittpunkt vid neutralt (`CLEAN`).
- **Höger kommandokolumn (sidebar):**
  - `◎ FILTER`: Bi-polärt DJ-filter (vrid vänster för LPF / vrid höger för HPF).
  - `▲ XFADE`: Kort tryck på övre knappen aktiverar **Beat-Matched Smart Transition**! Maskinen håller förra låtens rytmkärna vid full volym (`CORE / WAIT`) medan Spotify laddar nästa låt. Så fort nästa låt faktiskt har ljud och energinivå synkas övergången mot nästa taktslag (`SYNC`), och den nya låten droppar in med HPF i perfekt takt medan förra låtens basgroove mjukt fasas ut över 2 takter!
  - `↳ BRAKE`: Håll övre knappen för **Turntable Brake / Tape Stop** (musiken saktar in och stannar som en vinylspelare vars motor stängts av!).
  - `▼ TAPE`: Kort tryck på nedre knappen växlar till `TAPE`.
  - `↳ VOL`: Håll nedre knappen för att återgå till standard volymläge.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder (Vrid vänster)** | Vrid | **Low-Pass Filter (LPF):** Skär bort diskant och sång. Ljudet blir djupt och mörkt som om du står i toalettkön utanför klubben! |
| **Rotary Encoder (Vrid höger)** | Vrid | **High-Pass Filter (HPF):** Skär bort bas och kick för att bygga upp maximal förväntan! |
| **Övre knapp (`IO23`)** | Klick | **BEAT-MATCHED TRANSITION (XFADE):** Intelligent DJ-övergång! Håller förra låtens groove vid 100 % volym tills nästa låt faktiskt levererar ljud. Matchar taktslag och energinivå, droppar in på takten och sveper med filter. Noll tystnad, noll volymdipp, 100 % musikaliskt! Klicka igen för att avbryta/snäppa till nutid. |
| | Håll (>0.5 s) | **TURNTABLE BRAKE (Tape Stop):** Skivspelarens motor stängs av och musiken saktar in till ett stopp (*wwwhhhoooom*). Släpp för att varva upp igen! |
| **Nedre knapp (`IO22`)** | Klick | Växla vidare till **`TAPE` Mode**. |
| | Håll (>0.5 s) | **Återgå till `VOL` Mode**. |

---

## ⚡ Säker avstängning
Oavsett vilket läge du befinner dig i:
- **Håll båda knapparna samtidigt i 3 sekunder**: Skärmen visar *"SHUTTING DOWN..."* och Pi:n stängs av säkert (`sudo shutdown -h now`).
