# Guide: Byte av OLED-skärm & Nytt Lock (Rev 5)

Dokumentation för att beställa ny 1.3" OLED-skärm, mäta den exakt och uppdatera CAD-modellen så att locket inte klämmer glaset.

---

## 1. Vad som hände (Rotorsak)

- **CAD-mått i Rev 4:** Glasfickan sattes till $H = 18.6\text{ mm}$ (vilket bara motsvarar det synliga bildområdet/övre kanten).
- **Verkligt mått på komponenten:** 
  - Glassubstratet fortsätter ner till ca **23 mm**.
  - Längst ner sitter **COG-anslutningen (Chip-On-Glass)** där den tunna orangea flatkabeln (FFC) är bondad mot glaset och viker runt kretskortets kant till baksidan (totalt ca **25–26 mm**).
- **Resultat:** När skärmen trycktes fast mot locket tog den 19 mm korta fickans plastkant emot direkt över glaset. Det skapade en brytpunkt som spräckte glasskivan och slet av displayens ledningsbanor.

---

## 2. Vilken skärm du ska beställa

Sök efter följande specifikationer:
- **Typ:** 1.3 tum I2C / IIC OLED Display Module
- **Upplösning:** 128 x 64 pixlar
- **Styrkrets:** **SH1106** (eller SSD1306)
- **Gränssnitt / Pinnar:** 4-pin (`GND`, `VCC`, `SCL`, `SDA`)
- **I2C-adress:** `0x3C` (ofta märkt `0x78` i 8-bit på baksidan)
- **Färg:** Vit (eller blå/vit)

### Snabba inköpsställen i Sverige:
1. **Amazon.se:** Sök på `"1.3 inch I2C OLED SH1106"` (finns ofta med 1 dags Prime-leverans).
2. **Electrokit.com:** Sök på `"OLED 1.3 I2C"`.
3. **M.nu:** Sök på `"OLED 1.3"`.

---

## 3. Måttchecklista (när nya skärmen anländer)

Mät följande med skjutmått och klistra in här i chatten:

| # | Mått att ta | Ditt mått (mm) | Kommentar |
|---|---|---|---|
| **A** | **Kretskortets bredd** (PCB X) | _______ mm | Typiskt 35.4–35.6 mm |
| **B** | **Kretskortets höjd** (PCB Y) | _______ mm | Typiskt 33.5–34.0 mm |
| **C** | **Glasets totala bredd** | _______ mm | Typiskt 34.4–34.8 mm |
| **D** | **Glasets totala höjd** (från toppen ner till glasskivans underkant) | _______ mm | Det var detta som var ~23 mm |
| **E** | **Total höjd inkl. flexkabelns böj** | _______ mm | Hur långt ner kabeln buktar under kretskortskanten (~25–26 mm) |
| **F** | **Synliga displayområdets höjd** | _______ mm | Själva bildrutan (~18–19 mm) |
| **G** | **Total tjocklek** (Kretskort + glas) | _______ mm | Typiskt 3.6–4.0 mm |
| **H** | **Pinnarnas placering** | GND-VCC-SCL-SDA | Bekräfta pinordningen på ovansidan |

---

## 4. Vad vi ändrar i CAD (`scratch/generate_cad.py`)

När måtten är ifyllda uppdaterar vi CAD-modellen:

1. **Större glasficka (`GLASS_H`):**
   - Ökas från 18.6 mm till **$D + 1.5\text{ mm}$** (t.ex. 25.0 mm).
2. **Dedikerat uttag för flexkabeln:**
   - En djup urgröpning/slits i lockets undersida där flatkabeln viker runt, så att den hänger helt fritt i luften utan att någonsin nudda plasten.
3. **Bibehållen bezel (fönster):**
   - Själva titthålet på ovansidan behålls i rätt storlek ($18.6\text{ mm}$) med snygg fasning så att man bara ser den aktiva skärmen utifrån och slipper se kretskortet.
4. **Mjuk montering:**
   - Skärmen ska vila mot en tunn skumtejp/tätningslist runt fönsterramen istället för att pressas hårt mot solid plast.

---

## 5. El & Mjukvara (viktig notering)

- **Spänning (VCC):** Koppla den nya skärmens **VCC** till **`+5V`** (inte 3.3V) på GeeekPi-plinten. Skärmens inbyggda regulator (662K) reglerar ner till ren 3.3V och ger full kraft till displayens interna laddningspump.
- **Drivrutin:** Vi har redan verifierat att mjukvaran startar perfekt med SH1106-kommandot (`0xAD, 0x8B`).

---

## 6. Hur vi återupptar (Instruktion till AI-assistenten)

> [!IMPORTANT]
> **När användaren återupptar konversationen:**
> Assistenten ska **aktivt be användaren om:**
> 1. **Bilder på den nya skärmen** (fram- och baksida med mått/referens så att komponentplacering, flexkabel och pinout syns tydligt).
> 2. **Alla exakta kontrollmått (A till H)** enligt tabellen i sektion 3.
> 
> Först när måtten och bilderna har bekräftats ska CAD-koden i `scratch/generate_cad.py` uppdateras.

### Arbetsgång vid återupptagning:
1. Assistenten stämmer av måtten mot parametrarna i CAD.
2. Uppdaterar `scratch/generate_cad.py` med generösa marginaler och flexkabel-avlastning.
3. Kör geometri- och kollisionsgranskningen (`scratch/audit_cad.py`).
4. Exporterar `cad_output/od11_minimix_lid.stl` och `.step`.
5. Committar och pushar till GitHub så filen kan slicas i EasyPrint.
