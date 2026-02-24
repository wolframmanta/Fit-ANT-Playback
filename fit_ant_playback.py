#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
# pyright: reportIndexIssue=false, reportArgumentType=false
"""
FIT File ANT+ Playback Tool
Broadcasts power and cadence data from a FIT file via ANT+ USB dongle.
Can be read by Zwift or other ANT+ compatible applications.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import struct
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

try:
    import fitdecode  # type: ignore[import-untyped]
except ImportError:
    fitdecode = None  # type: ignore[assignment]

try:
    from ant.core import driver, node, event, message  # type: ignore[import-not-found]
    from ant.core.constants import *  # type: ignore[import-not-found]
    ANT_AVAILABLE = True
except ImportError:
    try:
        # Try alternative import structure
        from openant.easy.node import Node  # type: ignore[import-untyped]
        from openant.easy.channel import Channel  # type: ignore[import-untyped]
        ANT_AVAILABLE = True
    except ImportError:
        ANT_AVAILABLE = False


@dataclass
class PowerCadenceRecord:
    """Single record of power and cadence data"""
    timestamp: float  # seconds from start
    power: int  # watts
    cadence: int  # rpm


class FitFileParser:
    """Parses FIT files to extract power and cadence data"""
    
    def __init__(self):
        if fitdecode is None:
            raise ImportError("fitdecode library not installed. Run: pip install fitdecode")
    
    def parse(self, filepath: str) -> List[PowerCadenceRecord]:
        """Parse a FIT file and extract power/cadence records"""
        records = []
        start_timestamp = None
        
        with fitdecode.FitReader(filepath) as fit:  # type: ignore[union-attr]
            for frame in fit:
                if isinstance(frame, fitdecode.FitDataMessage):  # type: ignore[union-attr]
                    if frame.name == 'record':
                        timestamp = None
                        power = None
                        cadence = None
                        
                        for field in frame.fields:
                            if field.name == 'timestamp':
                                timestamp = field.value
                            elif field.name == 'power':
                                power = field.value
                            elif field.name == 'cadence':
                                cadence = field.value
                        
                        if timestamp is not None:
                            if start_timestamp is None:
                                start_timestamp = timestamp
                            
                            # Calculate relative timestamp in seconds
                            if hasattr(timestamp, 'timestamp'):
                                ts = timestamp.timestamp()
                                st = start_timestamp.timestamp() if hasattr(start_timestamp, 'timestamp') else start_timestamp
                            else:
                                ts = timestamp
                                st = start_timestamp
                            
                            relative_time = ts - st
                            
                            # Only add if we have at least power or cadence
                            if power is not None or cadence is not None:
                                records.append(PowerCadenceRecord(
                                    timestamp=relative_time,
                                    power=power if power is not None else 0,
                                    cadence=cadence if cadence is not None else 0
                                ))
        
        return records


class ANTBikePowerBroadcaster:
    """
    Broadcasts bike power and cadence via ANT+
    
    ANT+ Bike Power Profile (Device Type 0x0B = 11)
    Uses Standard Power-Only main data page (0x10)
    """
    
    # ANT+ Bike Power constants
    DEVICE_TYPE = 0x0B  # Bike Power
    DEVICE_NUMBER = 12345  # Arbitrary device number
    TRANSMISSION_TYPE = 0x05  # Independent channel, global pages supported
    CHANNEL_PERIOD = 8182  # ~4.049 Hz (standard for bike power)
    CHANNEL_FREQUENCY = 57  # 2457 MHz (ANT+ frequency)
    NETWORK_KEY = [0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45]  # ANT+ Network Key
    
    def __init__(self):
        self.node = None
        self.channel = None
        self.running = False
        self.event_count = 0
        self.accumulated_power = 0
        self.crank_event_time = 0
        self.crank_revolutions = 0
        
    def _check_usb_device(self):
        """Check if ANT+ USB stick is detected"""
        try:
            import usb.core  # type: ignore[import-untyped]
            # Common ANT+ USB stick vendor/product IDs
            ant_sticks = [
                (0x0FCF, 0x1008),  # Dynastream ANT USB-m Stick
                (0x0FCF, 0x1009),  # Dynastream ANT USB2 Stick  
                (0x0FCF, 0x1004),  # Dynastream ANT USB Stick
            ]
            for vid, pid in ant_sticks:
                device = usb.core.find(idVendor=vid, idProduct=pid)
                if device:
                    return True, f"Found ANT+ stick (VID:{hex(vid)} PID:{hex(pid)})"
            return False, "No ANT+ USB stick found. Please plug in your ANT+ dongle."
        except Exception as e:
            return False, f"USB detection error: {e}"
        
    def start(self):
        """Initialize ANT+ node and channel"""
        import os
        
        # Check if running with admin privileges on macOS
        if os.name != 'nt' and os.geteuid() != 0:
            print("Warning: Not running as root. ANT+ USB access may fail.")
            print("Try running with: sudo python fit_ant_playback.py")
        
        # First check if device is even present
        found, msg = self._check_usb_device()
        print(msg)
        if not found:
            return False
            
        try:
            # Try using openant
            from openant.easy.node import Node  # type: ignore[import-untyped]
            from openant.easy.channel import Channel  # type: ignore[import-untyped]

            print("Initializing ANT+ node...")
            self.node = Node()
            print("Setting network key...")
            self.node.set_network_key(0x00, bytes(self.NETWORK_KEY))  # type: ignore[arg-type]
            
            print("Creating transmit channel...")
            self.channel = self.node.new_channel(Channel.Type.BIDIRECTIONAL_TRANSMIT)
            self.channel.set_id(self.DEVICE_NUMBER, self.DEVICE_TYPE, self.TRANSMISSION_TYPE)
            self.channel.set_period(self.CHANNEL_PERIOD)
            self.channel.set_rf_freq(self.CHANNEL_FREQUENCY)
            
            print("Opening channel...")
            self.channel.open()
            self.running = True
            print("ANT+ channel opened successfully!")
            return True
            
        except PermissionError as e:
            print(f"Permission denied: {e}")
            print("Run with sudo: sudo python fit_ant_playback.py")
            return False
        except Exception as e:
            print(f"Error starting ANT+: {e}")
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                print("Timeout error - this usually means permission denied.")
                print("On macOS, run with: sudo python fit_ant_playback.py")
            return False
    
    def stop(self):
        """Stop ANT+ broadcast"""
        self.running = False
        if self.channel:
            try:
                self.channel.close()
            except:
                pass
        if self.node:
            try:
                self.node.stop()
            except:
                pass
    
    def broadcast_power_cadence(self, power: int, cadence: int):
        """
        Broadcast power and cadence using ANT+ Bike Power Profile
        
        Data Page 0x10 - Standard Power-Only Main Data Page:
        Byte 0: Data Page Number (0x10)
        Byte 1: Update Event Count
        Byte 2: Pedal Power (0xFF = not used)
        Byte 3: Instantaneous Cadence
        Byte 4-5: Accumulated Power (little-endian)
        Byte 6-7: Instantaneous Power (little-endian)
        """
        if not self.running or not self.channel:
            return
        
        self.event_count = (self.event_count + 1) & 0xFF
        self.accumulated_power = (self.accumulated_power + power) & 0xFFFF
        
        # Clamp values
        power = min(max(power, 0), 65535)
        cadence = min(max(cadence, 0), 254)
        
        # Build data page 0x10 (Standard Power-Only)
        data = bytes([
            0x10,  # Data page number
            self.event_count,  # Update event count
            0xFF,  # Pedal power not used
            cadence,  # Instantaneous cadence
            self.accumulated_power & 0xFF,  # Accumulated power LSB
            (self.accumulated_power >> 8) & 0xFF,  # Accumulated power MSB
            power & 0xFF,  # Instantaneous power LSB
            (power >> 8) & 0xFF  # Instantaneous power MSB
        ])
        
        try:
            self.channel.send_broadcast_data(data)  # type: ignore[arg-type]
        except Exception as e:
            print(f"Broadcast error: {e}")


class ANTBikePowerBroadcasterUSB:
    """
    Direct USB ANT+ broadcaster - bypasses openant for macOS compatibility
    Implements the ANT protocol directly over USB
    """
    
    # ANT+ Constants
    DEVICE_TYPE = 0x0B  # Bike Power
    DEVICE_NUMBER = 12345
    TRANSMISSION_TYPE = 0x05
    CHANNEL_PERIOD = 8182
    CHANNEL_FREQUENCY = 57
    NETWORK_KEY = [0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45]
    
    # ANT Message IDs
    MSG_SYSTEM_RESET = 0x4A
    MSG_SET_NETWORK_KEY = 0x46
    MSG_ASSIGN_CHANNEL = 0x42
    MSG_SET_CHANNEL_ID = 0x51
    MSG_SET_CHANNEL_PERIOD = 0x43
    MSG_SET_CHANNEL_FREQ = 0x45
    MSG_OPEN_CHANNEL = 0x4B
    MSG_CLOSE_CHANNEL = 0x4C
    MSG_BROADCAST_DATA = 0x4E
    MSG_CHANNEL_RESPONSE = 0x40
    MSG_STARTUP = 0x6F
    
    # Channel types
    CHANNEL_TYPE_BIDIRECTIONAL_TRANSMIT = 0x10
    
    def __init__(self):
        self.device = None
        self.ep_out = None
        self.ep_in = None
        self.running = False
        self.event_count = 0
        self.accumulated_power = 0
        self.channel_number = 0
        self.network_number = 0
        self.reader_thread = None
        self._stop_reader = False
        
    def _find_ant_stick(self):
        """Find ANT+ USB stick"""
        try:
            import usb.core  # type: ignore[import-untyped]
            
            ant_sticks = [
                (0x0FCF, 0x1008),  # Dynastream ANT USB-m Stick
                (0x0FCF, 0x1009),  # Dynastream ANT USB2 Stick
                (0x0FCF, 0x1004),  # Dynastream ANT USB Stick
            ]
            
            for vid, pid in ant_sticks:
                device = usb.core.find(idVendor=vid, idProduct=pid)
                if device:
                    return device
            return None
        except ImportError:
            return None
    
    def _build_message(self, msg_id: int, data: bytes) -> bytes:
        """Build an ANT message with sync byte, length, and checksum"""
        sync = 0xA4
        length = len(data)
        msg = bytes([sync, length, msg_id]) + data
        checksum = 0
        for b in msg:
            checksum ^= b
        return msg + bytes([checksum])
    
    def _send_message(self, msg_id: int, data: bytes, timeout: int = 1000) -> bool:
        """Send an ANT message"""
        if not self.device or not self.ep_out:
            return False
        try:
            msg = self._build_message(msg_id, data)
            self.ep_out.write(msg, timeout)
            time.sleep(0.1)  # Delay for device processing
            return True
        except Exception as e:
            print(f"Send error: {e}")
            return False
    
    def _read_response(self, timeout=1000) -> bytes:
        """Read response from ANT stick"""
        if not self.device or not self.ep_in:
            return bytes()
        try:
            data = self.ep_in.read(64, timeout)
            return bytes(data)
        except Exception:
            return bytes()
    
    def start(self):
        """Initialize ANT+ stick with raw USB"""
        import usb.core  # type: ignore[import-untyped]
        import usb.util  # type: ignore[import-untyped]
        
        self.device = self._find_ant_stick()
        if not self.device:
            print("ANT+ USB stick not found")
            return False
            
        try:
            print(f"Found ANT+ device: VID={hex(self.device.idVendor)} PID={hex(self.device.idProduct)}")
            
            # Full USB device reset first
            try:
                self.device.reset()
                time.sleep(0.5)
            except Exception as e:
                print(f"Device reset warning: {e}")
            
            # Reset and configure USB device
            try:
                if self.device.is_kernel_driver_active(0):
                    self.device.detach_kernel_driver(0)
            except Exception:
                pass
            
            # Clear any stale configurations
            try:
                usb.util.dispose_resources(self.device)
            except Exception:
                pass
                
            self.device.set_configuration()
            cfg = self.device.get_active_configuration()
            intf = cfg[(0, 0)]
            
            # Claim the interface explicitly
            try:
                usb.util.claim_interface(self.device, intf)
            except Exception as e:
                print(f"Interface claim warning: {e}")
            
            # Find endpoints
            self.ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
            )
            self.ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
            )
            
            if not self.ep_out or not self.ep_in:
                print("Could not find USB endpoints")
                return False
                
            print("USB endpoints configured")
            
            # Clear any pending data from the input endpoint
            for _ in range(3):
                try:
                    self.ep_in.read(64, 100)
                except Exception:
                    pass
            
            # Reset ANT system
            print("Resetting ANT...")
            self._send_message(self.MSG_SYSTEM_RESET, bytes([0x00]))
            time.sleep(0.5)
            
            # Clear startup message
            for _ in range(3):
                try:
                    self.ep_in.read(64, 200)
                except Exception:
                    pass
            
            # Set network key
            print("Setting network key...")
            network_data = bytes([self.network_number]) + bytes(self.NETWORK_KEY)
            if not self._send_message(self.MSG_SET_NETWORK_KEY, network_data):
                return False
            self._read_response()
            
            # Assign channel (transmit)
            print("Assigning channel...")
            channel_data = bytes([self.channel_number, self.CHANNEL_TYPE_BIDIRECTIONAL_TRANSMIT, self.network_number])
            if not self._send_message(self.MSG_ASSIGN_CHANNEL, channel_data):
                return False
            self._read_response()
            
            # Set channel ID
            print("Setting channel ID...")
            device_num_lsb = self.DEVICE_NUMBER & 0xFF
            device_num_msb = (self.DEVICE_NUMBER >> 8) & 0xFF
            id_data = bytes([self.channel_number, device_num_lsb, device_num_msb, 
                           self.DEVICE_TYPE, self.TRANSMISSION_TYPE])
            if not self._send_message(self.MSG_SET_CHANNEL_ID, id_data):
                return False
            self._read_response()
            
            # Set channel period
            print("Setting channel period...")
            period_lsb = self.CHANNEL_PERIOD & 0xFF
            period_msb = (self.CHANNEL_PERIOD >> 8) & 0xFF
            period_data = bytes([self.channel_number, period_lsb, period_msb])
            if not self._send_message(self.MSG_SET_CHANNEL_PERIOD, period_data):
                return False
            self._read_response()
            
            # Set RF frequency
            print("Setting RF frequency...")
            freq_data = bytes([self.channel_number, self.CHANNEL_FREQUENCY])
            if not self._send_message(self.MSG_SET_CHANNEL_FREQ, freq_data):
                return False
            self._read_response()
            
            # Open channel
            print("Opening channel...")
            if not self._send_message(self.MSG_OPEN_CHANNEL, bytes([self.channel_number])):
                return False
            self._read_response()
            
            self.running = True
            print("ANT+ channel opened successfully!")
            print(f"Broadcasting as Device ID: {self.DEVICE_NUMBER}")
            
            # Start background reader thread to drain incoming data
            self._stop_reader = False
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()
            
            return True
            
        except Exception as e:
            print(f"USB initialization error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _reader_loop(self):
        """Background thread to continuously read from USB to prevent buffer overflow"""
        while not self._stop_reader and self.running and self.ep_in:
            try:
                # Read with short timeout
                data = self.ep_in.read(64, 100)
                # Could process responses here if needed
            except Exception:
                pass
            time.sleep(0.01)  # Small delay to prevent tight loop
    
    def stop(self):
        """Stop ANT+ broadcast"""
        self._stop_reader = True
        if self.reader_thread:
            self.reader_thread.join(timeout=1)
        if self.running and self.device:
            try:
                self._send_message(self.MSG_CLOSE_CHANNEL, bytes([self.channel_number]))
            except:
                pass
        self.running = False
        self.device = None
        
    def broadcast_power_cadence(self, power: int, cadence: int):
        """Broadcast power and cadence data"""
        if not self.running:
            return
            
        self.event_count = (self.event_count + 1) & 0xFF
        self.accumulated_power = (self.accumulated_power + power) & 0xFFFF
        
        # Clamp values
        power = min(max(power, 0), 65535)
        cadence = min(max(cadence, 0), 254)
        
        # Build data page 0x10 (Standard Power-Only)
        # Channel number + 8 bytes of data
        data = bytes([
            self.channel_number,
            0x10,  # Data page number
            self.event_count,  # Update event count
            0xFF,  # Pedal power not used
            cadence,  # Instantaneous cadence
            self.accumulated_power & 0xFF,  # Accumulated power LSB
            (self.accumulated_power >> 8) & 0xFF,  # Accumulated power MSB
            power & 0xFF,  # Instantaneous power LSB
            (power >> 8) & 0xFF  # Instantaneous power MSB
        ])
        
        try:
            # Build message directly for faster broadcast (no sleep)
            msg = self._build_message(self.MSG_BROADCAST_DATA, data)
            self.ep_out.write(msg, 100)  # Short timeout for broadcast
            
            # Drain any incoming responses to prevent buffer overflow
            try:
                self.ep_in.read(64, 10)  # Quick non-blocking read
            except:
                pass
        except Exception as e:
            # Only print errors occasionally to not spam
            if self.event_count % 100 == 1:
                print(f"Broadcast error: {e}")


class FitAntPlaybackApp:
    """Main application GUI with dark theme"""

    # Color palette
    BG_DARK = "#1e1e2e"
    BG_MEDIUM = "#2a2a3d"
    BG_LIGHT = "#363650"
    BG_INPUT = "#44446a"
    FG_PRIMARY = "#e0e0f0"
    FG_SECONDARY = "#a0a0c0"
    FG_DIM = "#707090"
    ACCENT = "#6c8cff"
    ACCENT_HOVER = "#8aa4ff"
    SUCCESS = "#50c878"
    WARNING = "#ffb347"
    ERROR = "#ff6b6b"

    # Power zone colors
    ZONE_COLORS = [
        (0, "#a0a0c0"),       # 0 W — gray
        (100, "#50c878"),     # green
        (200, "#8cd96c"),     # light green
        (300, "#ffdd57"),     # yellow
        (400, "#ffb347"),     # orange
        (600, "#ff6b6b"),     # red
        (1000, "#ff3860"),    # deep red
    ]

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FIT ANT+ Playback")
        self.root.geometry("1050x750")
        self.root.resizable(True, True)
        self.root.configure(bg=self.BG_DARK)
        self.root.minsize(900, 650)

        self.fit_records: List[PowerCadenceRecord] = []
        self.broadcaster = None
        self.playback_thread = None
        self.is_playing = False
        self.is_paused = False
        self.current_index = 0
        self.playback_speed = 1.0

        # Manual mode state
        self.manual_broadcasting = False
        self.manual_thread = None

        # FIT file info vars (set in _build_fit_tab)
        self.records_var: tk.StringVar = tk.StringVar(value="0")
        self.duration_var: tk.StringVar = tk.StringVar(value="00:00:00")
        self.avg_power_var: tk.StringVar = tk.StringVar(value="0 W")
        self.avg_cadence_var: tk.StringVar = tk.StringVar(value="0 RPM")

        self._setup_styles()
        self._setup_ui()

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _setup_styles(self):
        """Configure dark-theme ttk styles"""
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Frames
        self.style.configure("Dark.TFrame", background=self.BG_DARK)
        self.style.configure("Card.TFrame", background=self.BG_MEDIUM)

        # Labels
        self.style.configure("Dark.TLabel", background=self.BG_DARK,
                             foreground=self.FG_PRIMARY, font=("Helvetica", 11))
        self.style.configure("Card.TLabel", background=self.BG_MEDIUM,
                             foreground=self.FG_PRIMARY, font=("Helvetica", 11))
        self.style.configure("Dim.TLabel", background=self.BG_MEDIUM,
                             foreground=self.FG_SECONDARY, font=("Helvetica", 10))
        self.style.configure("Heading.TLabel", background=self.BG_DARK,
                             foreground=self.FG_PRIMARY, font=("Helvetica", 13, "bold"))
        self.style.configure("BigValue.TLabel", background=self.BG_MEDIUM,
                             foreground=self.ACCENT, font=("Helvetica Neue", 32, "bold"))
        self.style.configure("ValueUnit.TLabel", background=self.BG_MEDIUM,
                             foreground=self.FG_DIM, font=("Helvetica", 11))
        self.style.configure("Status.TLabel", background=self.BG_MEDIUM,
                             foreground=self.WARNING, font=("Helvetica", 11, "bold"))

        # LabelFrames
        self.style.configure("Dark.TLabelframe", background=self.BG_MEDIUM,
                             foreground=self.FG_SECONDARY, borderwidth=1,
                             relief="flat")
        self.style.configure("Dark.TLabelframe.Label", background=self.BG_MEDIUM,
                             foreground=self.ACCENT, font=("Helvetica", 11, "bold"))

        # Buttons
        self.style.configure("Accent.TButton", font=("Helvetica", 11, "bold"),
                             padding=(14, 8))
        self.style.map("Accent.TButton",
                       background=[("active", self.ACCENT_HOVER),
                                   ("!active", self.ACCENT)],
                       foreground=[("active", "#ffffff"), ("!active", "#ffffff")])

        self.style.configure("Secondary.TButton", font=("Helvetica", 10),
                             padding=(10, 6))
        self.style.map("Secondary.TButton",
                       background=[("active", self.BG_LIGHT),
                                   ("!active", self.BG_INPUT)],
                       foreground=[("active", self.FG_PRIMARY),
                                   ("!active", self.FG_PRIMARY)])

        self.style.configure("Success.TButton", font=("Helvetica", 11, "bold"),
                             padding=(14, 8))
        self.style.map("Success.TButton",
                       background=[("active", "#3da863"), ("!active", self.SUCCESS)],
                       foreground=[("active", "#ffffff"), ("!active", "#ffffff")])

        self.style.configure("Danger.TButton", font=("Helvetica", 11, "bold"),
                             padding=(14, 8))
        self.style.map("Danger.TButton",
                       background=[("active", "#e05555"), ("!active", self.ERROR)],
                       foreground=[("active", "#ffffff"), ("!active", "#ffffff")])

        # Entry
        self.style.configure("Dark.TEntry", fieldbackground=self.BG_INPUT,
                             foreground=self.FG_PRIMARY, insertcolor=self.FG_PRIMARY,
                             borderwidth=1)

        # Combobox
        self.style.configure("Dark.TCombobox", fieldbackground=self.BG_INPUT,
                             foreground=self.FG_PRIMARY, selectbackground=self.ACCENT,
                             selectforeground="#ffffff")
        self.style.map("Dark.TCombobox",
                       fieldbackground=[("readonly", self.BG_INPUT)],
                       foreground=[("readonly", self.FG_PRIMARY)])

        # Progressbar
        self.style.configure("Accent.Horizontal.TProgressbar",
                             troughcolor=self.BG_INPUT,
                             background=self.ACCENT, thickness=12)

        # Notebook (tabs)
        self.style.configure("Dark.TNotebook", background=self.BG_DARK,
                             borderwidth=0)
        self.style.configure("Dark.TNotebook.Tab",
                             background=self.BG_LIGHT,
                             foreground=self.FG_SECONDARY,
                             font=("Helvetica", 11, "bold"),
                             padding=(18, 8))
        self.style.map("Dark.TNotebook.Tab",
                       background=[("selected", self.ACCENT)],
                       foreground=[("selected", "#ffffff")])

        # Scale (slider)
        self.style.configure("Accent.Horizontal.TScale",
                             troughcolor=self.BG_INPUT,
                             background=self.ACCENT,
                             sliderthickness=20)

        # Scrollbar
        self.style.configure("Dark.Vertical.TScrollbar",
                             troughcolor=self.BG_DARK,
                             background=self.BG_LIGHT)

    # ------------------------------------------------------------------
    # UI Layout
    # ------------------------------------------------------------------
    def _setup_ui(self):
        """Setup the user interface"""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.root, style="Dark.TFrame", padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        # rows: 0=title, 1=ant, 2=tabs, 3=current vals, 4=log
        outer.rowconfigure(2, weight=0)
        outer.rowconfigure(4, weight=1)

        # ---- Title bar ----
        title_lbl = ttk.Label(outer, text="FIT ANT+ Playback",
                              style="Heading.TLabel",
                              font=("Helvetica Neue", 18, "bold"))
        title_lbl.grid(row=0, column=0, sticky="w", pady=(0, 8))

        # ---- ANT+ connection row ----
        ant_frame = ttk.Frame(outer, style="Card.TFrame", padding=10)
        ant_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ant_frame.columnconfigure(1, weight=1)

        ttk.Label(ant_frame, text="ANT+ Status:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.ant_status_var = tk.StringVar(value="Not Connected")
        self.ant_status_label = ttk.Label(ant_frame, textvariable=self.ant_status_var,
                                          style="Status.TLabel")
        self.ant_status_label.grid(row=0, column=1, sticky="w")

        self.connect_btn = ttk.Button(ant_frame, text="Connect ANT+",
                                      command=self._connect_ant, style="Accent.TButton")
        self.connect_btn.grid(row=0, column=2, padx=(8, 0))

        # ---- Notebook (tabs) ----
        self.notebook = ttk.Notebook(outer, style="Dark.TNotebook")
        self.notebook.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self._build_fit_tab()
        self._build_manual_tab()

        # ---- Current values ----
        self._build_current_values(outer, row=3)

        # ---- Log ----
        self._build_log(outer, row=4)

        self._log("FIT ANT+ Playback ready")
        self._log("Select a FIT file or switch to Manual Power mode")

    # ---------- FIT Playback tab ----------
    def _build_fit_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame", padding=10)
        self.notebook.add(tab, text="  FIT File Playback  ")
        tab.columnconfigure(0, weight=1)

        # File selection
        file_frame = ttk.LabelFrame(tab, text="FIT File", style="Dark.TLabelframe",
                                    padding=8)
        file_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        file_frame.columnconfigure(1, weight=1)

        ttk.Label(file_frame, text="File:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.file_path_var = tk.StringVar()
        self.file_entry = ttk.Entry(file_frame, textvariable=self.file_path_var,
                                    state="readonly", style="Dark.TEntry")
        self.file_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.browse_btn = ttk.Button(file_frame, text="Browse...",
                                     command=self._browse_file, style="Secondary.TButton")
        self.browse_btn.grid(row=0, column=2)

        # File info
        info_frame = ttk.LabelFrame(tab, text="File Info", style="Dark.TLabelframe",
                                    padding=8)
        info_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        for c in (1, 3):
            info_frame.columnconfigure(c, weight=1)

        for r, (lbl, sv) in enumerate([
            ("Records:", self.records_var),
            ("Duration:", self.duration_var),
        ]):
            ttk.Label(info_frame, text=lbl, style="Dim.TLabel"
                      ).grid(row=r, column=0, sticky="w", padx=(0, 4))
            ttk.Label(info_frame, textvariable=sv, style="Card.TLabel"
                      ).grid(row=r, column=1, sticky="w")

        for r, (lbl, sv) in enumerate([
            ("Avg Power:", self.avg_power_var),
            ("Avg Cadence:", self.avg_cadence_var),
        ]):
            ttk.Label(info_frame, text=lbl, style="Dim.TLabel"
                      ).grid(row=r, column=2, sticky="w", padx=(16, 4))
            ttk.Label(info_frame, textvariable=sv, style="Card.TLabel"
                      ).grid(row=r, column=3, sticky="w")

        # Playback controls
        play_frame = ttk.LabelFrame(tab, text="Playback", style="Dark.TLabelframe",
                                    padding=8)
        play_frame.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        play_frame.columnconfigure(1, weight=1)

        # Progress
        ttk.Label(play_frame, text="Progress:", style="Dim.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(play_frame, variable=self.progress_var,
                                            maximum=100,
                                            style="Accent.Horizontal.TProgressbar")
        self.progress_bar.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        self.time_var = tk.StringVar(value="00:00:00 / 00:00:00")
        ttk.Label(play_frame, textvariable=self.time_var, style="Dim.TLabel"
                  ).grid(row=1, column=1, sticky="w")

        # Speed
        ttk.Label(play_frame, text="Speed:", style="Dim.TLabel"
                  ).grid(row=2, column=0, sticky="w", padx=(0, 6))
        self.speed_var = tk.StringVar(value="1.0x")
        speed_combo = ttk.Combobox(play_frame, textvariable=self.speed_var,
                                   values=["0.5x", "1.0x", "1.5x", "2.0x", "4.0x"],
                                   width=8, style="Dark.TCombobox", state="readonly")
        speed_combo.grid(row=2, column=1, sticky="w")
        speed_combo.bind("<<ComboboxSelected>>", self._on_speed_change)

        # Buttons
        btn_frame = ttk.Frame(play_frame, style="Dark.TLabelframe")
        btn_frame.grid(row=3, column=0, columnspan=4, pady=(8, 0))

        self.play_btn = ttk.Button(btn_frame, text="Play",
                                   command=self._play, style="Success.TButton", width=10)
        self.play_btn.grid(row=0, column=0, padx=4)

        self.pause_btn = ttk.Button(btn_frame, text="Pause",
                                    command=self._pause, style="Secondary.TButton",
                                    width=10, state="disabled")
        self.pause_btn.grid(row=0, column=1, padx=4)

        self.stop_btn = ttk.Button(btn_frame, text="Stop",
                                   command=self._stop, style="Danger.TButton",
                                   width=10, state="disabled")
        self.stop_btn.grid(row=0, column=2, padx=4)

    # ---------- Manual Power tab ----------
    def _build_manual_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame", padding=10)
        self.notebook.add(tab, text="  Manual Power  ")
        tab.columnconfigure(0, weight=1)

        # Power control
        pwr_frame = ttk.LabelFrame(tab, text="Power (Watts)",
                                   style="Dark.TLabelframe", padding=10)
        pwr_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        pwr_frame.columnconfigure(1, weight=1)

        self.manual_power_var = tk.IntVar(value=300)

        ttk.Label(pwr_frame, text="Watts:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.power_slider = ttk.Scale(pwr_frame, from_=0, to=2000,
                                      orient="horizontal",
                                      variable=self.manual_power_var,
                                      command=self._on_power_slider_change,
                                      style="Accent.Horizontal.TScale")
        self.power_slider.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        # Validation: register a callback that allows only integers 0-2000
        vcmd_power = (self.root.register(self._validate_power_entry), "%P")
        self.power_entry = ttk.Entry(pwr_frame, width=6, justify="center",
                                     style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                     validate="key", validatecommand=vcmd_power)
        self.power_entry.grid(row=0, column=2, padx=(0, 4))
        self.power_entry.insert(0, "300")
        self.power_entry.bind("<Return>", self._on_power_entry_change)
        self.power_entry.bind("<FocusOut>", self._on_power_entry_change)

        ttk.Label(pwr_frame, text="W", style="Dim.TLabel"
                  ).grid(row=0, column=3, sticky="w")

        # Quick-set buttons
        qf = ttk.Frame(pwr_frame, style="Dark.TLabelframe")
        qf.grid(row=1, column=0, columnspan=4, pady=(8, 0))
        for watts in (0, 150, 200, 250, 283, 300, 350, 400, 500, 600, 800, 1000, 1200):
            b = ttk.Button(qf, text=f"{watts}",
                           command=lambda w=watts: self._set_manual_power(w),
                           style="Secondary.TButton", width=5)
            b.pack(side="left", padx=2)

        # W/kg control
        wkg_frame = ttk.LabelFrame(tab, text="W/kg",
                                   style="Dark.TLabelframe", padding=10)
        wkg_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(wkg_frame, text="Weight (kg):", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        vcmd_weight = (self.root.register(self._validate_weight_entry), "%P")
        self.weight_entry = ttk.Entry(wkg_frame, width=6, justify="center",
                                      style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                      validate="key", validatecommand=vcmd_weight)
        self.weight_entry.grid(row=0, column=1, padx=(0, 4))
        self.weight_entry.insert(0, "75")
        ttk.Label(wkg_frame, text="kg", style="Dim.TLabel"
                  ).grid(row=0, column=2, sticky="w", padx=(0, 20))

        ttk.Label(wkg_frame, text="W/kg:", style="Card.TLabel"
                  ).grid(row=0, column=3, sticky="w", padx=(0, 8))

        vcmd_wkg = (self.root.register(self._validate_wkg_entry), "%P")
        self.wkg_entry = ttk.Entry(wkg_frame, width=6, justify="center",
                                   style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                   validate="key", validatecommand=vcmd_wkg)
        self.wkg_entry.grid(row=0, column=4, padx=(0, 4))
        self.wkg_entry.bind("<Return>", self._on_wkg_entry_change)
        self.wkg_entry.bind("<FocusOut>", self._on_wkg_entry_change)

        ttk.Label(wkg_frame, text="W/kg", style="Dim.TLabel"
                  ).grid(row=0, column=5, sticky="w", padx=(0, 8))

        self.wkg_apply_btn = ttk.Button(wkg_frame, text="Apply",
                                        command=self._on_wkg_entry_change,
                                        style="Secondary.TButton", width=6)
        self.wkg_apply_btn.grid(row=0, column=6, padx=(8, 0))

        # Cadence control
        cad_frame = ttk.LabelFrame(tab, text="Cadence (RPM)",
                                   style="Dark.TLabelframe", padding=10)
        cad_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        cad_frame.columnconfigure(1, weight=1)

        self.manual_cadence_var = tk.IntVar(value=85)

        ttk.Label(cad_frame, text="RPM:", style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.cadence_slider = ttk.Scale(cad_frame, from_=0, to=200,
                                        orient="horizontal",
                                        variable=self.manual_cadence_var,
                                        command=self._on_cadence_slider_change,
                                        style="Accent.Horizontal.TScale")
        self.cadence_slider.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        vcmd_cadence = (self.root.register(self._validate_cadence_entry), "%P")
        self.cadence_entry = ttk.Entry(cad_frame, width=6, justify="center",
                                       style="Dark.TEntry", font=("Helvetica", 14, "bold"),
                                       validate="key", validatecommand=vcmd_cadence)
        self.cadence_entry.grid(row=0, column=2, padx=(0, 4))
        self.cadence_entry.insert(0, "85")
        self.cadence_entry.bind("<Return>", self._on_cadence_entry_change)
        self.cadence_entry.bind("<FocusOut>", self._on_cadence_entry_change)

        ttk.Label(cad_frame, text="RPM", style="Dim.TLabel"
                  ).grid(row=0, column=3, sticky="w")

        # Start / stop manual broadcast
        ctrl_frame = ttk.Frame(tab, style="Dark.TFrame")
        ctrl_frame.grid(row=3, column=0, pady=(4, 0))

        self.manual_start_btn = ttk.Button(ctrl_frame, text="Start Broadcasting",
                                           command=self._start_manual,
                                           style="Success.TButton", width=20)
        self.manual_start_btn.grid(row=0, column=0, padx=6)

        self.manual_stop_btn = ttk.Button(ctrl_frame, text="Stop Broadcasting",
                                          command=self._stop_manual,
                                          style="Danger.TButton", width=20,
                                          state="disabled")
        self.manual_stop_btn.grid(row=0, column=1, padx=6)

    # ---------- Current values display ----------
    def _build_current_values(self, parent, row):
        cf = ttk.Frame(parent, style="Card.TFrame", padding=14)
        cf.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        cf.columnconfigure(1, weight=1)
        cf.columnconfigure(4, weight=1)

        ttk.Label(cf, text="POWER", style="Dim.TLabel"
                  ).grid(row=0, column=0, sticky="w", padx=(4, 8))
        self.current_power_var = tk.StringVar(value="---")
        self.power_value_label = tk.Label(cf, textvariable=self.current_power_var,
                                          font=("Helvetica Neue", 36, "bold"),
                                          fg=self.ACCENT, bg=self.BG_MEDIUM)
        self.power_value_label.grid(row=0, column=1, sticky="w")
        ttk.Label(cf, text="W", style="ValueUnit.TLabel"
                  ).grid(row=0, column=2, sticky="sw", padx=(2, 30), pady=(0, 6))

        ttk.Label(cf, text="CADENCE", style="Dim.TLabel"
                  ).grid(row=0, column=3, sticky="w", padx=(4, 8))
        self.current_cadence_var = tk.StringVar(value="---")
        self.cadence_value_label = tk.Label(cf, textvariable=self.current_cadence_var,
                                            font=("Helvetica Neue", 36, "bold"),
                                            fg=self.ACCENT, bg=self.BG_MEDIUM)
        self.cadence_value_label.grid(row=0, column=4, sticky="w")
        ttk.Label(cf, text="RPM", style="ValueUnit.TLabel"
                  ).grid(row=0, column=5, sticky="sw", padx=(2, 4), pady=(0, 6))

    # ---------- Log ----------
    def _build_log(self, parent, row):
        lf = ttk.LabelFrame(parent, text="Log", style="Dark.TLabelframe", padding=6)
        lf.grid(row=row, column=0, sticky="nsew", pady=(0, 0))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)

        self.log_text = tk.Text(lf, height=6, state="disabled",
                                bg=self.BG_DARK, fg=self.FG_SECONDARY,
                                insertbackground=self.FG_PRIMARY,
                                selectbackground=self.ACCENT,
                                font=("Menlo", 10), borderwidth=0,
                                highlightthickness=0)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(lf, orient=tk.VERTICAL,
                                  command=self.log_text.yview,
                                  style="Dark.Vertical.TScrollbar")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text["yscrollcommand"] = scrollbar.set

    # ------------------------------------------------------------------
    # Power color helper
    # ------------------------------------------------------------------
    def _color_for_power(self, watts: int) -> str:
        color = self.ZONE_COLORS[0][1]
        for threshold, c in self.ZONE_COLORS:
            if watts >= threshold:
                color = c
        return color

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _log(self, message: str):
        """Add message to log"""
        self.log_text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # FIT File Playback methods
    # ------------------------------------------------------------------
    def _browse_file(self):
        """Open file browser to select FIT file"""
        filepath = filedialog.askopenfilename(
            title="Select FIT File",
            filetypes=[("FIT files", "*.fit"), ("All files", "*.*")]
        )
        if filepath:
            self.file_path_var.set(filepath)
            self._load_fit_file(filepath)

    def _load_fit_file(self, filepath: str):
        """Load and parse FIT file"""
        try:
            parser = FitFileParser()
            self.fit_records = parser.parse(filepath)

            if not self.fit_records:
                self._log("No power/cadence data found in file")
                messagebox.showwarning("Warning",
                                       "No power or cadence data found in the FIT file")
                return

            self.records_var.set(str(len(self.fit_records)))

            if self.fit_records:
                duration_secs = self.fit_records[-1].timestamp
                hours = int(duration_secs // 3600)
                minutes = int((duration_secs % 3600) // 60)
                seconds = int(duration_secs % 60)
                self.duration_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

                powers = [r.power for r in self.fit_records if r.power > 0]
                cadences = [r.cadence for r in self.fit_records if r.cadence > 0]
                avg_power = sum(powers) / len(powers) if powers else 0
                avg_cadence = sum(cadences) / len(cadences) if cadences else 0
                self.avg_power_var.set(f"{avg_power:.0f} W")
                self.avg_cadence_var.set(f"{avg_cadence:.0f} RPM")

            self._log(f"Loaded {len(self.fit_records)} records from {Path(filepath).name}")

        except ImportError as e:
            self._log(f"Error: {e}")
            messagebox.showerror("Error", str(e))
        except Exception as e:
            self._log(f"Error loading file: {e}")
            messagebox.showerror("Error", f"Failed to load FIT file: {e}")

    def _connect_ant(self):
        """Connect to ANT+ USB stick"""
        import os

        if self.broadcaster and self.broadcaster.running:
            self.broadcaster.stop()
            self.broadcaster = None
            self.ant_status_var.set("Not Connected")
            self.connect_btn.configure(text="Connect ANT+")
            self._log("ANT+ disconnected")
            return

        is_root = os.name == "nt" or os.geteuid() == 0
        if not is_root:
            self._log("WARNING: Not running with admin privileges!")
            self._log("ANT+ USB access requires sudo on macOS")
            self._log("Restart with: sudo python fit_ant_playback.py")

        self._log("Connecting to ANT+ USB stick...")

        try:
            self.broadcaster = ANTBikePowerBroadcasterUSB()
            if self.broadcaster.start():
                self.ant_status_var.set("Connected")
                self.ant_status_label.configure(foreground=self.SUCCESS)
                self.connect_btn.configure(text="Disconnect")
                self._log("ANT+ connected successfully")
                self._log(f"Device ID: {self.broadcaster.DEVICE_NUMBER}, Type: Bike Power")
            else:
                self.ant_status_var.set("Connection Failed")
                self.ant_status_label.configure(foreground=self.ERROR)
                self._log("Failed to connect to ANT+ stick")

                if not is_root:
                    messagebox.showerror("Permission Denied",
                        "ANT+ USB access requires admin privileges on macOS.\n\n"
                        "Please restart the app with sudo:\n\n"
                        "sudo python fit_ant_playback.py\n\n"
                        "Or use the run_with_sudo.command script.")
                else:
                    messagebox.showerror("Error",
                        "Failed to connect to ANT+ USB stick.\n\n"
                        "Make sure:\n"
                        "- ANT+ USB stick is plugged in\n"
                        "- No other application is using it (Zwift, TrainerRoad, etc.)")
                self.broadcaster = None
        except Exception as e:
            self._log(f"ANT+ error: {e}")
            messagebox.showerror("Error", f"ANT+ connection error: {e}")
            self.broadcaster = None

    def _on_speed_change(self, event=None):
        """Handle playback speed change"""
        speed_str = self.speed_var.get()
        self.playback_speed = float(speed_str.replace("x", ""))
        self._log(f"Playback speed set to {speed_str}")

    def _play(self):
        """Start or resume playback"""
        if self.manual_broadcasting:
            messagebox.showwarning("Warning",
                                   "Stop manual broadcasting before playing a FIT file")
            return
        if not self.fit_records:
            messagebox.showwarning("Warning", "Please load a FIT file first")
            return
        if not self.broadcaster or not self.broadcaster.running:
            messagebox.showwarning("Warning", "Please connect ANT+ first")
            return

        if self.is_paused:
            self.is_paused = False
            self._log("Playback resumed")
        else:
            self.is_playing = True
            self.current_index = 0
            self.playback_thread = threading.Thread(target=self._playback_loop,
                                                    daemon=True)
            self.playback_thread.start()
            self._log("Playback started")

        self.play_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")
        self.browse_btn.configure(state="disabled")

    def _pause(self):
        """Pause playback"""
        self.is_paused = True
        self.play_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self._log("Playback paused")

    def _stop(self):
        """Stop playback"""
        self.is_playing = False
        self.is_paused = False
        self.current_index = 0

        self.play_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self.browse_btn.configure(state="normal")

        self.progress_var.set(0)
        self.current_power_var.set("---")
        self.current_cadence_var.set("---")
        self.power_value_label.configure(fg=self.ACCENT)
        self._log("Playback stopped")

    def _playback_loop(self):
        """Main playback loop running in separate thread"""
        start_time = time.time()
        total_duration = self.fit_records[-1].timestamp if self.fit_records else 0

        while self.is_playing and self.current_index < len(self.fit_records):
            if self.is_paused:
                time.sleep(0.1)
                start_time = (time.time()
                              - self.fit_records[self.current_index].timestamp
                              / self.playback_speed)
                continue

            record = self.fit_records[self.current_index]
            target_time = record.timestamp / self.playback_speed
            elapsed = time.time() - start_time

            if elapsed < target_time:
                time.sleep(min(target_time - elapsed, 0.1))
                continue

            if self.broadcaster and self.broadcaster.running:
                self.broadcaster.broadcast_power_cadence(record.power, record.cadence)

            self.root.after(0, self._update_playback_ui, record, total_duration)
            self.current_index += 1
            time.sleep(0.01)

        if self.is_playing:
            self.root.after(0, self._playback_finished)

    def _update_playback_ui(self, record: PowerCadenceRecord, total_duration: float):
        """Update UI during playback (called from main thread)"""
        self.current_power_var.set(str(record.power))
        self.current_cadence_var.set(str(record.cadence))
        self.power_value_label.configure(fg=self._color_for_power(record.power))

        progress = (record.timestamp / total_duration * 100) if total_duration > 0 else 0
        self.progress_var.set(progress)

        current_secs = record.timestamp
        curr_h = int(current_secs // 3600)
        curr_m = int((current_secs % 3600) // 60)
        curr_s = int(current_secs % 60)

        total_h = int(total_duration // 3600)
        total_m = int((total_duration % 3600) // 60)
        total_s = int(total_duration % 60)

        self.time_var.set(
            f"{curr_h:02d}:{curr_m:02d}:{curr_s:02d} / "
            f"{total_h:02d}:{total_m:02d}:{total_s:02d}")

    def _playback_finished(self):
        """Called when playback completes"""
        self._log("Playback finished")
        self._stop()

    # ------------------------------------------------------------------
    # Manual Power methods
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_power_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = int(value)
            return 0 <= v <= 2000
        except ValueError:
            return False

    @staticmethod
    def _validate_cadence_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = int(value)
            return 0 <= v <= 200
        except ValueError:
            return False

    def _on_power_slider_change(self, value):
        """Slider moved — update entry box"""
        watts = int(float(value))
        self.power_entry.delete(0, tk.END)
        self.power_entry.insert(0, str(watts))

    def _on_power_entry_change(self, event=None):
        """Entry box changed — update slider"""
        txt = self.power_entry.get().strip()
        if txt == "":
            return
        try:
            watts = max(0, min(2000, int(txt)))
            self.manual_power_var.set(watts)
        except ValueError:
            pass

    def _on_cadence_slider_change(self, value):
        """Slider moved — update entry box"""
        rpm = int(float(value))
        self.cadence_entry.delete(0, tk.END)
        self.cadence_entry.insert(0, str(rpm))

    def _on_cadence_entry_change(self, event=None):
        """Entry box changed — update slider"""
        txt = self.cadence_entry.get().strip()
        if txt == "":
            return
        try:
            rpm = max(0, min(200, int(txt)))
            self.manual_cadence_var.set(rpm)
        except ValueError:
            pass

    @staticmethod
    def _validate_weight_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = float(value)
            return 0 < v <= 300
        except ValueError:
            return False

    @staticmethod
    def _validate_wkg_entry(value: str) -> bool:
        if value == "":
            return True
        try:
            v = float(value)
            return 0 <= v <= 30
        except ValueError:
            return False

    def _on_wkg_entry_change(self, event=None):
        """W/kg entry changed — compute watts from W/kg * weight and set power"""
        wkg_txt = self.wkg_entry.get().strip()
        weight_txt = self.weight_entry.get().strip()
        if not wkg_txt or not weight_txt:
            return
        try:
            wkg = float(wkg_txt)
            weight = float(weight_txt)
            watts = max(0, min(2000, int(round(wkg * weight))))
            self._set_manual_power(watts)
        except ValueError:
            pass

    def _set_manual_power(self, watts: int):
        """Quick-set power from preset button"""
        self.manual_power_var.set(watts)
        self.power_entry.delete(0, tk.END)
        self.power_entry.insert(0, str(watts))

    def _start_manual(self):
        """Start manual power broadcast"""
        if self.is_playing:
            messagebox.showwarning("Warning",
                                   "Stop FIT playback before starting manual mode")
            return
        if not self.broadcaster or not self.broadcaster.running:
            messagebox.showwarning("Warning", "Please connect ANT+ first")
            return

        self.manual_broadcasting = True
        self.manual_start_btn.configure(state="disabled")
        self.manual_stop_btn.configure(state="normal")
        self.manual_thread = threading.Thread(target=self._manual_broadcast_loop,
                                              daemon=True)
        self.manual_thread.start()
        self._log("Manual broadcast started")

    def _stop_manual(self):
        """Stop manual power broadcast"""
        self.manual_broadcasting = False
        self.manual_start_btn.configure(state="normal")
        self.manual_stop_btn.configure(state="disabled")
        self.current_power_var.set("---")
        self.current_cadence_var.set("---")
        self.power_value_label.configure(fg=self.ACCENT)
        self._log("Manual broadcast stopped")

    def _manual_broadcast_loop(self):
        """Broadcast manual power/cadence at ~4 Hz"""
        while self.manual_broadcasting:
            if not self.broadcaster or not self.broadcaster.running:
                self.root.after(0, self._stop_manual)
                self.root.after(0, self._log, "ANT+ disconnected — manual broadcast stopped")
                break

            power = self.manual_power_var.get()
            cadence = self.manual_cadence_var.get()
            self.broadcaster.broadcast_power_cadence(power, cadence)
            self.root.after(0, self._update_manual_ui, power, cadence)
            time.sleep(0.25)  # ~4 Hz

    def _update_manual_ui(self, power: int, cadence: int):
        """Update current-value display for manual mode"""
        self.current_power_var.set(str(power))
        self.current_cadence_var.set(str(cadence))
        self.power_value_label.configure(fg=self._color_for_power(power))

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self):
        """Start the application"""
        self.root.mainloop()

        # Cleanup on exit
        self.manual_broadcasting = False
        if self.broadcaster:
            self.broadcaster.stop()


def main():
    """Main entry point"""
    # Check dependencies
    if fitdecode is None:
        print("Error: fitdecode library not installed")
        print("Install with: pip install fitdecode")
        
        # Show GUI error
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Missing Dependency", 
            "The 'fitdecode' library is required.\n\n"
            "Install it with:\npip install fitdecode")
        return
    
    if not ANT_AVAILABLE:
        print("Warning: openant library not installed")
        print("ANT+ features will not work")
        print("Install with: pip install openant")
    
    app = FitAntPlaybackApp()
    app.run()


if __name__ == "__main__":
    main()
