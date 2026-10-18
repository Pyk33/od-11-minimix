# Guide: Uppgradering till 1.5" Kvadratisk OLED (128x128) & Nytt Lock (Rev 5)

Dokumentation för installation av **1.5 tum SH1107 (128x128 I2C)**, måttchecklista och CAD/mjukvaruplan.

---

## 1. Vad som hände med förra skärmen (Rotorsak)

- **CAD-mått i Rev 4:** Glasfickan var $18.6\text{ mm}$ hög (bara det aktiva bildområdet).
- **Verkligt mått:** Glassubstratet fortsatte ner till $23\text{ mm}$ plus flatkabelns böj ($25\text{–}26\text{ mm}$).
- **Resultat:** Plastkanten klämde mot glasets svagaste punkt och knäckte glasskivan vid COG-bondningen.

---

## 2. Vald ny skärm: Hailege 1.5" SH1107 OLED (128x128)

- **Modell:** Hailege 1,5" SSH1107 OLED 128x128 Vit
- **Gränssnitt:** 4-pin IIC / I2C (`SDA, SCL, GND, VCC`)
- **Styrkrets:** **SH1107** (stöds direkt i Python via `luma.oled.device.sh1107`)
- **Upplösning:** 128 x 128 pixlar (Kvadratisk!)
- **Fysisk form:** Kvadratiskt kretskort (ca $42\text{–}45\text{ mm}$ per sida) och kvadratisk bildyta (~$27 \times 27\text{ mm}$).
- **Flexkabelns placering:** Sitter på **sidokanten** (inte underkanten som på 1.3").
- **Orientering:** Modulen kan roteras i locket så att sladdarna ansluts optimalt, och bilden roteras i mjukvaran (`rotate=0, 1, 2, 3`) så att den alltid visas rättvänd.

---

## 3. Måttchecklista (när 1.5"-skärmen anländer)

Mät följande med skjutmått och klistra in i chatten:

| # | Mått att ta | Ditt mått (mm) | Kommentar |
|---|---|---|---|
| **A** | **Kretskortets totala bredd** (PCB X) | _______ mm | Ca 42–45 mm |
| **B** | **Kretskortets totala höjd** (PCB Y) | _______ mm | Ca 42–45 mm |
| **C** | **Glasets totala bredd** | _______ mm | Ca 34–35 mm |
| **D** | **Glasets totala höjd** | _______ mm | Ca 34–35 mm |
| **E** | **Synliga/aktiva displayrutans mått** | ____ $\times$ ____ mm | Ca 27 × 27 mm |
| **F** | **Displayrutans offset från kretskortskanterna** | X: ___ , Y: ___ mm | Hur centrerad skärmen sitter på PCB:t |
| **G** | **Flexkabelns utstick** | _______ mm | Hur långt ut flatkabeln buktar på sidan |
| **H** | **Total tjocklek** (Kretskort + glas) | _______ mm | Ca 3.5–4.2 mm |
| **I** | **Pinnarnas placering & riktning** | Raka / Vinklade | Var stiften sitter och hur långt de sticker ut |

---

## 4. Vad vi ändrar i CAD (`scratch/generate_cad.py`)

1. **Kvadratiskt fönster (bezel) i locket:**
   - Det nedsänkta fönstret görs kvadratiskt (~$28 \times 28\text{ mm}$ med snygg fasning) exakt anpassat för 128x128-bildytan.
2. **Förstorad ficka på undersidan:**
   - Fickan expanderas för det större kretskortet (~$45 \times 45\text{ mm}$) med generöst spel runt om.
3. **Generös flexkabel-slits:**
   - Djup urfasning längs den sida där flatkabeln viker runt glaset, så att kabeln har minst 1.5–2 mm fri luft och noll mekanisk belastning.
4. **Stift-frigång:**
   - Urtag/spår för jumperkablarna så de inte tar i lockets styrring eller HAT:ens distanser.

---

## 5. Mjukvara & UI (`streamer.py`)

1. **Drivrutin:**
   ```python
   from luma.oled.device import sh1107
   device = sh1107(i2c(port=1, address=0x3C), width=128, height=128, rotate=oled_rotate)
   ```
2. **Kvadratisk layout (128x128):**
   - Vi anpassar UI-designen för den kvadratiska rutan:
     - **Överdel:** Statusikon, källa (Spotify/AirPlay/Tape) och låt-/artisttext.
     - **Mitten:** Stor retro rullbandsanimation (OD-11 / OB-4 bandspelare) eller stor volymindikator.
     - **Nederdel:** Speltid/progress-bar och volym/läge.
3. **Elmatning:**
   - Skärmens `VCC` kopplas till **`+5V`** på GeeekPi-plinten.

---

## 6. Hur vi återupptar (Instruktion till AI-assistenten)

> [!IMPORTANT]
> **När användaren återupptar konversationen:**
> Assistenten ska **aktivt be användaren om:**
> 1. **Bilder på 1.5"-skärmen** (fram- och baksida).
> 2. **Alla kontrollmått (A till I)** enligt tabellen i sektion 3.
> 
> Först när måtten och bilderna har stämts av uppdateras CAD-koden i `scratch/generate_cad.py` och UI-koden i `streamer.py`.
