# FIT ANT+ Playback Tool

A **development and testing utility** that broadcasts power and cadence data via ANT+ USB dongle. Built for developers, testers, and equipment manufacturers who need to simulate ANT+ power meter signals without requiring actual cycling hardware.

## Intended Use

This tool is designed for **legitimate testing and development purposes**, including:

- **Application development** — Test ANT+ integration in fitness apps without needing a bike, trainer, or power meter
- **QA and regression testing** — Replay recorded FIT files to verify consistent behavior across software versions
- **Hardware/software validation** — Confirm that devices and applications correctly receive and interpret ANT+ power data
- **Demo and presentation** — Showcase ANT+ compatible software without live cycling equipment

**This tool is NOT intended for cheating, falsifying results, or gaining unfair advantages in competitive platforms like Zwift, TrainerRoad, or any other online racing or training service.** Use responsibly and in accordance with the terms of service of any platform you connect to.

## Features

- Version 0.2.0
- Browse and load FIT files with power/cadence data
- Broadcast data via ANT+ Bike Power profile (Device Type 0x0B)
- Play, pause, and stop playback controls
- Variable playback speed (0.5x - 4.0x)
- Real-time display of power and cadence values
- Progress tracking with time display
- Manual Power mode with slider, preset buttons (including 0W), and direct entry
- W/kg input with configurable weight — enter watts per kilogram and the tool calculates power automatically

## Requirements

### Hardware
- ANT+ USB stick (Dynastream/Garmin)

### Software Dependencies
```bash
pip install fitdecode pyusb
```

On macOS, you may also need:
```bash
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

   For editable development installs:
   ```bash
   pip install -e .
   ```

## Usage

1. Run the application (requires `sudo` for USB access to the ANT+ stick):
   ```bash
   sudo python fit_ant_playback.py
   ```

   If your operating system allows user-level USB access, you can run:
   ```bash
   python fit_ant_playback.py
   ```

2. Click "Browse..." to select a FIT file containing power/cadence data

3. Click "Connect ANT+" to initialize the ANT+ USB stick

4. Click "Play" to start broadcasting

5. Pair the ANT+ power source in your application under test — it will appear as a Bike Power sensor

### Manual Power Mode

1. Switch to the **Manual Power** tab
2. Set power using the slider, direct entry, or preset buttons (0, 150, 200, ... 1200W)
3. To use **W/kg**: enter your weight in kg, type a W/kg value, and press Enter or click Apply — power is calculated automatically
4. Adjust cadence as needed
5. Click **Start Broadcasting** to begin

## ANT+ Details

The tool broadcasts using the **ANT+ Bike Power Profile**:
- Device Type: 0x0B (11)
- Data Page: 0x10 (Standard Power-Only)
- Channel Period: 8182 (~4.00 Hz)
- RF Frequency: 2457 MHz (ANT+ frequency)

The USB backend uses PyUSB directly, validates ANT command responses during startup, and reports the specific command failure in the app log when the stick rejects a setup step.

## Development

The app is split into testable modules:
- `fit_ant_playback.py` — Tk GUI and app wiring
- `fit_ant_playback_core/fit_parser.py` — FIT parsing
- `fit_ant_playback_core/ant_protocol.py` — ANT serial frames and Bike Power pages
- `fit_ant_playback_core/ant_usb.py` — raw USB ANT+ broadcaster
- `fit_ant_playback_core/playback_engine.py` — monotonic playback/manual broadcast scheduling

Run the unit tests:
```bash
python -m unittest discover
```

## Release Notes

### 0.2.0 - 2026-05-20

- Split the single-file prototype into focused core modules for FIT parsing, ANT protocol framing, USB broadcasting, playback scheduling, and app models.
- Replaced the old mixed `openant`/raw USB path with a PyUSB ANT+ backend that validates setup command responses.
- Added ANT serial checksum parsing, Bike Power page generation, event count rollover, and accumulated power rollover tests.
- Reworked FIT playback and manual broadcasting to use monotonic 4 Hz schedulers.
- Kept Tk variable access on the UI thread for safer manual mode updates.
- Added package metadata, a console entry point, and unit tests.

## Troubleshooting

### ANT+ Won't Connect
- Ensure the ANT+ USB stick is plugged in
- Close any other applications using the ANT+ stick
- On Linux/macOS, you may need elevated permissions

### No Data in FIT File
- Ensure your FIT file contains `record` messages with `power` and/or `cadence` fields
- Files from bike computers, power meters, or smart trainers typically have this data

### Device Not Detected
- Make sure playback is running before searching for sensors in your application
- Select ANT+ (not Bluetooth) in your application's pairing screen
- The device will appear as a power source

## License

MIT License
