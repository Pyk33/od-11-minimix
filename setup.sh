#!/usr/bin/env bash
# ==============================================================================
# setup.sh – Provisionering av OD-11 Minimix streamer (Pi OS Lite 64-bit, Bookworm)
# Kör på Pi:n (som vanlig användare, inte root):  bash setup.sh
# Valfritt: CARD=<alsa-kortnamn> bash setup.sh   (om USB-DAC:en inte hittas automatiskt)
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
RUN_USER="$(whoami)"
[ "$RUN_USER" = "root" ] && { echo "Kör som vanlig användare (sudo anropas vid behov)."; exit 1; }

echo "=== 1. Systempaket ==="
sudo apt update
sudo apt install -y \
    python3-venv python3-pip python3-dev python3-numpy swig \
    i2c-tools playerctl avahi-daemon shairport-sync \
    libasound2-dev libjpeg-dev zlib1g-dev libfreetype6-dev \
    fonts-dejavu-core curl ca-certificates \
    libogg0 libvorbis0a libflac12 libmpg123-0

echo "=== 2. I2C (400 kHz för snabb OLED-uppdatering) + grupper ==="
sudo raspi-config nonint do_i2c 0
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
if grep -q '^dtparam=i2c_arm=on' "$CFG"; then
    sudo sed -i 's/^dtparam=i2c_arm=on.*/dtparam=i2c_arm=on,i2c_arm_baudrate=400000/' "$CFG"
else
    echo 'dtparam=i2c_arm=on,i2c_arm_baudrate=400000' | sudo tee -a "$CFG" >/dev/null
fi
# Stäng av onboard-ljud/HDMI-ljud så USB-DAC:en alltid är kort 0/primär
sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CFG"
sudo usermod -aG gpio,i2c,audio "$RUN_USER"

echo "=== 3. ALSA: snd-aloop (OB-4 Tape Engine) + USB-DAC softvol ==="
sudo modprobe snd-aloop 2>/dev/null || true
if ! grep -q '^snd-aloop' /etc/modules 2>/dev/null; then
    echo 'snd-aloop' | sudo tee -a /etc/modules >/dev/null
fi

CARD="${CARD:-$(aplay -l 2>/dev/null | grep -i 'usb' | head -1 | awk '{print $3}')}"
if [ -z "$CARD" ]; then
    echo "!! Hittade ingen USB-ljudenhet. Anslut Cubilux och kör: CARD=<namn> bash setup.sh"
    aplay -l || true
    exit 1
fi
echo "Använder ALSA-kort: $CARD"
sudo tee /etc/asound.conf >/dev/null <<EOF
# Genererad av setup.sh – OD-11 Minimix OB-4 Tape Engine
pcm.dac {
    type hw
    card "$CARD"
}
pcm.dmixed {
    type dmix
    ipc_key 5978293
    ipc_perm 0666
    slave {
        pcm "dac"
        rate 48000
        format S16_LE
        period_size 1024
        buffer_size 4096
    }
}
pcm.softvol {
    type softvol
    slave.pcm "dmixed"
    control {
        name "Master"
        card "$CARD"
    }
    min_dB -60.0
    max_dB 0.0
    resolution 101
}
pcm.loop_in {
    type plug
    slave {
        pcm "hw:Loopback,0,0"
        rate 48000
        format S16_LE
    }
}
pcm.!default {
    type plug
    slave.pcm "loop_in"
}
ctl.!default {
    type hw
    card "$CARD"
}
EOF
# Skapa softvol-kontrollen direkt på det fysiska kortet
aplay -q -D softvol -d 1 -f S16_LE -r 48000 -c 2 /dev/zero 2>/dev/null || true

echo "=== 4. AirPlay (shairport-sync) ==="
sudo tee /etc/shairport-sync.conf >/dev/null <<'EOF'
general = {
    name = "Olle's Mini-Mix";
    output_backend = "alsa";
    ignore_volume_control = "no";   // iPhonens volymknappar reglerar AirPlay-ljudet direkt
};
alsa = {
    output_device = "default";
};
EOF
sudo usermod -aG audio shairport-sync || true
sudo systemctl enable --now avahi-daemon shairport-sync
sudo systemctl restart shairport-sync

echo "=== 5. Spotify Connect (go-librespot) ==="
if [ ! -x /usr/local/bin/go-librespot ]; then
    URL="$(curl -fsSL https://api.github.com/repos/devgianlu/go-librespot/releases/latest \
        | grep -o 'https://[^"]*linux_arm64[^"]*\.tar\.gz' | head -1)"
    [ -n "$URL" ] || { echo "Kunde inte hitta go-librespot-release för arm64"; exit 1; }
    TMP="$(mktemp -d)"
    curl -fsSL "$URL" | tar -xz -C "$TMP"
    sudo install -m 755 "$TMP/go-librespot" /usr/local/bin/go-librespot
    rm -rf "$TMP"
fi
CONF_DIR="$HOME/.config/go-librespot"
mkdir -p "$CONF_DIR"
cat > "$CONF_DIR/config.yml" <<'EOF'
device_name: "Olle's Mini-Mix"
device_type: speaker
audio_backend: alsa
audio_device: default
external_volume: true        # volymen styrs av encodern (ALSA softvol), inte av appen
zeroconf_backend: avahi      # delar mDNS med shairport-sync utan portkonflikt
server:
  enabled: true
  address: 127.0.0.1
  port: 3678
EOF
sed "s|^User=.*|User=${RUN_USER}|" go-librespot.service | sudo tee /etc/systemd/system/go-librespot.service >/dev/null

echo "=== 6. Python-venv ==="
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "=== 7. streamer.service ==="
sed -e "s|^User=.*|User=${RUN_USER}|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=${PROJECT_DIR}|" \
    -e "s|^ExecStart=.*|ExecStart=${PROJECT_DIR}/venv/bin/python3 ${PROJECT_DIR}/streamer.py|" \
    streamer.service | sudo tee /etc/systemd/system/streamer.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable go-librespot.service streamer.service
sudo systemctl restart go-librespot.service streamer.service

echo "=== 8. Statuskontroll ==="
sudo i2cdetect -y 1 || true
amixer -c "$CARD" sget Master || echo "(softvol 'Master' dyker upp efter första uppspelning)"
systemctl --no-pager --lines=5 status go-librespot streamer shairport-sync || true

echo "=== Klart! Starta om (sudo reboot) för grupper, 400 kHz I2C och ljudkortsordning. ==="