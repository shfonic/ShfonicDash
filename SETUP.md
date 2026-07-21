# Sim Racing Telemetry Dashboard — Pi OS Lite Setup Guide

- **Target hardware**: Raspberry Pi 3 + 7” official touchscreen
- **OS**: Raspberry Pi OS Lite (Debian Trixie)
- **Dashboard**: Pygame-based, Python 3.13

## Steps

### 1. Flash and Boot Raspberry Pi OS Lite
- Flash Raspberry Pi OS Lite to your SD card (recommended: Raspberry Pi Imager)
- Boot the Pi and log in with the default user (`pi` or your chosen username)

#### Raspberry Pi Imager
If using Raspberry Pi Imager, setup the following which will save time later:
- Add Wifi Details
- Enable SSH
  - Use Public Key Authentication (Generate and assign SSH Public Key)
- Don't use Raspberry Pi Connect

### 2. Basic system setup
Run:
```bash
sudo apt update
sudo apt upgrade -y
sudo raspi-config
```

Inside `raspi-config`:
- Set hostname
- Set locale / keyboard / timezone
- Enable autologin for your user on tty1
- Enable SSH if needed (Should have already been done as part of the Raspberry Pi Imager)
Reboot after configuration.

### 3. Install minimal X11 for Pygame
```bash
sudo apt install --no-install-recommends xserver-xorg xinit \
    xserver-xorg-input-libinput x11-xserver-utils
sudo apt install python3-pip python3-dev
```
- No desktop environment needed
- Touchscreen works automatically via `libinput`
- X11 is lightweight → reduced latency

### 4. Install Git and Python dependencies
1. Install Git, Python, and dependencies
```bash
sudo apt install git -y
```
2. Clone your repo (or copy it to the Pi):
```bash
cd ~
git clone <your-github-repo-url> ShfonicDash
cd ShfonicDash
```

3. Create a Python virtual environment (optional but recommended):
```bash
python3 -m venv ~/ShfonicDash/venv
source ~/ShfonicDash/venv/bin/activate
```

4. Install requirements:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Create dashboard launcher script
Create run_dashboard.sh:
```
nano ~/ShfonicDash/run_dashboard.sh
```
Paste:
```bash
#!/bin/bash
export SDL_VIDEODRIVER=x11  # Use X11 driver
cd ~/ShfonicDash/src
/usr/bin/python3 main.py --mock
Make it executable:
chmod +x ~/ShfonicDash/run_dashboard.sh
```

### 6. Enable auto-start on boot via .bash_profile
Edit the user’s bash profile:
```bash
nano ~/.bash_profile
```
Add at the end:
```bash
DASHBOARD_LOCK="$HOME/.dashboard_disabled"

# Only start dashboard if lock file does not exist
if [ ! -f "$DASHBOARD_LOCK" ] && [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx ~/ShfonicDash/run_dashboard.sh -- :0
fi
```
Ensures dashboard auto-starts on login
Won’t start if lock file exists (used when exiting dashboard)

### 7. Rotate touchscreen 180°
1. Find your touchscreen name:
```bash
xinput list
```
Example:
```bash
FT5406 memory based touchscreen   id=6   [slave  pointer  (2)]
```
2. Create X11 config:
```bash
sudo mkdir -p /etc/X11/xorg.conf.d
sudo nano /etc/X11/xorg.conf.d/99-touchscreen.conf
```
Paste:
```bash
Section "InputClass"
    Identifier "Touchscreen"
    MatchProduct "FT5406 memory based touchscreen"
    Option "TransformationMatrix" "-1 0 0 0 -1 1 0 0 1"
EndSection
```
- Replace ``MatchProduct`` with your exact device name from ```xinput list```
- Reboot to apply

### 8. Handle long-press exit
In your Pygame dashboard:
```python
import os
# on long-press exit
os.system(f"touch {os.path.expanduser('~/.dashboard_disabled')}")
pygame.quit()
exit()
```
- Creates a lock file to prevent auto-restart
- To restart dashboard manually, remove the lock file:
```bash
rm ~/.dashboard_disabled
```

### 9. Reboot and verify
```bash
sudo reboot
```
- Pi logs in automatically
- Dashboard launches fullscreen
- Touchscreen works correctly (rotated)
- Long-press exit stops the dashboard from restarting

### 10. Notes / Tips
- Use `export SDL_VIDEODRIVER=x11` in the launcher — avoids the `EGL not initialized` error on Lite
- Keep `run_dashboard.sh` executable
- For debugging:
```bash
# Check dashboard logs
tail -f ~/.local/share/xorg/Xorg.0.log
```
- Optional: Add more dashboards later — `.bash_profile` auto-start handles the current default dashboard
