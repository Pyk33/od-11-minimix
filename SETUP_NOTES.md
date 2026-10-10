# Pi-inställningar (Raspberry Pi Imager)

Användare och lösenord ligger i `.env` (ignoreras av git, kopieras inte till Pi:n).

- **OS:** Raspberry Pi OS (Legacy, 64-bit) Lite (Bookworm)
- **Hostname:** `minimix`
- **Användare:** se `.env` (`PI_USER`)
- **Lösenord:** se `.env` (`PI_PASSWORD`)
- **Tidszon:** Europe/Stockholm, tangentbord `se`
- **Wi-Fi-land:** SE
- **SSH:** aktiverat

## Efter första boot
```bash
source .env
ssh $PI_USER@$PI_HOST
rsync -av --exclude .env --exclude venv --exclude __pycache__ ./ $PI_USER@$PI_HOST:~/streamer/
ssh $PI_USER@$PI_HOST 'cd ~/streamer && bash setup.sh'
```
Sedan: `sudo reboot` på Pi:n.
