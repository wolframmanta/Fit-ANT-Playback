# DMRL Virtual Power Lab

A **Dirty Mitten Racing League** development and testing utility that broadcasts power and cadence data via ANT+ USB dongle. Built for developers, testers, and equipment manufacturers who need to simulate ANT+ power meter signals without requiring actual cycling hardware.

- Dirty Mitten Racing League: <https://www.dirtymittenracing.com>
- Created by The.Colonel: <https://lonewolfracing.cc>

## Intended Use

This tool is designed for **legitimate testing and development purposes**, including:

- **Application development** — Test ANT+ integration in fitness apps without needing a bike, trainer, or power meter
- **QA and regression testing** — Replay recorded FIT files to verify consistent behavior across software versions
- **Hardware/software validation** — Confirm that devices and applications correctly receive and interpret ANT+ power data
- **Demo and presentation** — Showcase ANT+ compatible software without live cycling equipment

**This tool is NOT intended for cheating, falsifying results, or gaining unfair advantages in competitive platforms like Zwift, TrainerRoad, or any other online racing or training service.** Use responsibly and in accordance with the terms of service of any platform you connect to.

The DMRL dashboard displays this testing-and-diagnostics disclaimer at startup. The warning is intentional and should remain visible in packaged builds.

## Current Release

- Version 1.2.2
- macOS-only packaged application: `DMRL Virtual Power Lab.app`
- The legacy Python/Tk interface remains in source for development and fallback testing, but public distribution is now the macOS Dirty Mitten Racing League dashboard build.

## Features

- DMRL-branded PySide6 dashboard UI with a denser control-room layout, live metrics, ride preview chart, and shared playback controls
- In-app How To page for basic setup, input selection, broadcasting, pairing, and safe-use reminders
- Browse and load FIT files with power/cadence data
- Browse and load structured workout files (`.zwo`, `.erg`, `.mrc`, `.xml`, `.xert`) using configurable FTP for percent-based targets
- Generate simulated ride profiles with course types, average power, NP-style target, weight, cadence, and variability controls
- Broadcast data via ANT+ Bike Power profile (Device Type 0x0B)
- Play, pause, and stop playback controls
- Variable playback speed (0.5x - 4.0x)
- Real-time display of power and cadence values
- Progress tracking with time display
- Manual Power mode with slider, preset buttons (including 0W), and direct entry
- W/kg input with configurable weight — enter watts per kilogram and the tool calculates power automatically

## Requirements

The current packaged release is macOS only.

### Hardware
- ANT+ USB stick (Dynastream/Garmin)

### Software Dependencies
```bash
pip install fitdecode PySide6 pyusb
```

The DMRL PySide6 dashboard was verified with Python 3.13 in this workspace. If Python 3.14 reports a Qt platform-plugin startup error, create the app venv with Python 3.13 for the Qt UI.

On macOS, you may also need:
```bash
brew install libusb
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

1. Run the DMRL dashboard application on macOS (requires `sudo` for USB access to the ANT+ stick on some systems):
   ```bash
   sudo python fit_ant_playback_qt.py
   ```

   If your operating system allows user-level USB access, you can run:
   ```bash
   python fit_ant_playback_qt.py
   ```

   After an editable install, you can also run:
   ```bash
   fit-ant-playback-qt
   ```

   The original Tk interface remains available from source for development/fallback use:
   ```bash
   sudo python fit_ant_playback.py
   ```

   Or, without elevated USB access:
   ```bash
   python fit_ant_playback.py
   ```

2. Click "Browse..." to select a FIT file containing power/cadence data or a structured workout file. Set FTP first for percent-based workout files.

3. Click "Connect ANT+" to initialize the ANT+ USB stick

4. Click "Play" to start broadcasting

5. Pair the ANT+ power source in your application under test — it will appear as a Bike Power sensor

### Ride Simulator Mode

1. Switch to the **Ride Simulator** tab
2. Choose a course type: steady TT, endurance ride, rolling course, hilly course, mountain climb, crit/race surges, or VO2 intervals
3. Set duration, average power, target NP, rider weight, preferred cadence, and variability
4. Click **Generate Ride**; the generated ride loads into the File Playback tab
5. Click **Play** from File Playback after connecting ANT+

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
- `fit_ant_playback_qt.py` — DMRL-branded PySide6 dashboard UI and app wiring
- `fit_ant_playback.py` — legacy Tk GUI and app wiring
- `fit_ant_playback_core/fit_parser.py` — FIT parsing
- `fit_ant_playback_core/workout_parser.py` — structured workout parsing
- `fit_ant_playback_core/ride_simulator.py` — simulated ride generation
- `fit_ant_playback_core/ant_protocol.py` — ANT serial frames and Bike Power pages
- `fit_ant_playback_core/ant_usb.py` — raw USB ANT+ broadcaster
- `fit_ant_playback_core/playback_engine.py` — monotonic playback/manual broadcast scheduling

Run the unit tests:
```bash
python -m unittest discover
```

See `docs/ROADMAP.md` for planned larger improvements and remaining simulator refinements.

## Release Notes

### 1.2.2 - 2026-06-13

- Updated the sidebar brand treatment so it mirrors the main DMRL red/yellow/red diagonal stripe.
- Added an in-app How To page for the basic operating workflow and testing-only reminder.

### 1.2.1 - 2026-06-13

- Cleaned up the sidebar logo so the compact mark reads as `DMRL` only, with `Dirty Mitten` as the sidebar label.
- Kept the full Dirty Mitten Racing League name in About and documentation.

### 1.2.0 - 2026-06-13

- Made the DMRL Virtual Power Lab macOS dashboard the public packaged release.
- Added the DMRL-branded PySide6 dashboard, app icon, and macOS `.app` packaging.
- Added startup legal disclaimer for testing/diagnostics-only use.
- Added structured workout file playback for ZWO, ERG, MRC, XML, and XERT-style files.
- Added realistic ride simulation controls for course type, average power, target NP, weight, cadence, and variability.

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
- On macOS, you may need elevated permissions

### No Data in File
- Ensure your FIT file contains `record` messages with `power` and/or `cadence` fields
- Ensure your workout file contains supported workout steps or course data
- Files from bike computers, power meters, smart trainers, and common workout exporters typically have this data

### Device Not Detected
- Make sure playback is running before searching for sensors in your application
- Select ANT+ (not Bluetooth) in your application's pairing screen
- The device will appear as a power source

## License

MIT License
