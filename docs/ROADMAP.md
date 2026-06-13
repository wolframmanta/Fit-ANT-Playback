# Roadmap

This file tracks larger improvements that are planned or partially implemented.

## 1. Professional UI Upgrade

Initial PySide6 support exists as a DMRL-branded dashboard in `fit_ant_playback_qt.py`. The target is a production-quality control surface with clear device status, live power/cadence, playback state, logs, and mode-specific controls that are easy to scan while Zwift or another test application is open.

Implemented direction:

- Keep the existing Tk app as a compatibility interface.
- Add a PySide6/Qt dashboard with DMRL black/blue/red/yellow branding.
- Use a left navigation rail, live metric cards, a power/cadence timeline, and mode-specific control pages.
- Preserve existing FIT playback, workout playback, ride simulator, manual power, and ANT+ broadcast workflows.

Remaining refinements:

- Run real visual QA on Matthew's desktop with PySide6 installed.
- Tune spacing and typography after seeing it at the actual monitor scale.
- Add icons if the Qt dependency set grows to include an icon library or bundled assets.
- Consider saving/restoring preferred FTP, rider weight, speed, and simulator defaults.

## 2. Realistic Cycling Input Simulator

Initial simulator support exists. It generates believable power and cadence streams instead of fixed manual values, using rider-level targets as guides and adding controlled variation so the broadcast looks more like an actual ride than a flat signal.

Implemented inputs:

- Target average power
- Target normalized power style value
- Ride duration
- Rider weight
- Cadence preference
- Variability level
- Ride type, such as steady TT, endurance ride, rolling ride, interval session, or race-like effort

Implemented behavior:

- Generate power variation around the requested targets.
- Couple cadence to power and effort style.
- Include drift, surges, recoveries, and short-term noise based on course type.
- Show estimated average power and normalized power style output after generation.
- Keep the simulator engine testable without ANT+ hardware.

Remaining refinements:

- Validate the generated traces against real ride files.
- Expand preview chart interactivity beyond the initial Qt timeline.
- Add more course profiles if useful.

## 3. Workout File Playback

Initial support exists for importing structured workout files directly and broadcasting their target power/cadence over time. This is not a workout builder; the first version focuses on reading existing files and turning them into replayable power targets.

Initial supported formats:

- Zwift/XML-style workout files (`.zwo`, `.xml`, `.xert`)
- ERG course-data files (`.erg`)
- MRC percent course-data files (`.mrc`)

Remaining refinements:

- Validate with real TrainerRoad, Xert, and Zwift exports.
- Add clearer unsupported-step reporting for workout XML files.
- Add rider-weight handling if a supported format requires it.
- Consider cadence fields beyond the currently supported common attributes.
