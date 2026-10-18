# Guide & Dokumentation: Uppgradering till 1.5" Kvadratisk OLED (128x128 SH1107)

Dokumentation för installation av **Hailege 1.5" SH1107 OLED (128x128 I2C)**, mekanisk CAD-lösning för locket, inkoppling och mjukvarukonfiguration i `streamer.py`.

---

## 1. Vad som hände med förra skärmen (Rotorsak)

- **CAD-mått i Rev 4:** Glasfickan var $18.6\text{ mm}$ djup/hög (endast beräknad efter den aktiva bildytan).
- **Verkligt mått på 1.3"-modulen:** Glassubstratet fortsatte ner till $23.0\text{ mm}$ plus flatkabelns böj runt kanten ($25\text{–}26\text{ mm}$).
- **Resultat:** Plastkanten klämde direkt mot glasets svagaste punkt och knäckte glasskivan vid COG-bondningen vid montering.

---

## 2. Vald ny skärm & Officiell Ritning (MC01506)

Skärmen är **Hailege 1.5" SH1107 OLED 128x128 Vit (IIC/I2C)** (Amazon ASIN `B0CJY2Q4SY`).
Tillverkarens tekniska ritning (LCDWiki SKU `MC01506` / `GME128128-01`):

| Komponent / Del | Mått från ritning | CAD-ficka i locket (Rev 5) | Tolerans / Spel |
|---|---|---|---|
| **Kretskort (PCB)** | $34.00 \times 47.00 \times 1.2\text{ mm}$ | $34.80 \times 47.80 \times 2.8\text{ mm}$ | $+0.8\text{ mm}$ spel i X och Y |
| **Glasskiva** | $33.90 \times 37.30 \times 1.44\text{ mm}$ | $34.70 \times 38.50 \times 4.0\text{ mm}$ | $+0.8\text{ mm}$ i bredd, $+1.2\text{ mm}$ i höjd |
| **Aktiv bildyta (A.A.)** | $26.855 \times 26.855\text{ mm}$ ($128 \times 128$ px) | $27.20 \times 27.20\text{ mm}$ | $+0.34\text{ mm}$ synligt fönster |
| **Offset A.A. mot PCB** | Centrerad i X, $+2.82\text{ mm}$ mot överkant | $Y_{\text{fönster}} = Y_{\text{pcb}} + 2.82\text{ mm}$ | Exakt linjerat med bildytan |
| **Flatkabel (nederkant)** | $10.31\text{ mm}$ urfräsning på PCB | **$15.0 \times 9.0\text{ mm}$ fri ficka** | **Helt fri luft, 0% tryck** |
| **Stiftlist (överkant)** | 4-pin $2.54\text{ mm}$ delning | **$15.0 \times 6.0\text{ mm}$ fri ficka** | Gott om plats för lödpunkter |

Ritningsfiler sparade i projektet:
- `scratch/mc01506_size.png`
- `scratch/mc01506_pdf.png`

---

## 3. CAD-lösning & Geometrisk Audit

CAD-skriptet `scratch/generate_cad.py` genererar locket med följande parametrar:
1. **Placering:** `OG_X = 60.0`, `OG_Y = 35.0` (inre koordinater).
   - Centrerat perfekt mellan Raspberry Pi-distanserna ($X=31.0$ och $X=89.0$).
   - Ger exakt **$12.0\text{ mm}$ symmetrisk frigång** på både vänster och höger sida.
2. **Kvadratiskt fönster:** $27.2 \times 27.2\text{ mm}$ med $2.0\text{ mm}$ hörnradie och $0.4\text{ mm}$ nedsänkt bezel-ram.
3. **Flatkabel-avlastning:** Dedikerad urfräsning i plasten vid glasets nederkant ($15.0 \times 9.0\text{ mm}$) så att flatkabeln aldrig kan komma i kontakt med lockets plast.
4. **Gravyr:** `"OLLE's MiniMix"` centrerad direkt under fönstret vid `(60.0, 12.0)` med knivskarp $5.2\text{ mm}$ typografi.
5. **Audit-resultat:** `scratch/audit_cad.py` godkänd med **0 kollisioner** mot Pi 4, distanser, GeeekPi HAT-plintar, encoder och M12-knappar.

