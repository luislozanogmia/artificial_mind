#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AX Inspector - Research Preview CLI Wrapper
===========================================

Click-based accessibility inspector for macOS using the unified AX Engine.
Records detailed element information on each mouse click for automation development.

Usage:
    python test_ax_inspector.py

Features:
- Real-time click inspection with comprehensive AX data
- Automatic JSON export to inspector.json  
- Clean signal handling (Ctrl+C to save and exit)
- Research preview of advanced accessibility analysis

Part of the AX Executor research preview - experimental automation technology.
"""

import sys
import json
import signal
import os
from ax_executor import AXEngine

from AppKit import NSWorkspace

# Event tap imports
from Quartz import (
    CGEventTapCreate, CGEventTapEnable, CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource, CFRunLoopGetCurrent, kCFRunLoopCommonModes,
    kCGHeadInsertEventTap, kCGEventLeftMouseDown, kCGEventRightMouseDown,
    CGEventGetLocation,
)

# Runtime management
STOP_REQUESTED = False
RUN_LOOP = None

def _handle_signal(sig, frame):
    """Signal handler for clean shutdown."""
    global STOP_REQUESTED
    STOP_REQUESTED = True
    try:
        import CoreFoundation
        rl = RUN_LOOP or CoreFoundation.CFRunLoopGetCurrent()
        CoreFoundation.CFRunLoopStop(rl)
    except Exception:
        pass
    print(f"\n[SIGNAL] Received {sig}. Requesting shutdown…")

def _install_stop_timer():
    """Create periodic timer to check stop requests."""
    try:
        import CoreFoundation as CF
        def _timer_cb(timer, info):
            if STOP_REQUESTED:
                rl = RUN_LOOP or CF.CFRunLoopGetCurrent()
                try:
                    CF.CFRunLoopStop(rl)
                except Exception:
                    pass
        
        # Fire after 0.1s, repeat every 0.1s
        timer = CF.CFRunLoopTimerCreate(None, CF.CFAbsoluteTimeGetCurrent() + 0.1, 0.1, 0, 0, _timer_cb, None)
        CF.CFRunLoopAddTimer(CF.CFRunLoopGetCurrent(), timer, kCFRunLoopCommonModes)
        return timer
    except Exception as e:
        print(f"[WARN] Could not install stop timer: {e}")
        return None

def _event_mask(*event_types):
    """
    Build CGEventMask without relying on kCGEventMaskBit constant.
    
    Constructs event mask by bit-shifting event type IDs. This is more
    reliable than using kCGEventMaskBit which may not be available in
    all PyObjC versions.
    
    Args:
        *event_types: Variable number of CGEvent type constants
        
    Returns:
        int: Bitmask for event tap creation
    """
    mask = 0
    for t in event_types:
        try:
            mask |= (1 << int(t))
        except Exception:
            pass
    return mask

class AXInspectorCLI:
    """CLI wrapper for AX inspection using unified engine."""
    
    def __init__(self):
        self.engine = AXEngine()
        self.inspector_path = os.path.join(os.getcwd(), "inspector.json")
    
    def _event_callback(self, proxy, etype, event, refcon):
        """Process mouse click events."""
        try:
            if etype in (kCGEventLeftMouseDown, kCGEventRightMouseDown):
                loc = CGEventGetLocation(event)
                data = self.engine.inspect_step(loc.x, loc.y, save_to_buffer=True)
                
                # Display summary
                summary_parts = []
                if data.get('role'):
                    summary_parts.append(str(data['role']))
                if data.get('best_label') or data.get('title'):
                    summary_parts.append(str(data.get('best_label') or data.get('title')))
                if data.get('app_name'):
                    summary_parts.append(str(data['app_name']))
                
                summary = ' • '.join(filter(None, summary_parts))
                print(summary.strip())
                print(json.dumps(data, ensure_ascii=False, indent=2))
                sys.stdout.flush()

                if data.get("schema_version"):
                    print(f"[INFO] schema version: {data['schema_version']}")

                try:
                    front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
                    is_frontmost = (front_app and front_app.localizedName() == data.get("app_name"))
                    print(f"🖥️ frontmost: {'✅ yes' if is_frontmost else '❌ no'}")
                except Exception as fe:
                    print(f"[DEBUG] frontmost check failed: {fe}")
                
                # Status update
                buffer_size = len(self.engine.recorded_buffer)
                print(f"[BUFFERED] Click #{data.get('click_index', buffer_size-1)} (session total: {buffer_size})")
                
        except Exception as e:
            print(f"[ERROR] {e}")
            print(json.dumps({"error": str(e)}))
            sys.stdout.flush()
        
        return event  # Always pass event through

    def run(self):
        """Main inspection loop."""
        # Setup
        print(f"[INFO] This run will overwrite: {self.inspector_path}")
        self.engine.clear_buffer()
        
        # Signal handling
        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except Exception as sig_e:
            print(f"[WARN] Could not register signal handlers: {sig_e}")
        
        # Check accessibility permissions
        from ApplicationServices import AXIsProcessTrusted
        if not AXIsProcessTrusted():
            print("[AX] This process is not trusted. Enable Accessibility permissions and rerun.")
            sys.exit(1)
        
        # Create event tap
        tap = CGEventTapCreate(
            kCGHeadInsertEventTap,
            kCGHeadInsertEventTap,
            0,
            _event_mask(kCGEventLeftMouseDown, kCGEventRightMouseDown),
            self._event_callback,
            None,
        )
        
        if not tap:
            print("""
        [ERROR] Failed to create event tap.

        Required macOS Permissions:
        1. System Settings → Privacy & Security → Accessibility
            → Enable for Terminal (or your Python IDE)
        
        2. System Settings → Privacy & Security → Input Monitoring
            → Enable for Terminal (or your Python IDE)

        After enabling permissions, restart your terminal and try again.
        """)
            sys.exit(1)
        
        CGEventTapEnable(tap, True)
        src = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
        
        # Install stop timer
        stop_timer = _install_stop_timer()
        
        print("AX click-inspector running. Click anywhere to print element info. Ctrl+C to exit.\n")

        print(f"[INFO] Using inspector schema v1.0")
        
        # Run loop
        import CoreFoundation
        global RUN_LOOP
        RUN_LOOP = CoreFoundation.CFRunLoopGetCurrent()
        
        try:
            CoreFoundation.CFRunLoopRun()
            print("\n[STOP] RunLoop returned.")
        except KeyboardInterrupt:
            print("\n[STOP] KeyboardInterrupt.")
        finally:
            # Cleanup
            try:
                CGEventTapEnable(tap, False)
            except Exception:
                pass
            
            try:
                import CoreFoundation as CF
                if 'stop_timer' in locals() and stop_timer is not None:
                    CF.CFRunLoopTimerInvalidate(stop_timer)
            except Exception:
                pass
            
            # Save results
            self.engine.save_inspection_buffer(self.inspector_path)
            return

def main():
    """Entry point."""
    inspector = AXInspectorCLI()
    inspector.run()

if __name__ == "__main__":
    main()
    sys.exit(0)