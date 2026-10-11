# Olle's Mini-Mix – OB-4 Magic Tape, Looper & Disk Mode

Inspirerad av Teenage Engineerings ikoniska **OB-4 "Magic Radio"** är Olle's Mini-Mix utrustad med en kontinuerlig rullande bandbuffert i minnet och realtids-DSP som gör det möjligt att spola i realtidsljud, loopa och skapa eteriska drönarlandskap.

---

## 🎛️ Lägen & Kontroller

Mini-Mix har fyra driftslägen. Du växlar mellan dem med knapparna och encodern:

```
[ VOL ] ──(Håll Next)──> [ TAPE ] ──(Klicka Next)──> [ LOOP ] ──(Klicka Next)──> [ AMBIENT ] ──(Klicka Next)──> [ VOL ]
```

---

### 1. `VOL` (Standardläge / Live)
Normal uppspelning från Spotify Connect eller AirPlay.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder** | Vrid medurs / moturs | Höj / sänk volym (0–85 %). Stor TE-volymoverlay visas på skärmen. |
| **Play/Pause (`IO22`)** | Klick | Play / Pause (Spotify / AirPlay). |
| | Håll (0,7 s) | Mute / Unmute. |
| **Next (`IO23`)** | Klick | Nästa spår. |
| | Håll (0,7 s) | **Växla till `TAPE` Mode!** |

---

### 2. `TAPE` (OB-4 Magic Tape: Scrub & Rewind)
En kontinuerlig 15-minuters bandbuffert spelar in all musik i realtid i 48 kHz stereo. I detta läge kan du spola bakåt och framåt i tiden med autentisk pitch/bandretardation och mekanisk tröghet.

- **Display:** Visar två animerade rullbandshjul som snurrar i takt med bandhastigheten, tidsskillnad mot live (`-00:24` eller `LIVE`), och bandhuvud.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder** | Vrid moturs | **Spola bakåt i tiden!** (Tape scratch / rewind). |
| | Vrid medurs | **Spola framåt** mot realtidsströmmen. |
| **Play/Pause (`IO22`)** | Klick | **Tape Stop / Resume**: Simulerar motorstopp på rullband/vinyl. |
| | Håll (0,7 s) | **JUMP TO LIVE!** Hoppar omedelbart fram till realtidsströmmen och återgår till `VOL`. |
| **Next (`IO23`)** | Klick | Växla till **`LOOP` Mode**. |
| | Håll (0,7 s) | Återgå till `VOL` Mode. |

---

### 3. `LOOP` (Instant Looper & Glitch Stutter)
Fångar omedelbart en slinga av musiken och upprepar den med klickfria equal-power crossfades.

- **Display:** Visar aktiv slinga, looplängd i sekunder samt en pulserande loopbox med rörligt playhead i realtid.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder** | Vrid medurs / moturs | **Ändra looplängd:** Stega mellan 16 s, 8 s, 4 s, 2 s, 1 s, 0,5 s, 0,25 s och 0,125 s (snabb glitch-stutter). |
| **Play/Pause (`IO22`)** | Klick | **Freeze / Bypass:** Växla loopning av och på. |
| | Håll (0,7 s) | **Reverse Loop:** Spela loopen baklänges! |
| **Next (`IO23`)** | Klick | Växla till **`AMBIENT` Mode**. |
| | Håll (0,7 s) | Återgå till `VOL` Mode. |

---

### 4. `AMBIENT` (OB-4 Disk Mode: Generative Drone)
Granulerar ett fryst ögonblick av musiken med 4 överlappande Hann-fönstrade stämmor till en oändlig, eterisk ambient drönare.

- **Display:** Visar en levande harmonisk vågform och en reglagelinje för klangfärg / grain position.

| Kontroll | Åtgärd | Funktion |
|---|---|---|
| **Rotary Encoder** | Vrid | **Modulera klangfärg:** Flyttar sökfönstret genom ljudet för att utforska ackord och övertoner. |
| **Play/Pause (`IO22`)** | Klick | **Ny klang:** Fångar en ny punkt i ljudet att granulera. |
| **Next (`IO23`)** | Klick | Återgå till `VOL` Mode. |
| | Håll (0,7 s) | Återgå till `VOL` Mode. |

---

## ⚡ Säker avstängning
Oavsett vilket läge du befinner dig i:
- **Håll båda knapparna samtidigt i 3 sekunder**: Skärmen visar *"SHUTTING DOWN..."* och Pi:n stängs av säkert (`sudo shutdown -h now`).