### Filer för 3D-utskrift:
- **Lock STL:** [`cad_output/od11_minimix_lid.stl`](file:///Users/ollepyk/Desktop/OD-11%20Minimix/streamer-project/cad_output/od11_minimix_lid.stl)
- **Lock STEP:** [`cad_output/od11_minimix_lid.step`](file:///Users/ollepyk/Desktop/OD-11%20Minimix/streamer-project/cad_output/od11_minimix_lid.step)
- **Komplett montering:** [`cad_output/od11_minimix_assembly.step`](file:///Users/ollepyk/Desktop/OD-11%20Minimix/streamer-project/cad_output/od11_minimix_assembly.step)

---

## 4. Inkoppling & Elmatning (Viktigt!)

> [!IMPORTANT]
> **Hailege-modulens VCC MÅSTE anslutas till +5V!**  
> Modulen har en inbyggd 3.3V LDO-regulator (märkt 662K) och en skyddsdiod på kretskortet.  
> Om du matar med 3.3V får SH1107-chippet bara ~2.7V, vilket gör att den interna laddningspumpen för OLED-panelen inte kan tända pixlarna.  
> Anslut därför modulens **VCC till +5V** på GeeekPi HAT-skruvplinten.

### Kopplingsschema:
| Skärmstift | Signal | GeeekPi HAT Anslutning |
|---|---|---|
| **GND** | Jord | **GND** (skruvplint eller GPIO stift 6/9/14) |
| **VCC** | Matningsspänning | **+5V** (skruvplint) |
| **SCL** | I2C Klocka | **SCL** / GPIO 3 (skruvplint) |
| **SDA** | I2C Data | **SDA** / GPIO 2 (skruvplint) |

---

## 5. Mjukvara & UI-layout i `streamer.py`

Mjukvaran har uppdaterats för fullt stöd av SH1107 och $128 \times 128$ kvadratiskt UI:

1. **Drivrutin:**
   - Standard är nu `OLED_DRIVER="sh1107"` med upplösning $128 \times 128$.
   - Bakåtkompatibel med `sh1106` ($128 \times 64$) om den gamla skärmen används.
2. **Kvadratisk Teenage Engineering UI-layout:**
   - **Main-vy (VOL/Uppspelning):**
     - Topprad: Källa (`SPOTIFY`/`AIRPLAY`), status (`PLAY`/`PAUS`/`-MM:SS`).
     - Titel & Artist: Stor text i `F_MD` och `F_SM` med mjuk horisontell marquee.
     - Center: Animerad TE-spektrumanalysator med 10 dansande EQ-staplar!
     - Progress: Speltid (`MM:SS`), totallängd och 16-segmenters progressbar.
     - Footer: Volymindikator och segmenterad volymstapel.
   - **Volym-overlay:**
     - Stor `VOLUME`-badge och gigantiska siffror (`F_XL`, 38 px).
     - 12-segmenters fet volymmätare och `LEVEL X/85` readout.
   - **TAPE-vy (OB-4 rullbandspelare):**
     - Två stora $30\text{ mm}$ rullbandshjul med roterande ekrar och rörligt band!
     - Tidsförskjutnings-display (`DELAY -00:45`), scrub-hastighet (`SCRUB 1.0x`) och buffertmätare.
   - **Sidobar (höger 1 cm):**
     - Snyggt utspridda TE-ikoner och labels för alla 5 funktioner (Rotor, Topp-klick, Topp-håll, Botten-klick, Botten-håll).

---

## 6. Utskriftsrekommendation för locket (Prusa MK4S)

- **Orientering:** Skriv ut med **utsidan (framsidan med fönstret) nedåt mot byggplattan**.
- **Byggplatta:** Prusa Textured PEI Sheet eller Satin Sheet ger den karakteristiska, matta Teenage Engineering-texturen på ovansidan av locket och runt fönstret!
- **Lagerhöjd:** 0.20 mm SPEED eller 0.15 mm STRUCTURAL.
- **Infill:** 15–20% Gyroid eller Grid.
- **Support:** Inga stöd behövs! Alla snäpptungor och blindfickor är optimerade för att skrivas utan stöd.
