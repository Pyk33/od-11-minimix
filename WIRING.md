# OD-11 Minimix – kopplingsschema

> [!IMPORTANT]
> Stäng av Pi:n (dra ur strömmen) varje gång du kopplar om. Pinnummer nedan är **fysiska pinnar** (1–40) på Pi:ns header. GeeekPi-HAT:en har skruvplintar med samma GPIO-namn, så använd GPIO-numren där.

## Översikt

![Kopplingsschema](wiring.svg)

(Mermaid-version nedan.)

```mermaid
flowchart LR
    subgraph PI["Raspberry Pi 4 + GeeekPi HAT"]
        P4["5V (pin 4 / plint)"]
        P2["5V (pin 2)"]
        SDA["GPIO2 SDA (pin 3)"]
        SCL["GPIO3 SCL (pin 5)"]
        G17["GPIO17 (pin 11)"]
        G27["GPIO27 (pin 13)"]
        G22["GPIO22 (pin 15)"]
        G23["GPIO23 (pin 16)"]
        GND["GND (pin 6, 9, 14, 20)"]
        USB["USB-A"]
    end
    OLED["OLED 1.5 tum SH1107 (128x128)"]
    ENC["LPD3806 encoder"]
    B1["Knapp Play/Pause"]
    B2["Knapp Next"]
    DAC["Cubilux USB till TOSLINK"]
    OD["OD-11 (TOSLINK, undersidan)"]

    P4 --> OLED
    SDA --> OLED
    SCL --> OLED
    GND --> OLED
    P2 --> ENC
    G17 --- ENC
    G27 --- ENC
    GND --> ENC
    G23 --- B1
    G22 --- B2
    GND --> B1
    GND --> B2
    USB --> DAC
    DAC -->|"TOSLINK-kabel"| OD
```

## 1. OLED-skärm (1.5" SH1107 I2C kvadratisk 128x128, adress 0x3C)

> [!IMPORTANT]
> **Hailege-modulens VCC MÅSTE kopplas till +5V!**  
> 1.5"-modulen har en inbyggd 3.3V LDO-regulator (662K) och en skyddsdiod. Om den matas med 3.3V får styrchippet bara ~2.7V, vilket gör att skärmen inte tänds. Anslut till **5V (pin 4 eller 5V-plint)**.
>
> **Stiftordning på modulens kretskort (från vänster till höger):** `GND` • `VCC` • `SCL` • `SDA`

| Skärm (Stift på modul) | Din kabelfärg | Pi / GeeekPi HAT | Fysisk Pin |
|---|---|---|---|
| **GND** (Stift 1) | **Gul** | **GND** | Pin 9 (eller valfri GND) |
| **VCC** (Stift 2) | **Orange** | **5V** *(OBS: 5V, inte 3.3V!)* | Pin 4 (eller 5V-plint) |
| **SCL** (Stift 3) | **Röd** | **GPIO3** (SCL) | Pin 5 |
| **SDA** (Stift 4) | **Ljusbrun** | **GPIO2** (SDA) | Pin 3 |

Kontroll efter uppstart: `sudo i2cdetect -y 1` ska visa `3c`.

## 2. Rotary encoder LPD3806-600

| Encoder (typisk färg) | Pi | Pin |
|---|---|---|
| Röd (VCC) | **5V** | 2 |
| Svart (GND) | GND | 14 |
| Grön (A) | GPIO17 | 11 |
| Vit (B) | GPIO27 | 13 |
| Skärm/skärmning (om finns) | GND | 14 |

Pull-up-motstånd (4,7 kΩ) är **valfria**. Du behöver inte köpa dem för att börja: Pi:ns interna pull-ups används automatiskt. Köp bara motstånd om encodern hoppar eller räknar fel vid snabb vridning:
- Ett motstånd mellan GPIO17 och **3V3** (pin 1).
- Ett motstånd mellan GPIO27 och **3V3** (pin 1).

```
3V3 ──[4.7k]──┬── GPIO17 ── Grön (A)
3V3 ──[4.7k]──┬── GPIO27 ── Vit (B)
```

> [!CAUTION]
> Koppla **aldrig** 5 V till GPIO 17 eller 27. Pull-upen ska gå till **3,3 V**, inte 5 V.

Test innan du kopplar in Pi:n på riktigt: mata encodern med 5 V och mät A och B mot GND med multimeter.
- Nära 0 V eller flytande: open-collector, allt är OK.
- Nära 5 V i vila: utgången är push-pull eller har en egen pull-up. Lägg då ett 1 kΩ-motstånd i serie på A och B, eller skriv till mig.

Går volymen åt fel håll: byt plats på A och B.

## 3. Tryckknappar (12 mm metallknappar med NO, C, NC)

Använd bara stiften märkta **NO** och **C**. Låt **NC** vara okopplad.

| Knapp | C (Common) | NO (Normally Open) | HAT-plintar (Rad 3) |
|---|---|---|---|
| **Play/Pause** (övre) | GND | GPIO23 | **`GND`** + **`IO23`** |
| **Next** (nedre) | GND | GPIO22 | **`GND`** + **`IO22`** |

Inga externa motstånd behövs. Koden aktiverar interna pull-ups automatiskt.

### Knappfunktioner i koden:
- **Play/Pause (IO23, övre knapp):** 
  - Klick: Växla Play / Pause.
  - Håll intryckt (0,7 s): Mute / Unmute.
- **Next (IO22, nedre knapp):** 
  - Klick: Nästa låt.
  - Håll intryckt (0,7 s): Föregående låt.
- **Säker avstängning:** Håll **båda knapparna samtidigt i 3 sekunder**. Skärmen visar *"STÄNGER AV..."* och Pi:n stängs ner kontrollerat.

## 4. Ljud

```
Pi USB-A ──► Cubilux USB till TOSLINK ──► TOSLINK-kabel ──► OD-11 (undersidan)
```

- Optisk ingång på OD-11 är en vanlig stor, fyrkantig **TOSLINK** och sitter på **undersidan** (verifierat med din egen kabel). Ingen adapter behövs.
- Använd en blå USB-3-port (eller vilken USB-port som helst). Cubilux behöver ingen separat ström.
- Välj källa på OD-11 för optisk ingång.

## 5. Ström

Officiella 15,3 W USB-C-adaptern till Pi:n. Encoder och skärm drar bara Pi:ns egen ström.

## Pinnöversikt (bara de som används)

| Pin | Funktion | Går till | Kabelfärg |
|---|---|---|---|
| 1 | 3V3 | OLED VCC | **Orange** |
| 2 | 5V | Encoder VCC | Röd |
| 3 | GPIO2 SDA | OLED SDA | **Ljusbrun** |
| 5 | GPIO3 SCL | OLED SCL | **Röd** |
| 9 | GND | OLED GND | **Gul** |
| 11 | GPIO17 | Encoder A | Grön |
| 13 | GPIO27 | Encoder B | Vit |
| 14 | GND | Encoder GND | Svart |
| 15 | GPIO22 | Knapp Next (nedre) | |
| 16 | GPIO23 | Knapp Play/Pause (övre) | |
| 20 | GND | Knappar COM | |

## Tips för 3D-printad låda

- Hål för: USB-C-ström, Ethernet (om du använder kabel), optisk kabel från Cubilux, encoderaxel (6 mm) och två knappar (12 mm).
- Encodern är ca 38 mm i diameter och långt bakåt. Placera den bredvid Pi:n, inte ovanpå.
- Ge Pi:n lite luft. Plast isolerar, så lägg på en liten kylfläns.
