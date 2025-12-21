# FIT ANT+ Playback Tool

Broadcasts power and cadence data from FIT files via ANT+ USB dongle for use with Zwift and other ANT+ compatible applications.

## Features

- 📁 Browse and load FIT files with power/cadence data
- 📡 Broadcast data via ANT+ Bike Power profile (Device Type 0x0B)
- ⏯️ Play, pause, and stop playback controls
- ⏩ Variable playback speed (0.5x - 4.0x)
- 📊 Real-time display of power and cadence values
- 📈 Progress tracking with time display

## Requirements

### Hardware
- ANT+ USB stick (Dynastream/Garmin)

### Software Dependencies
```bash
pip install fitdecode openant
```

On macOS, you may also need:
```bash
pip install pyusb
brew install libusb
```

On Linux, you may need to set up udev rules for ANT+ stick access:
```bash
sudo tee /etc/udev/rules.d/99-ant.rules << EOF
SUBSYSTEM=="usb", ATTR{idVendor}=="0fcf", MODE="0666"
EOF
sudo udevadm control --reload-rules
```

## Installation

1. Clone or download this project
2. Install dependencies:
   ```bash
   cd "Fit ANT Playback"
   pip install -r requirements.txt
   ```

## Usage

1. Run the application:
   ```bash
   python fit_ant_playback.py
   ```

2. Click "Browse..." to select a FIT file containing power/cadence data

3. Click "Connect ANT+" to initialize the ANT+ USB stick

4. Click "Play" to start broadcasting

5. Open Zwift and pair your ANT+ power source - it will appear as a Bike Power sensor

## ANT+ Details

The tool broadcasts using the **ANT+ Bike Power Profile**:
- Device Type: 0x0B (11)
- Data Page: 0x10 (Standard Power-Only)
- Channel Period: 8182 (~4.05 Hz)
- RF Frequency: 2457 MHz (ANT+ frequency)

## Troubleshooting

### ANT+ Won't Connect
- Ensure the ANT+ USB stick is plugged in
- Close any other applications using the ANT+ stick (Zwift, TrainerRoad, etc.)
- On Linux/macOS, you may need elevated permissions

### No Data in FIT File
- Ensure your FIT file contains `record` messages with `power` and/or `cadence` fields
- Files from bike computers, power meters, or smart trainers typically have this data

### Zwift Won't See the Device
- Make sure playback is running before searching in Zwift
- Select ANT+ (not Bluetooth) in Zwift's pairing screen
- The device will appear as a power source

## License

MIT License
