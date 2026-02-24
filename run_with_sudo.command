#!/bin/bash
# FIT ANT+ Playback Launcher with Admin Privileges
# Double-click this file to run the app with sudo

cd "$(dirname "$0")"

echo "Starting FIT ANT+ Playback with admin privileges..."
echo "You may be prompted for your password."
echo ""

# Activate virtual environment and run with sudo
sudo .venv/bin/python fit_ant_playback.py
