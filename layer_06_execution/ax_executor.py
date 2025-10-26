"""
Part of the Artificial Mind open-source framework.
Implements Layer 06 (Execution) — deterministic macOS automation via Accessibility (AX).

AX Executor – Unified macOS Accessibility Engine (Research Preview)
===================================================================

A unified engine for both accessibility inspection and automated execution on macOS.
Implements an L0–L7 pipeline for robust, validation-first automation.

Core Components:
- AXEngine: Main class with inspect_step() and execute_step() methods
- Shared utilities for AX API interaction, screen handling, and element analysis
- Constants and tolerances unified across inspector/executor modes

Research Preview: Experimental automation layer intended for validation, safety testing, and reproducible macOS interaction.
"""

# ----------------  Core Imports ----------------
import os
import time
import json
import re
import objc
import unicodedata
from math import hypot
from typing import Any, Dict, Optional, Tuple
from collections import deque


# ---------------- CoreGraphics (mouse + screen) ----------------
from Quartz.CoreGraphics import (
    CGEventCreate, CGEventGetLocation,
    CGEventCreateMouseEvent, CGEventPost,
    kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGEventMouseMoved,
    kCGMouseButtonLeft, kCGHIDEventTap,
    CGMainDisplayID, CGDisplayBounds,
    CGGetActiveDisplayList, CGDisplayPixelsWide, CGDisplayPixelsHigh,
    CGDisplayRotation, CGDisplayScreenSize, kCGEventFlagMaskCommand, CGEventSetFlags    
)

# ---------------- Event tap (for inspection) ----------------
from Quartz import (
    CGEventTapCreate, CGEventTapEnable, CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource, CFRunLoopGetCurrent, kCFRunLoopCommonModes,
    kCGHeadInsertEventTap, kCGEventLeftMouseDown, kCGEventRightMouseDown,
)

# ---------------- Accessibility (direct first, fallback bind) ----------------
AX_DIRECT_OK = True
try:
    from ApplicationServices import (
        AXUIElementCreateSystemWide, AXUIElementCreateApplication,
        AXUIElementCopyElementAtPosition, AXUIElementCopyAttributeValue,
        AXUIElementGetPid, AXIsProcessTrusted,
        AXValueGetValue, AXValueGetType,
        kAXValueCGPointType, kAXValueCGRectType, kAXValueCGSizeType,
        AXUIElementPerformAction, 
    )
except Exception:
    AX_DIRECT_OK = False

if not AX_DIRECT_OK:
    framework = objc.loadBundle(
        "ApplicationServices",
        bundle_path="/System/Library/Frameworks/ApplicationServices.framework",
        module_globals=globals(),
    )
    objc.loadBundleFunctions(framework, globals(), [
        ("AXUIElementCreateSystemWide", b"^{__AXUIElement=}"),
        ("AXUIElementCreateApplication", b"^{__AXUIElement=}i"),
        ("AXUIElementCopyElementAtPosition", b"i^{__AXUIElement=}ddo^@"),
        ("AXUIElementCopyAttributeValue", b"i^{__AXUIElement=}@o^@"),
        ("AXUIElementGetPid", b"i^{__AXUIElement=}o^i"),
        ("AXUIElementPerformAction", b"i^{__AXUIElement=}@"), 
    ])
    try:
        objc.loadBundleFunctions(framework, globals(), [
            ("AXIsProcessTrusted", b"Z"),
            ("AXValueGetValue", b"Z^{__AXValue=}I^v"),
        ])
    except Exception:
        pass

try:
    from AppKit import NSRunningApplication, NSWorkspace, NSScreen
    from AppKit import NSApplicationActivateIgnoringOtherApps
except Exception:
    NSRunningApplication = None
    NSWorkspace = None
    NSScreen = None

# Optional ColorSync for display UUIDs
try:
    import ColorSync
except Exception:
    ColorSync = None

# ---------------- Constants ----------------
# These values were empirically tuned for reliability across different
# macOS versions and hardware configurations. Reducing them may cause
# race conditions; increasing them impacts automation speed.

SYSTEM = AXUIElementCreateSystemWide()
kAXErrorSuccess = 0
SCHEMA_VERSION = "1.0"

# Focus safeguard inset
FOCUS_INSET = 12

# Position tolerance for window matching (pixels)
POS_TOL_PX = 2.0

# Size tolerance for window matching (relative)
SIZE_TOL_REL = 0.02

# Hover delay
HOVER_DELAY = 0.06

# Click delay between down/up
CLICK_DELAY = 0.01

# App activation delay
APP_ACTIVATION_DELAY = 0.18

# Neighbor scan parameters
NEIGHBOR_RADIUS = 16
NEIGHBOR_STEP = 4
TIGHT_NEIGHBOR_RADIUS = 10
TIGHT_NEIGHBOR_STEP = 2

# Tree traversal limits
MAX_TREE_DEPTH = 5
MAX_TREE_NODES = 800
MAX_PARENT_DEPTH = 8
MAX_MICRO_REFINE_DEPTH = 6

# Safe container roles for relaxed matching
SAFE_CONTAINER_ROLES = {
    "AXWebArea", "AXGroup", "AXScrollArea", "AXWindow", 
    "AXApplication", "AXSplitGroup", "AXLayoutArea"
}

# AX attributes map
# WHY THIS EXISTS (and why we keep it explicit)
# --------------------------------------------------------------
# Apple’s Accessibility (AX) API is not stable across macOS versions or app implementations.
# AX attribute constants (like AXTitle, AXRole, AXChildren, etc.) are technically defined in
# ApplicationServices, but in practice:
#   1. Many apps expose non-standard attribute names.
#   2. Some attributes return localized variants depending on system language.
#   3. Dynamic introspection (AXCopyAttributeNames) is slow and inconsistent across processes.
#
# Keeping a hardcoded, version-controlled attribute map:
#   - Ensures deterministic behavior and cross-version stability.
#   - Avoids runtime crashes when Apple silently changes API identifiers.
#   - Makes debugging and inspection easier for developers unfamiliar with AX APIs.
#   - Enables clear, searchable references for each attribute in this file (important for open-source contributors).
#
# In short: this explicit map guarantees reproducible automation. Without it,
# the engine would behave differently on each macOS build, language pack, or app type.
# It’s defensive :)
import Quartz
ATTR = {
    "AXRole": getattr(Quartz, "kAXRoleAttribute", "AXRole"),
    "AXTitle": getattr(Quartz, "kAXTitleAttribute", "AXTitle"),
    "AXIdentifier": getattr(Quartz, "kAXIdentifierAttribute", "AXIdentifier"),
    "AXValue": getattr(Quartz, "kAXValueAttribute", "AXValue"),
    "AXDescription": getattr(Quartz, "kAXDescriptionAttribute", "AXDescription"),
    "AXHelp": getattr(Quartz, "kAXHelpAttribute", "AXHelp"),
    "AXPlaceholderValue": getattr(Quartz, "kAXPlaceholderValueAttribute", "AXPlaceholderValue"),
    "AXActionNames": getattr(Quartz, "kAXActionNamesAttribute", "AXActionNames"),
    "AXParent": getattr(Quartz, "kAXParentAttribute", "AXParent"),
    "AXChildren": getattr(Quartz, "kAXChildrenAttribute", "AXChildren"),
    "AXRoleDescription": getattr(Quartz, "kAXRoleDescriptionAttribute", "AXRoleDescription"),
    "AXSubrole": getattr(Quartz, "kAXSubroleAttribute", "AXSubrole"),
    "AXEnabled": getattr(Quartz, "kAXEnabledAttribute", "AXEnabled"),
    "AXFocused": getattr(Quartz, "kAXFocusedAttribute", "AXFocused"),
    "AXFrame": getattr(Quartz, "kAXFrameAttribute", "AXFrame"),
    "AXPosition": getattr(Quartz, "kAXPositionAttribute", "AXPosition"),
    "AXSize": getattr(Quartz, "kAXSizeAttribute", "AXSize"),
    "AXWindow": getattr(Quartz, "kAXWindowAttribute", "AXWindow"),
    "AXWindows": getattr(Quartz, "kAXWindowsAttribute", "AXWindows"),
    "AXSelectedText": getattr(Quartz, "kAXSelectedTextAttribute", "AXSelectedText"),
    "AXURL": getattr(Quartz, "kAXURLAttribute", "AXURL"),
    "AXActivationPoint": getattr(Quartz, "kAXActivationPointAttribute", "AXActivationPoint"),
    "AXActions": getattr(Quartz, "kAXActionsAttribute", "AXActions"),
    "AXLabel": getattr(Quartz, "kAXLabelAttribute", "AXLabel") if hasattr(Quartz, "kAXLabelAttribute") else "AXLabel",
    "AXLabelValue": getattr(Quartz, "kAXLabelValueAttribute", "AXLabelValue") if hasattr(Quartz, "kAXLabelValueAttribute") else "AXLabelValue",
    "AXTitleUIElement": getattr(Quartz, "kAXTitleUIElementAttribute", "AXTitleUIElement") if hasattr(Quartz, "kAXTitleUIElementAttribute") else "AXTitleUIElement",
}

# Role sets for classification
CONTAINER_ROLES = {
    "AXGroup", "AXToolbar", "AXScrollArea", "AXComboBox", "AXSplitGroup",
    "AXUnknown", "AXLayoutArea", "AXList", "AXTable", "AXWebArea", "AXWindow",
}

EDITABLE_TEXT_ROLES = {
    "AXTextField", "AXTextArea", "AXText", "AXTextBox", "AXSearchField", "AXEditableTextArea",
}

CLICKABLE_ROLES = {
    "AXButton", "AXTab", "AXRadioButton", "AXCheckBox", "AXLink", "AXPopUpButton", "AXMenuItem",
}

# Treat only these as interactive during adaptation/BFS
INTERACTIVE_ROLES = set().union(
    CLICKABLE_ROLES,         # AXButton, AXCheckBox, AXLink, AXMenuItem, ...
    EDITABLE_TEXT_ROLES,     # AXTextField, AXTextArea, ...
    {"AXCheckBox", "AXButton", "AXRadioButton", "AXPopUpButton", "AXTab", "AXLink"}
)
MIN_NODE_WH = 12.0  # skip microscopic nodes (w or h < 12) during adaptation/BFS
TINY_LINE_THICKNESS = 6.0  # px; treat 1–6 px lines as non-targets
MIN_LINE_LENGTH = 60.0     # px; long edge threshold for line-like nodes

# Preferred attributes for best label detection
PREF_LABEL_ATTRS = (
    "AXTitle", "AXValue", "AXDescription", "AXHelp", 
    "AXPlaceholderValue", "AXIdentifier", "AXLabel", "AXLabelValue",
)

SYSTEM_PROCESS_BLACKLIST = {
    "loginwindow", "WindowServer", "SystemUIServer",
    "ControlCenter", "NotificationCenter", "Spotlight", "launchd", "universalaccessd",
}

# ---------------- Frontmost app dectection (Standalone Implementation) ----------------
# This function provides enhanced frontmost app detection by returning PID,
# app name, and window title in a single call using NSWorkspace + AppleScript.
#
# STANDALONE: This implementation has zero external dependencies and works
# perfectly for the AX Executor's needs.
#
# OPTIONAL ENHANCEMENT: A more comprehensive system_info.py module is available
# as part of the Artificial Mind Beta framework. It provides additional features
# like AX element caching, OCR fallbacks, and Chrome profile management. However,
# this standalone version is fully functional for UI automation tasks.
#
# To request system_info.py: Contact me if you need macOS system-level
# introspection beyond what this executor provides.

def clean_text(text: str) -> str:
    """Minimal text normalization for app name matching (inlined from backend.cleaning)"""
    if not text:
        return ""
    text = text.strip().lower()
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')

def _get_frontmost_app_info():
    """
    Get frontmost application info with window title.
    Returns dict with {pid, name, window_title} or None on failure.
    
    This is a lightweight alternative to NSWorkspace + separate AppleScript calls.
    """
    try:
        import subprocess
        
        if NSWorkspace is None:
            return None
        
        # Get frontmost app from NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication()
        if not app:
            return None
        
        pid = int(app.processIdentifier())
        name = str(app.localizedName()) if app.localizedName() else None
        
        # Get window title via AppleScript (macOS native, no dependencies)
        window_title = None
        try:
            script = f'''
            tell application "System Events"
                set frontApp to first process whose unix id is {pid}
                set windowName to name of front window of frontApp
            end tell
            return windowName
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout:
                window_title = result.stdout.strip()
        except Exception:
            pass 
        
        return {
            "pid": pid,
            "name": name,
            "window_title": window_title
        }
    except Exception:
        return None

# ---------------- Label helpers ----------------

def _is_trivial_label(s):
    """Return True if label is empty or meaningless (e.g., '0.0')."""
    if s is None:
        return True
    try:
        s_str = str(s).strip()
    except Exception:
        return True
    return s_str == "" or s_str.lower() == "0.0"

def recorded_best_label(rec: dict):
    """Resolve best label for a recorded element, avoiding trivial '0.0'.
    Order: best_label/title -> parent_chain titles -> raw_labels -> None.
    """
    # 1) Direct fields
    rb = rec.get("best_label") or rec.get("title")
    if rb and not _is_trivial_label(rb):
        return str(rb).strip()

    # 2) Parent chain scan (nearest first)
    chain = rec.get("parent_chain") or []
    for item in chain:
        t = item.get("title") if isinstance(item, dict) else None
        if t and not _is_trivial_label(t):
            return str(t).strip()

    # 3) Raw labels fallback
    raw = rec.get("raw_labels") if isinstance(rec.get("raw_labels"), dict) else None
    if raw:
        for k in ("title", "value", "description", "help", "placeholder", "identifier"):
            v = raw.get(k)
            if v and not _is_trivial_label(v):
                return str(v).strip()

    return None

def _fmt_pt(p):
    """Format point for display."""
    return f"({p[0]:.1f}, {p[1]:.1f})"

def _fmt_rect(r):
    """Format rectangle for display."""
    return f"({r['x']:.1f}, {r['y']:.1f}, {r['w']:.1f}, {r['h']:.1f})"

def _status(ok):
    """Format status indicator."""
    return "✅ pass" if ok else "❌ fail"

def _dist(a, b):
    """Calculate distance between two points."""
    return hypot(a[0]-b[0], a[1]-b[1])

def _to_str(v):
    """Convert value to string unless None or empty."""
    if v is None:
        return None
    try:
        s = str(v)
        return s if s != "" else None
    except Exception:
        return None

def ensure_trust():
    """Check and warn about accessibility trust."""
    try:
        if 'AXIsProcessTrusted' in globals() and callable(AXIsProcessTrusted):
            if not AXIsProcessTrusted():
                print("⚠️ Enable Accessibility for Terminal/VSCode: System Settings → Privacy & Security → Accessibility")
    except Exception:
        pass

# ---------------- AX API Wrappers ----------------
def AXGet(el, attr):
    """Get AX attribute with error handling."""
    try:
        err, v = AXUIElementCopyAttributeValue(el, attr, None)
        return v if err == kAXErrorSuccess else None
    except Exception:
        try:
            res = AXUIElementCopyAttributeValue(el, attr)
            if isinstance(res, tuple) and len(res) == 2:
                err, v = res
                return v if err == kAXErrorSuccess else None
            return res
        except Exception:
            return None

def ax_get(el, attr):
    """Alternative AX getter with tuple handling."""
    if el is None:
        return None
    try:
        val = AXUIElementCopyAttributeValue(el, attr)
        if isinstance(val, tuple) and len(val) == 2:
            err, real = val
            return real if err == 0 else None
        return val
    except TypeError:
        try:
            err, val = AXUIElementCopyAttributeValue(el, attr, None)
            return val if err == 0 else None
        except Exception:
            return None
    except Exception:
        return None

def _parent(el):
    """Get parent element."""
    return AXGet(el, ATTR["AXParent"])

def _children(el):
    """Get children elements."""
    return AXGet(el, ATTR["AXChildren"]) or []

def ax_children(el):
    """Return children array for an element."""
    try:
        children = ax_get(el, "AXChildren")
        if isinstance(children, tuple) and len(children) == 2:
            err, arr = children
            return list(arr) if err == 0 and arr else []
        return list(children) if children else []
    except Exception:
        return []

# ---------------- Screen/Display Functions ----------------
def cg_main_bounds():
    """Get main display bounds."""
    try:
        b = CGDisplayBounds(CGMainDisplayID())
        return {"x": 0.0, "y": 0.0, "w": float(b.size.width), "h": float(b.size.height)}
    except Exception:
        return None

def _nsrect_to_dict(rect):
    """Convert NSRect to dict."""
    try:
        return {"x": float(rect.origin.x), "y": float(rect.origin.y), 
                "w": float(rect.size.width), "h": float(rect.size.height)}
    except Exception:
        try:
            (x, y), (w, h) = rect
            return {"x": float(x), "y": float(y), "w": float(w), "h": float(h)}
        except Exception:
            return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}

def _display_uuid_str(display_id):
    """Get display UUID string."""
    try:
        import CoreFoundation as CF
        if ColorSync is not None:
            uuid = ColorSync.CGDisplayCreateUUIDFromDisplayID(display_id)
        else:
            uuid = None
        if uuid:
            s = CF.CFUUIDCreateString(None, uuid)
            return str(s)
    except Exception:
        pass
    return None

def _approx_ppi(display_id):
    """Approximate display PPI."""
    try:
        px_w = float(CGDisplayPixelsWide(display_id))
        px_h = float(CGDisplayPixelsHigh(display_id))
        mm = CGDisplayScreenSize(display_id)
        mm_w = float(mm.width)
        mm_h = float(mm.height)
        if mm_w > 0 and mm_h > 0:
            import math
            inch_w = mm_w / 25.4
            inch_h = mm_h / 25.4
            ppi = math.sqrt(px_w**2 + px_h**2) / math.sqrt(inch_w**2 + inch_h**2)
            return float(ppi)
    except Exception:
        pass
    return None

def collect_screens_info():
    """Collect information about all screens."""
    screens = []
    if NSScreen is None:
        return screens
    
    try:
        for sc in NSScreen.screens() or []:
            try:
                dev = sc.deviceDescription()
                display_id = int(dev.get("NSScreenNumber")) if dev and dev.get("NSScreenNumber") is not None else None
            except Exception:
                display_id = None
            
            try:
                name = str(sc.localizedName()) if hasattr(sc, "localizedName") else None
            except Exception:
                name = None
            
            try:
                scale = float(sc.backingScaleFactor()) if hasattr(sc, "backingScaleFactor") else None
            except Exception:
                scale = None
            
            frame_pts = _nsrect_to_dict(sc.frame())
            vis_pts = _nsrect_to_dict(sc.visibleFrame())
            
            try:
                px_w = int(CGDisplayPixelsWide(display_id)) if display_id else None
                px_h = int(CGDisplayPixelsHigh(display_id)) if display_id else None
                rot = float(CGDisplayRotation(display_id)) if display_id else 0.0
                uuid = _display_uuid_str(display_id) if display_id else None
                ppi = _approx_ppi(display_id) if display_id else None
            except Exception:
                px_w = px_h = None
                rot = 0.0
                uuid = None
                ppi = None

            screens.append({
                "id": uuid or (str(display_id) if display_id is not None else None),
                "cg_id": display_id,
                "name": name,
                "bounds_points": frame_pts,
                "visible_points": vis_pts,
                "bounds_pixels": {"w": px_w, "h": px_h} if (px_w and px_h) else None,
                "scale": scale,
                "rotation": rot,
                "dpi": ppi,
            })
    except Exception:
        pass
    return screens

def pick_screen_for_rect(rect, screens):
    """Pick screen containing rect center."""
    try:
        cx = rect["x"] + rect["w"] / 2.0
        cy = rect["y"] + rect["h"] / 2.0
        for sc in screens:
            b = sc.get("bounds_points") or {}
            if (cx >= b.get("x", 0) and cx <= b.get("x", 0) + b.get("w", 0) and
                cy >= b.get("y", 0) and cy <= b.get("y", 0) + b.get("h", 0)):
                return sc
    except Exception:
        pass
    return screens[0] if screens else None

# ---------------- Point/Frame Parsing ----------------
# macOS Accessibility API returns geometry in multiple formats depending on:
# - macOS version
# - PyObjC version
# - Whether the app uses Carbon vs Cocoa vs SwiftUI
#
# These parsers handle all known formats:
# 1. AXValue objects (native CoreGraphics types)
# 2. Dictionary-like objects {"x": 10, "y": 20}
# 3. String representations "{{10, 20}, {100, 50}}" (legacy Carbon apps)
# 4. Tuple formats ((10, 20), (100, 50))

def _parse_rect_string(s):
    """Parse rectangle from string representation."""
    m = re.search(r"x:\s*(-?\d+(?:\.\d+)?)\s*y:\s*(-?\d+(?:\.\d+)?)\s*w:\s*(-?\d+(?:\.\d+)?)\s*h:\s*(-?\d+(?:\.\d+)?)", s)
    if m:
        x, y, w, h = map(float, m.groups())
        return {"x": x, "y": y, "w": w, "h": h}
    
    m2 = re.search(r"\{\{\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\},\s*\{\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\}\}", s)
    if m2:
        x, y, w, h = map(float, m2.groups())
        return {"x": x, "y": y, "w": w, "h": h}
    return None

def _parse_point_string(s):
    """Parse point from string representation."""
    m = re.search(r"x:\s*(-?\d+(?:\.\d+)?)\s*y:\s*(-?\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    
    m2 = re.search(r"\{\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\}", s)
    if m2:
        return float(m2.group(1)), float(m2.group(2))
    
    toks = [t for t in re.findall(r"[-+]?\d*\.?\d+|0x[0-9a-fA-F]+", s) if not t.startswith("0x")]
    nums = [float(t) for t in toks if re.match(r"[-+]?\d*\.?\d+", t)]
    return (nums[0], nums[1]) if len(nums) >= 2 else None


def decode_point(val):
    """Decode AX point value."""
    if val is None:
        return None
    try:
        out = AXValueGetValue(val, kAXValueCGPointType, None)
        if isinstance(out, tuple):
            if len(out) >= 2 and isinstance(out[1], tuple) and len(out[1]) == 2 and out[0] is True:
                return float(out[1][0]), float(out[1][1])
            if len(out) == 1 and isinstance(out[0], tuple) and len(out[0]) == 2:
                return float(out[0][0]), float(out[0][1])
    except Exception:
        pass
    
    if isinstance(val, dict):
        try:
            return float(val.get("x", val.get("X"))), float(val.get("y", val.get("Y")))
        except Exception:
            return None
    return _parse_point_string(str(val))

def _decode_point_val(v):
    """Decode AXValue CGPoint or dict-like into {x,y}."""
    if v is None:
        return None
    try:
        out = AXValueGetValue(v, kAXValueCGPointType, None)
        pt = out[1] if isinstance(out, tuple) else out
        if pt:
            x, y = pt
            return {"x": float(x), "y": float(y)}
    except Exception:
        pass
    
    try:
        if isinstance(v, dict):
            return {"x": float(v.get("X", v.get("x"))), "y": float(v.get("Y", v.get("y")))}
    except Exception:
        pass
    return None

def _decode_size_val(v):
    """Decode AXValue CGSize or dict-like into {w,h}."""
    if v is None:
        return None
    try:
        out = AXValueGetValue(v, kAXValueCGSizeType, None)
        sz = out[1] if isinstance(out, tuple) else out
        if sz:
            w, h = sz
            return {"w": float(w), "h": float(h)}
    except Exception:
        pass
    
    try:
        if isinstance(v, dict):
            return {"w": float(v.get("Width", v.get("w"))), "h": float(v.get("Height", v.get("h")))}
    except Exception:
        pass
    return None

def decode_frame(el, element_only=False, max_up=MAX_PARENT_DEPTH):
    """Decode frame from element or ancestors."""
    e = el
    depth = 0
    limit = 0 if element_only else max_up
    
    while e is not None and depth <= limit:
        v = AXGet(e, ATTR["AXFrame"])
        if v is not None:
            if isinstance(v, dict):
                try:
                    x = float(v.get("x", v.get("X")))
                    y = float(v.get("y", v.get("Y")))
                    w = float(v.get("w", v.get("Width")))
                    h = float(v.get("h", v.get("Height")))
                    return {"x": x, "y": y, "w": w, "h": h}, f"AXFrame depth={depth}"
                except Exception:
                    pass
            
            r = _parse_rect_string(str(v))
            if r:
                return r, f"AXFrame depth={depth}"
        
        pos = AXGet(e, ATTR["AXPosition"])
        size = AXGet(e, ATTR["AXSize"])
        if pos and size:
            try:
                px, py = _parse_point_string(str(pos)) or (None, None)
                sw, sh = _parse_point_string(str(size)) or (None, None)
                if None not in (px, py, sw, sh):
                    return {"x": px, "y": py, "w": sw, "h": sh}, f"AXPosition+Size depth={depth}"
            except Exception:
                pass
        
        e = _parent(e)
        depth += 1
    return None, "no_frame"

def ax_frame(el):
    """Return element's frame (x, y, w, h) if available."""
    v = ax_get(el, "AXFrame")
    if v is None:
        return None
    try:
        out = AXValueGetValue(v, kAXValueCGRectType, None)
        rect = out[1] if isinstance(out, tuple) else out
        if not rect:
            return None
        (x, y), (w, h) = rect
        return {"x": float(x), "y": float(y), "w": float(w), "h": float(h)}
    except Exception:
        return None

def ax_position(el):
    """Get element position."""
    v = ax_get(el, "AXPosition")
    return _decode_point_val(v)

def ax_size(el):
    """Get element size (w,h) if available."""
    try:
        v = ax_get(el, "AXSize")
        return _decode_size_val(v)
    except Exception:
        return None

def ax_frame_or_compose(el):
    """Return AXFrame if available; else compose from AXPosition+AXSize."""
    f = ax_frame(el)
    if f:
        return f
    pos = ax_position(el)
    sz = ax_size(el)
    if pos and sz:
        return {"x": pos["x"], "y": pos["y"], "w": sz["w"], "h": sz["h"]}
    return None

def get_activation_point(el):
    """Get activation point for element."""
    return decode_point(AXGet(el, ATTR["AXActivationPoint"]))

def ax_activation_point(el):
    """Return Activation Point {x,y} if element exposes it."""
    v = ax_get(el, "AXActivationPoint")
    return _decode_point_val(v)

def center_of(frame):
    """Calculate center point of frame."""
    return (frame["x"] + frame["w"]/2.0, frame["y"] + frame["h"]/2.0)

# ---------------- UI Element Analysis ----------------
def best_label_from_info(info):
    """Extract best label from element info.
    Order:
      1. AXTitle
      2. AXDescription
      3. AXValue
      4. AXHelp
      5. AXRole of child
      6. AXSubrole
      7. AXGroup of parent
      7.5. parent_chain titles (NEW)
      8. window_title (last resort)
    """
    if info.get("AXTitle"):
        return str(info.get("AXTitle")).strip().lower()
    
    if info.get("AXDescription"):
        return str(info.get("AXDescription")).strip().lower()
    
    if info.get("AXValue"):
        return str(info.get("AXValue")).strip().lower()
    
    if info.get("AXHelp"):
        return str(info.get("AXHelp")).strip().lower()
    children = info.get("AXChildren") or []
    
    if children and isinstance(children, list):
        for ch in children:
            if isinstance(ch, dict) and ch.get("AXRole"):
                return str(ch.get("AXRole")).strip().lower()
            
    if info.get("AXSubrole"):
        return str(info.get("AXSubrole")).strip().lower()
    
    parent = info.get("AXParent")
    if parent and isinstance(parent, dict) and parent.get("AXRole") and parent.get("AXRole").lower() == "axgroup":
        return "axgroup"
    
    parent_chain = info.get("parent_chain", [])
    for parent in parent_chain:
        if isinstance(parent, dict):
            parent_title = parent.get("title")
            if parent_title and str(parent_title).strip() not in ["", "0.0", "null"]:
                return str(parent_title).strip().lower()
             
    if info.get("window_title"):
        return str(info.get("window_title")).strip().lower()
    return None

def ax_best_label(el):
    """Return best human label for element."""
    for attr in PREF_LABEL_ATTRS:
        v = ax_get(el, attr)
        if v not in (None, ""):
            try:
                return str(v)
            except Exception:
                pass

    t_el = ax_get(el, "AXTitleUIElement")
    if t_el:
        cand = (ax_get(t_el, "AXTitle") or
                ax_get(t_el, "AXValue") or
                ax_get(t_el, "AXDescription"))
        if cand not in (None, ""):
            try:
                return str(cand)
            except Exception:
                pass

    role = _to_str(ax_get(el, "AXRole"))
    if role in CONTAINER_ROLES:
        for ch in ax_children(el):
            ch_role = _to_str(ax_get(ch, "AXRole"))
            if ch_role in EDITABLE_TEXT_ROLES or is_clickable(ch):
                lbl = ax_best_label(ch)
                if lbl:
                    return lbl

    return None

def ax_actions(el):
    """Return supported action names for element."""
    try:
        names = ax_get(el, "AXActions") or []
        if not names:
            names = ax_get(el, "AXActionNames") or []
        return [str(x) for x in names]
    except Exception:
        return []

# --- AXPress execution helper ---
def ax_perform_press(el):
    """Attempt AXPress on an element. Returns True on success."""
    try:
        names = ax_actions(el)
        if "AXPress" in names:
            try:
                err = AXUIElementPerformAction(el, "AXPress")
                # Some bindings return (err, None)
                if isinstance(err, tuple):
                    return err[0] == 0
                return err == 0
            except Exception:
                return False
    except Exception:
        pass
    return False

def _norm_menu_title(s: Optional[str]) -> Optional[str]:
    """
    Normalize menu titles for comparison.
    
    Handles macOS-specific menu quirks:
    - Replaces ellipsis character (…) with three dots (...)
    - Collapses whitespace (menus can have inconsistent spacing)
    - Case-insensitive matching
    
    Used by menu automation system (_ax_press_menu_item) to match
    recorded menu titles against live menu items.
    
    Args:
        s: Menu title string
        
    Returns:
        Normalized title or None
    """
    if s is None:
        return None
    try:
        s2 = str(s).replace("…", "...")
        s2 = re.sub(r"\s+", " ", s2).strip()
        return s2.casefold()
    except Exception:
        try:
            return str(s).strip().lower()
        except Exception:
            return None


def _safe_point_from_ap_or_frame(el):
    """Pick a sane click point: validated ActivationPoint, else frame center."""
    fr = ax_frame_or_compose(el)
    ap = ax_activation_point(el)

    # Validate AP against element frame
    if ap and fr:
        try:
            x, y = float(ap["x"]), float(ap["y"])
            cx, cy = fr["x"] + fr["w"]/2.0, fr["y"] + fr["h"]/2.0
            if abs(x - cx) <= fr["w"] * 2 and abs(y - cy) <= fr["h"] * 2:
                return (x, y)
        except Exception:
            pass

    # Fallback: frame center
    if fr:
        return center_of(fr)
    return None


def _ax_press_menu_item(app_el, title: str, debug: bool = False) -> bool:
    """
    Traverse the application's AXMenuBar and submenus to find a menu node whose
    title matches `title` and press it. Supports both AXMenuBarItem (e.g. "File")
    and AXMenuItem (e.g. "Close Window"). If not found in the menubar tree,
    falls back to scanning the focused window for window-local menu controls
    like AXMenuButton / AXPopUpButton.
    """
    if not app_el or not title:
        return False

    want = _norm_menu_title(title)
    if want is None:
        return False

    # ---- Phase 1: Menubar traversal (global menus) ----
    try:
        menubar = AXGet(app_el, "AXMenuBar")
    except Exception:
        menubar = None

    if menubar is not None:
        q = deque([menubar])
        visited = 0
        try:
            while q and visited < 10000:
                node = q.popleft()
                visited += 1

                role = _to_str(ax_get(node, "AXRole"))

                if role in {"AXMenuBar", "AXMenu"}:
                    for ch in ax_children(node):
                        q.append(ch)
                    continue

                # Match top-level MenuBarItem and submenu MenuItem
                if role in {"AXMenuBarItem", "AXMenuItem"}:
                    raw_title = (ax_get(node, "AXTitle") or ax_best_label(node) or "")
                    cand = _norm_menu_title(raw_title)
                    if cand == want:
                        # Prefer AXPress
                        if ax_perform_press(node):
                            if debug:
                                print(f"[MENU] AXPress (menubar): '{title}'")
                            time.sleep(0.12)  # allow the menu/submenu to render
                            return True
                        # Fallback: click a safe point
                        pt = _safe_point_from_ap_or_frame(node)
                        if pt:
                            try:
                                hover(pt, debug=False)
                            except Exception:
                                pass
                            try:
                                click(pt, button="left")
                                if debug:
                                    print(f"[MENU] Click fallback (menubar): '{title}' at {pt}")
                                time.sleep(0.12)  # allow the menu/submenu to render
                                return True
                            except Exception as e:
                                if debug:
                                    print(f"[MENU] Click fallback (menubar) failed: {e}")
                                return False

                    # Not our target; still enqueue children
                    for ch in ax_children(node):
                        q.append(ch)
                    continue

                # Any other role: keep exploring
                for ch in ax_children(node):
                    q.append(ch)
        except Exception as e:
            if debug:
                print(f"[MENU] Menubar traversal error: {e}")
            # Continue to window-local fallback

    # ---- Phase 2: Focused-window traversal (window-local menus) ----
    focused_win = None
    try:
        focused_win = AXGet(app_el, "AXFocusedWindow")
        if focused_win is None:
            wins = AXGet(app_el, "AXWindows") or []
            focused_win = wins[0] if wins else None
    except Exception:
        focused_win = None

    if focused_win is None:
        if debug:
            print("[MENU] No focused window; cannot search window-local menus.")
        return False

    roles_window_controls = {"AXMenuButton", "AXPopUpButton", "AXMenuItem"}
    q = deque([focused_win])
    visited = 0
    try:
        while q and visited < 5000:
            node = q.popleft()
            visited += 1

            role = _to_str(ax_get(node, "AXRole"))

            if role in roles_window_controls:
                raw_title = (ax_get(node, "AXTitle") or ax_best_label(node) or "")
                cand = _norm_menu_title(raw_title)
                if cand == want:
                    if ax_perform_press(node):
                        if debug:
                            print(f"[MENU] AXPress (window control): '{title}'")
                        return True
                    pt = _safe_point_from_ap_or_frame(node)
                    if pt:
                        try:
                            hover(pt, debug=False)
                        except Exception:
                            pass
                        try:
                            click(pt, button="left")
                            if debug:
                                print(f"[MENU] Click (window control): '{title}' at {pt}")
                            return True
                        except Exception as e:
                            if debug:
                                print(f"[MENU] Click (window control) failed: {e}")
                            return False

            # Continue BFS
            for ch in ax_children(node):
                q.append(ch)
    except Exception as e:
        if debug:
            print(f"[MENU] Window traversal error: {e}")
        return False

    if debug:
        print(f"[MENU] Not found: '{title}' (norm='{want}')")
    return False

def _execute_menu_click(recorded_step: Dict[str, Any], debug: bool = False) -> bool:
    """
    Resolve the correct application element and press the requested menu item by title.
    Uses frontmost app if PID is unavailable.
    """
    title = (
        recorded_step.get("ax_title")
        or recorded_step.get("title")
        or recorded_step.get("expected_text")
        or recorded_step.get("best_label")
        or recorded_step.get("target")
        or ""
    )
    title = title.strip() if isinstance(title, str) else ""
    if not title:
        if debug:
            print("[MENU] No title provided on recorded_step for menu click.")
        return False

    # Prefer recorded PID; fallback to frontmost app
    pid = None
    try:
        pid = int(recorded_step.get("pid")) if recorded_step.get("pid") is not None else None
    except Exception:
        pid = None

    app_el = None
    if pid:
        try:
            app_el = AXUIElementCreateApplication(pid)
        except Exception:
            app_el = None

    if app_el is None:
        if NSWorkspace is None:
            if debug:
                print("[MENU] NSWorkspace unavailable; cannot resolve frontmost application.")
            return False
        try:
            ws = NSWorkspace.sharedWorkspace()
            fa = ws.frontmostApplication()
            if fa is not None:
                pid = int(fa.processIdentifier())
                app_el = AXUIElementCreateApplication(pid)
        except Exception:
            app_el = None

    if app_el is None:
        if debug:
            print("[MENU] Could not resolve application element for menu click.")
        return False

    return _ax_press_menu_item(app_el, title, debug=debug)

def is_clickable(el):
    """Return True if element appears interactive."""
    role = ax_get(el, "AXRole")
    acts = set(ax_actions(el))
    return (role in CLICKABLE_ROLES) or ("AXPress" in acts) or ("AXPick" in acts)

def has_axpress(info):
    """Check if element has AXPress action."""
    acts = info.get("AXActionNames") or []
    return any(isinstance(a, str) and a.lower() == "axpress" for a in acts)

def element_info(el):
    """Extract comprehensive element information."""
    info = {k: AXGet(el, v) for k, v in ATTR.items() if k in (
        "AXRole", "AXRoleDescription", "AXSubrole", "AXTitle", "AXIdentifier", "AXValue", "AXDescription",
        "AXHelp", "AXPlaceholderValue", "AXActionNames"
    )}
    info["best_label"] = best_label_from_info(info)

    role = info.get("AXRole")
    best = info.get("best_label")
    e = el
    depth = 0

    while (role is None or best is None) and e is not None and depth < MAX_MICRO_REFINE_DEPTH:
        if role is None:
            r = AXGet(e, ATTR["AXRole"])
            if r:
                role = r
        if best is None:
            tmp = {k: AXGet(e, ATTR[k]) for k in (
                "AXTitle", "AXValue", "AXDescription", "AXHelp",
                "AXPlaceholderValue", "AXIdentifier"
            )}
            b = best_label_from_info(tmp)
            best = best or b
        e = _parent(e)
        depth += 1

    if info.get("AXRole") is None and role is not None:
        info["AXRole"] = role
    if info.get("best_label") is None and best is not None:
        info["best_label"] = best

    # Compute/refresh 'automation_type' now that role/role_description may be available.
    role_desc = info.get("AXRoleDescription")
    role_raw = info.get("AXRole")
    try:
        if role_desc:
            friendly_role = str(role_desc)
        elif isinstance(role_raw, str):
            friendly_role = role_raw[2:] if role_raw.startswith("AX") else role_raw
        elif role_raw is not None:
            friendly_role = str(role_raw)
        else:
            friendly_role = None
    except Exception:
        friendly_role = role_desc or role_raw
    info["automation_type"] = friendly_role

    return info

def compare_signature(rec, live, trusted_context=False):
    """Compare recorded vs live element signatures with strict matching (generalized)."""
    def _norm(s):
        if s is None:
            return None
        try:
            return unicodedata.normalize("NFKC", str(s)).strip().casefold()
        except Exception:
            try:
                return str(s).strip().lower()
            except Exception:
                return None

    mism = {}

    # STRICT role matching
    rec_role = rec.get("role")
    live_role = live.get("AXRole")
    if rec_role and live_role and rec_role != live_role:
        mism["role"] = {"recorded": rec_role, "live": live_role}

    # CONTEXTUAL label matching
    rb = recorded_best_label(rec)
    lb = live.get("best_label")
    if rb and lb:
        if trusted_context:
            # Relaxed: allow if any significant words match
            rb_norm = _norm(rb)
            lb_norm = _norm(lb)
            if rb_norm and lb_norm:
                rb_words = set(w for w in rb_norm.split() if len(w) > 2)
                lb_words = set(w for w in lb_norm.split() if len(w) > 2)
                if not (rb_words & lb_words):  # No word overlap
                    mism["best_label"] = {"recorded": rb, "live": lb}
            elif rb_norm != lb_norm:  # One is None or they differ
                mism["best_label"] = {"recorded": rb, "live": lb}

    # For label-centric roles, require role + one of title/label to match
    strict_roles = {"AXCheckBox", "AXButton", "AXRadioButton", "AXTab", "AXLink", "AXMenuItem", "AXPopUpButton"}

    rec_title = rec.get("title")
    live_title = live.get("AXTitle")
    if rec_role in strict_roles and rec_title and not _is_trivial_label(rec_title):
        n_rec_title = _norm(rec_title)
        n_live_title = _norm(live_title)
        n_live_label = _norm(lb)
        if n_rec_title is not None:
            if not (n_rec_title == n_live_title or n_rec_title == n_live_label):
                mism["title_match"] = {"expected": rec_title, "got": live_title or lb}

    # Optional soft subrole check (only if both present)
    rec_sub = rec.get("subrole")
    live_sub = live.get("AXSubrole")
    if rec_sub and live_sub and rec_sub != live_sub:
        mism["subrole"] = {"recorded": rec_sub, "live": live_sub}

    return mism

# --- Strict normalization and identity helpers ---
def _norm_text(s):
    """
    Normalize text for strict element comparison.
    
    Uses NFKC normalization to handle unicode variants (e.g., "café" vs "café"),
    then applies casefold for case-insensitive matching. This is stricter than
    clean_text() which is used for app name matching.
    
    Args:
        s: Text to normalize (can be None)
        
    Returns:
        Normalized string or None if input was None/invalid
    """
    if s is None:
        return None
    try:
        return unicodedata.normalize("NFKC", str(s)).strip().casefold()
    except Exception:
        try:
            return str(s).strip().lower()
        except Exception:
            return None

def strict_identity_ok(recorded_step: dict, live_info: dict) -> bool:
    """Strict identity: role equal AND (title OR best_label) normalized equal."""
    rec_role = recorded_step.get("role")
    live_role = live_info.get("AXRole")
    if rec_role and live_role and rec_role != live_role:
        return False
    # Compare title or best_label
    rec_title = recorded_step.get("title")
    rec_label = recorded_best_label(recorded_step)
    live_title = live_info.get("AXTitle")
    live_label = live_info.get("best_label")
    rec_key = _norm_text(rec_title) or _norm_text(rec_label)
    live_key = _norm_text(live_title) or _norm_text(live_label)
    return (rec_key is not None) and (live_key is not None) and (rec_key == live_key)

def pick_best_descendant(el, max_depth=3):
    """Find more specific descendant if element is container."""
    role = _to_str(ax_get(el, "AXRole"))
    label = ax_best_label(el)
    if (label and label.strip()) or (role and role not in CONTAINER_ROLES):
        return el

    try:
        q = deque()
        q.append((el, 0))
        best = el
        while q:
            node, d = q.popleft()
            if d > max_depth:
                break
            node_role = _to_str(ax_get(node, "AXRole"))
            node_label = ax_best_label(node)
            if node_role in EDITABLE_TEXT_ROLES or is_clickable(node):
                if node_label:
                    return node
                best = node
            for c in ax_children(node):
                q.append((c, d + 1))
        return best
    except Exception:
        return el

def parent_chain(el, limit=MAX_PARENT_DEPTH):
    """Return chain of parents for context."""
    out = []
    cur = el
    for _ in range(limit):
        if not cur:
            break
        out.append({
            "role": _to_str(ax_get(cur, "AXRole")),
            "title": ax_best_label(cur),
        })
        cur = (ax_get(cur, "AXParent") or 
               ax_get(cur, "AXTopLevelUIElement") or 
               ax_get(cur, "AXWindow"))
    return out

def ax_ancestor(el, roles=("AXWindow", "AXApplication")):
    """Walk up to window/application ancestor."""
    cur = el
    for _ in range(30):
        if cur is None:
            return None
        role = ax_get(cur, "AXRole")
        if role in roles:
            return cur
        parent = (ax_get(cur, "AXParent") or
                  ax_get(cur, "AXTopLevelUIElement") or
                  ax_get(cur, "AXWindow"))
        cur = parent
    return None

def nearest_window(el):
    """Find nearest window ancestor."""
    e = el
    d = 0
    while e is not None and d < 12:
        role = AXGet(e, ATTR["AXRole"])
        if (isinstance(role, str) and role == "AXWindow") or role == getattr(Quartz, "kAXWindowRole", "AXWindow"):
            return e
        e = _parent(e)
        d += 1
    return None

# ---------------- App/Window Resolution ----------------
def pid_and_app(el):
    """Return PID and application name from element."""
    target = ax_ancestor(el) or el
    pid = None
    try:
        maybe = AXUIElementGetPid(target)
        if isinstance(maybe, tuple):
            pid = int(maybe[1]) if len(maybe) == 2 else None
        else:
            pid = int(maybe)
    except Exception:
        app_node = ax_ancestor(el, roles=("AXApplication",))
        try:
            maybe = AXUIElementGetPid(app_node) if app_node else None
            if isinstance(maybe, tuple):
                pid = int(maybe[1]) if len(maybe) == 2 else None
            elif maybe is not None:
                pid = int(maybe)
        except Exception:
            pid = None
    
    name = app_name_for_pid(pid) if pid else None
    return pid, name

def app_name_for_pid(pid):
    """Return app's localized name for given PID."""
    if NSRunningApplication is None:
        return None
    try:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        return str(app.localizedName()) if app else None
    except Exception:
        return None

def get_windows(app_el):
    """Get windows for application element."""
    return AXGet(app_el, ATTR["AXWindows"]) or []

def resolve_app_name_smart(recorded_app, live_app_name, live_title=None):
    """Multi-strategy app name resolution for complex titles"""
    import re
    
    if not recorded_app or not live_app_name:
        return False
    
    recorded_clean = clean_text(recorded_app)
    live_clean = clean_text(live_app_name)
    
    # Strategy 1: Exact match after normalization
    if recorded_clean == live_clean:
        return True
    
    # Strategy 2: Extract app from "content - app" pattern
    if live_title and " - " in live_title:
        segments = live_title.split(" - ")
        app_candidate = segments[-1].strip()
        app_candidate_clean = clean_text(app_candidate)
        if recorded_clean in app_candidate_clean or app_candidate_clean in recorded_clean:
            return True
    
    # Strategy 3: Strip dynamic content
    if live_title:
        cleaned = re.sub(r'\(\d+\)', '', live_title)
        cleaned = re.sub(r'\S+@\S+', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        if " - " in cleaned:
            segments = cleaned.split(" - ")
            app_candidate = clean_text(segments[-1].strip())
            if recorded_clean in app_candidate:
                return True
    
    # Strategy 4: Known app patterns (edit as needed for your use case)
    APP_ALIASES = {
        "chrome": ["google chrome", "chrome"],
        "gmail": ["google chrome", "chrome"],
        "finder": ["finder", "recents", "documents", "downloads"],
        "safari": ["safari"],
        "firefox": ["firefox", "mozilla firefox"]
    }
    
    for key, aliases in APP_ALIASES.items():
        if recorded_clean in aliases and live_clean in aliases:
            return True
        if recorded_clean == key and live_clean in aliases:
            return True
        if live_clean == key and recorded_clean in aliases:
            return True
    
    return False

def find_browser():
    """Specifically identify browser processes by bundle ID"""
    import Cocoa
    
    BROWSER_BUNDLE_IDS = {
        "com.google.Chrome": "Google Chrome",
        "com.apple.Safari": "Safari", 
        "org.mozilla.firefox": "Firefox",
        "com.microsoft.edgemac": "Microsoft Edge",
        "com.operasoftware.Opera": "Opera",
        "com.brave.Browser": "Brave Browser"
    }
    
    workspace = Cocoa.NSWorkspace.sharedWorkspace()
    browsers_found = []
    
    for app in workspace.runningApplications():
        try:
            bundle_id = str(app.bundleIdentifier()) if app.bundleIdentifier() else ""
            
            if bundle_id in BROWSER_BUNDLE_IDS:
                app_name = str(app.localizedName()) if app.localizedName() else BROWSER_BUNDLE_IDS[bundle_id]
                browsers_found.append((app.processIdentifier(), app_name, bundle_id))
                
        except Exception:
            continue
    
    return browsers_found

def resolve_app_window_by_recording(rec_app, rec_title, debug=False):
    """L0: Cold lookup by app name OR window title, with frontmost validation.

    Strategy:
      1) Normalize recorded Chrome-like strings (window-title-looking values).
      2) Try authoritative frontmost app (system_info if available, else NSWorkspace).
         If it semantically matches the recorded app/title, accept immediately.
      3) Browser-specific PID resolution (bundle IDs) as secondary path.
      4) Fallback: scan apps and their windows by title/semantic match.
    """
    if NSWorkspace is None:
        return None, None, None

    # --- 0) Normalize recorded inputs ---
    def _clean_rec_app_title(a, t):
        a2 = (a or "").strip()
        t2 = (t or "").strip()
        # Common Browser-style patterns: "Something - Google Chrome - Profile, using chrome as example"
        if a2 and (" - Google Chrome" in a2 or a2.casefold() in {"gmail", "chrome", "google chrome"}):
            a2 = "Google Chrome"
        if t2 and " - Google Chrome" in t2:
            pass
        return a2 or None, t2 or None

    rec_app, rec_title = _clean_rec_app_title(rec_app, rec_title)

    pid = None
    app_el = None
    win_el = None
    app_name = None

    ws = NSWorkspace.sharedWorkspace()

    # --- 1) Authoritative frontmost check (system_info → NSWorkspace) ---
    front_pid = None
    front_name = None
    front_title = None

    # Try enhanced detection (returns all 3 values in one call)
    front_info = _get_frontmost_app_info()
    if front_info:
        front_pid = front_info.get("pid")
        front_name = front_info.get("name")
        front_title = front_info.get("window_title")
    else:
        # Fallback to basic NSWorkspace
        front_pid = None
        front_name = None
        front_title = None
        try:
            if NSWorkspace:
                ws = NSWorkspace.sharedWorkspace()
                fa = ws.frontmostApplication()
                if fa:
                    front_pid = int(fa.processIdentifier())
                    front_name = app_name_for_pid(front_pid)
        except Exception:
            pass

    # Fallback to NSWorkspace for frontmost
    try:
        if front_pid is None:
            fa = ws.frontmostApplication()
            if fa is not None:
                front_pid = int(fa.processIdentifier())
                front_name = app_name_for_pid(front_pid)
    except Exception:
        pass

    # Derive a plausible frontmost window title (best-effort)
    if front_pid and front_title is None:
        try:
            _ap = AXUIElementCreateApplication(front_pid)
            _wins = get_windows(_ap) or []
            # Prefer main/focused window
            main_win = None
            for w in _wins:
                try:
                    if AXGet(w, "AXMain") is True or AXGet(w, ATTR.get("AXFocused", "AXFocused")) is True:
                        main_win = w
                        break
                except Exception:
                    continue
            if main_win is None and _wins:
                main_win = _wins[0]
            if main_win is not None:
                front_title = AXGet(main_win, ATTR["AXTitle"]) or None
        except Exception:
            front_title = None

    # If frontmost semantically matches recorded app/title, accept it (with Chrome safeguard)
    if front_pid and front_name:
        try:
            sem_ok = resolve_app_name_smart(rec_app or front_name, front_name, front_title)

            # Chrome safeguard: if process is Chrome but title didn't match, still accept
            if not sem_ok:
                if rec_app and rec_app.lower() in {"chrome", "google chrome", "gmail"}:
                    if front_name and "chrome" in front_name.lower():
                        sem_ok = True

            if sem_ok:
                pid = front_pid
                app_name = front_name
                app_el = AXUIElementCreateApplication(pid)
                # Try to pick the intended window
                wins = get_windows(app_el) or []
                chosen = None
                if rec_title:
                    for w in wins:
                        t = AXGet(w, ATTR["AXTitle"])  # exact match only here
                        if t and t == rec_title:
                            chosen = w
                            break
                if chosen is None:
                    # prefer main/focused
                    for w in wins:
                        try:
                            if AXGet(w, "AXMain") is True or AXGet(w, ATTR.get("AXFocused", "AXFocused")) is True:
                                chosen = w
                                break
                        except Exception:
                            continue
                    if chosen is None and wins:
                        chosen = wins[0]
                win_el = chosen
                if debug:
                    print(f"📦 L0: app={app_name} pid={pid} | window_title={(AXGet(win_el, ATTR['AXTitle']) if win_el else None)}")
                return pid, app_el, win_el
        except Exception:
            pass

    # --- 2) Browser-specific PID resolution by bundle IDs ---
    BROWSER_APPS = {"chrome", "google chrome", "gmail", "safari", "firefox", "edge", "opera", "brave"}
    if rec_app and rec_app.casefold() in BROWSER_APPS:
        browsers = find_browser()
        for browser_pid, browser_name, bundle_id in browsers:
            if (rec_app.casefold() in {"chrome", "google chrome", "gmail"} and bundle_id == "com.google.Chrome") or (
                rec_app.casefold() in browser_name.casefold()
            ):
                pid = browser_pid
                app_name = browser_name
                if debug:
                    print(f"Browser-specific resolution: {browser_name} PID {pid}")
                break

    # --- 3) Fallback: scan running apps, compare names semantically ---
    if pid is None and rec_app:
        for ra in ws.runningApplications():
            try:
                nm = str(ra.localizedName()) if ra.localizedName() else None
            except Exception:
                nm = None
            if nm and nm in SYSTEM_PROCESS_BLACKLIST:
                continue
            if nm and resolve_app_name_smart(rec_app, nm, rec_title):
                pid = ra.processIdentifier()
                app_name = nm
                break

    # --- 4) Title-driven window scan across apps ---
    if pid is None and rec_title:
        for ra in ws.runningApplications():
            try:
                app_name_candidate = str(ra.localizedName()) if ra.localizedName() else None
            except Exception:
                app_name_candidate = None
            ap = AXUIElementCreateApplication(ra.processIdentifier())
            for w in get_windows(ap):
                t = AXGet(w, ATTR["AXTitle"])
                if t and (t == rec_title or resolve_app_name_smart(rec_app or "unknown", app_name_candidate, t)):
                    pid = ra.processIdentifier()
                    app_name = app_name_candidate
                    app_el = ap
                    win_el = w
                    break
            if pid is not None:
                break

    # --- 5) Finalize handles ---
    if pid is not None and app_el is None:
        app_el = AXUIElementCreateApplication(pid)
    if app_el is not None and win_el is None:
        wins = get_windows(app_el)
        main_win = None
        try:
            for w in wins or []:
                is_main = AXGet(w, "AXMain")
                is_focused = AXGet(w, ATTR.get("AXFocused", "AXFocused"))
                if (is_main is True) or (is_focused is True):
                    main_win = w
                    break
        except Exception:
            main_win = None
        if rec_title:
            for w in wins or []:
                t = AXGet(w, ATTR["AXTitle"])
                if t and t == rec_title:
                    win_el = w
                    break
        if win_el is None:
            win_el = main_win if main_win is not None else (wins[0] if wins else None)

    if debug:
        print(f"📦 L0: app={app_name or rec_app} pid={pid} | window_title={(AXGet(win_el, ATTR['AXTitle']) if win_el else None)}")

    return pid, app_el, win_el

# ---------------- Hit Testing ----------------
def hit(pt):
    """Hit test at point to get element and info."""
    x, y = pt
    err, el = AXUIElementCopyElementAtPosition(SYSTEM, x, y, None)
    if err != kAXErrorSuccess or el is None:
        return None, {"error": f"hit failed err={err}"}
    return el, element_info(el)

def inspect_at_point(x, y):
    """Comprehensive inspection at point (for inspector mode)."""
    syswide = AXUIElementCreateSystemWide()
    try:
        res = AXUIElementCopyElementAtPosition(syswide, x, y, None)
        el = res[1] if isinstance(res, tuple) else res
    except Exception:
        try:
            err, el = AXUIElementCopyElementAtPosition(syswide, x, y, None)
        except Exception:
            el = None

    el = pick_best_descendant(el)

    # Ensure we capture an actionable element for recording
    if el and (not is_clickable(el) or not ax_best_label(el)):
        # climb up to nearest interactive ancestor
        parent = el
        depth = 0
        while parent is not None and depth < 5:
            if is_clickable(parent) and ax_best_label(parent):
                el = parent
                break
            parent = _parent(parent)
            depth += 1

    # Gather comprehensive element info
    role = ax_get(el, "AXRole")
    subrole = ax_get(el, "AXSubrole")
    role_desc = ax_get(el, "AXRoleDescription")
    title = ax_get(el, "AXTitle")
    desc = ax_get(el, "AXDescription")
    help_ = ax_get(el, "AXHelp")
    ident = ax_get(el, "AXIdentifier")
    value = ax_get(el, "AXValue")
    placeholder = ax_get(el, "AXPlaceholderValue")
    enabled = bool(ax_get(el, "AXEnabled") or False)
    actions = ax_actions(el)
    clickable = is_clickable(el)
    focused = bool(ax_get(el, "AXFocused") or False)

    # Window info
    win = ax_get(el, "AXWindow")
    win_title = ax_get(win, "AXTitle") if win else None
    window_frame = ax_frame_or_compose(win) if win else None

    # PID + app
    pid, app_name = pid_and_app(el)
    app_name_resolved = app_name if app_name else (_to_str(win_title) if win_title else None)

    # Element frame
    frame = ax_frame_or_compose(el)

    # Screen info
    screens = collect_screens_info()
    active_screen = pick_screen_for_rect(
        window_frame or (frame or {"x": float(x), "y": float(y), "w": 1.0, "h": 1.0}), 
        screens
    )

    # Click point calculation
    ap = ax_activation_point(el)
    
    # Validate activation point
    if ap and frame:
        if (ap["x"] <= 1.0 and ap["y"] >= 1000) or \
           (abs(ap["x"] - (frame["x"] + frame["w"]/2)) > frame["w"] * 2) or \
           (abs(ap["y"] - (frame["y"] + frame["h"]/2)) > frame["h"] * 2):
            ap = None

    if ap:
        click_point = {"x": ap["x"], "y": ap["y"]}
    elif frame:
        click_point = {"x": frame["x"] + frame["w"]/2.0, "y": frame["y"] + frame["h"]/2.0}
    else:
        click_point = {"x": float(x), "y": float(y)}

    # Fractions for resize-robust replay
    click_frac = None
    if window_frame and click_point:
        try:
            fx = (float(click_point["x"]) - float(window_frame["x"])) / float(window_frame["w"]) if window_frame["w"] else 0.0
            fy = (float(click_point["y"]) - float(window_frame["y"])) / float(window_frame["h"]) if window_frame["h"] else 0.0
            click_frac = {"fx": fx, "fy": fy}
        except Exception:
            click_frac = None

    # Browser/Electron extras + File ID resolution
    url = ax_get(el, "AXURL")
    resolved_path = None

    from urllib.parse import urlparse, unquote

    # Case 1: Already a real file URL → extract POSIX path
    if url and str(url).startswith("file:///") and not str(url).startswith("file:///.file/id="):
        try:
            _p = unquote(urlparse(str(url)).path)
            if _p and os.path.exists(_p):
                resolved_path = _p
        except Exception:
            pass

    # Case 2: Stale file-id → try to resolve via Spotlight, then Finder front window + filename
    if resolved_path is None and url and str(url).startswith("file:///.file/id="):
        import subprocess
        try:
            # Extract file ID from URL (the numeric node id component)
            file_id = str(url).split("=")[-1]

            # Attempt Spotlight resolution by node id
            result = subprocess.run(
                ["mdfind", f"kMDItemFSNodeID == {file_id}"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                real_path = result.stdout.strip().split("\n")[0]
                if os.path.exists(real_path):
                    resolved_path = real_path
        except Exception:
            pass 

        # Fallback: derive from Finder's front window directory + element label/title
        if resolved_path is None:
            filename = None
            try:
                filename = _to_str(ax_get(el, "AXTitle")) or ax_best_label(el)
            except Exception:
                filename = None

            base = None
            try:
                r = subprocess.run(
                    [
                        "osascript", "-e",
                        'tell application "Finder" to POSIX path of (target of front window as alias)'
                    ],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and r.stdout.strip():
                    base = r.stdout.strip()
            except Exception:
                base = None

            if base and filename:
                cand = os.path.join(base, filename)
                try:
                    if os.path.exists(cand):
                        resolved_path = cand
                except Exception:
                    pass

    if resolved_path:
        try:
            url = f"file://{resolved_path}"
        except Exception:
            pass
    
    selected_text = ax_get(el, "AXSelectedText")

    # AX info collection
    # --------------------------------------------------------------
    # This section gathers a complete snapshot of all accessible properties from
    # any macOS UI element (AXElement). While the system often needs only a subset
    # (title, role, frame, value), collecting the full AX info dictionary serves
    # several essential purposes:
    #
    #   1. Provides a unified, version-stable record for debugging and replay.
    #   2. Enables full reconstruction of element state for learning, validation,
    #      and replaying actions across sessions.
    #   3. Protects against API changes—Apple occasionally renames or removes
    #      attributes between macOS releases, and this ensures no data is lost
    #      when those changes occur.
    #
    # This block enumerates the *complete set of AX attributes* the engine
    # can safely retrieve across macOS versions. It is intentionally exhaustive
    # to act as a canonical "AX element schema" for research and replay.
    # Contributors should not trim or limit this dataset unless performance or
    # privacy concerns demand it.
    #
    # In short: AX info is the foundation of reproducibility and cross-context
    # validation. Without this data, deterministic automation and reflection
    # become impossible.

    ax_info = {
        "role": _to_str(role),
        "container_role": _to_str(ax_get(ax_ancestor(el, roles=("AXWindow",)), "AXRole")),
        "subrole": _to_str(subrole),
        "role_description": _to_str(role_desc),
        "title": _to_str(title),
        "best_label": ax_best_label(el),
        "description": _to_str(desc),
        "help": _to_str(help_),
        "identifier": _to_str(ident),
        "value": _to_str(value),
        "placeholder": _to_str(placeholder),
        "enabled": enabled,
        "actions": actions,
        "clickable": clickable,
        "focused": focused,
        "frame": frame,
        "activation_point": ap,
        "click_point": click_point,
        "window_title": _to_str(win_title),
        "pid": int(pid) if isinstance(pid, int) else None,
        "app_name": app_name_resolved,
        "url": _to_str(url),
        "resolved_path": resolved_path,
        "selected_text": _to_str(selected_text),
        "window_frame": window_frame,
        "screen": active_screen,
        "screen_id": active_screen.get("id") if active_screen else None,
        "screen_bounds": active_screen.get("bounds_points") if active_screen else None,
        "display_scale": active_screen.get("scale") if active_screen else None,
        "click_frac": click_frac,
        "parent_chain": parent_chain(el),
    }

    # Normalize keys to AX-style for best_label_from_info
    ax_info["AXTitle"] = ax_info.get("title")
    ax_info["AXDescription"] = ax_info.get("description")
    ax_info["AXValue"] = ax_info.get("value")
    ax_info["AXHelp"] = ax_info.get("help")
    ax_info["AXPlaceholderValue"] = ax_info.get("placeholder")
    ax_info["AXIdentifier"] = ax_info.get("identifier")
    ax_info["AXRole"] = ax_info.get("role")
    ax_info["AXSubrole"] = ax_info.get("subrole")
    ax_info["AXParentRole"] = ax_info.get("container_role")
    ax_info["AXWindowTitle"] = ax_info.get("window_title")

    # Friendly automation type (what Xcode Accessibility Inspector shows)
    role_desc = ax_info.get("role_description")
    role_raw = ax_info.get("role")
    try:
        friendly_role = str(role_desc) if role_desc else (str(role_raw)[2:] if isinstance(role_raw, str) and role_raw.startswith("AX") else role_raw)
    except Exception:
        friendly_role = role_desc or role_raw
    ax_info["automation_type"] = friendly_role

    # Compute best_label using normalized keys
    ax_info["best_label"] = best_label_from_info(ax_info)

    return ax_info

# ---------------- Mouse Operations ----------------
def hover(pt, debug=False):
    """Hover mouse at point."""
    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, kCGEventMouseMoved, pt, 0))
    time.sleep(HOVER_DELAY)
    if debug:
        loc = None
        try:
            loc = CGEventGetLocation(CGEventCreate(None))
        except Exception:
            pass
        if isinstance(loc, tuple) and len(loc) >= 2:
            mx, my = float(loc[0]), float(loc[1])
            print(f"[HOVER_LOC] mouse now at ({mx:.1f}, {my:.1f}) Δ=({_fmt_pt((mx-pt[0], my-pt[1]))})")

def click(pt, button="left"):
    """Click at point with specified button (left by default, right if requested)."""
    if button == "right":
        down = CGEventCreateMouseEvent(None, Quartz.kCGEventRightMouseDown, pt, Quartz.kCGMouseButtonRight)
        up = CGEventCreateMouseEvent(None, Quartz.kCGEventRightMouseUp, pt, Quartz.kCGMouseButtonRight)
    else:
        down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, pt, kCGMouseButtonLeft)
        up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, pt, kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, down)
    time.sleep(CLICK_DELAY)
    CGEventPost(kCGHIDEventTap, up)

# ---------------- Prediction and Refinement ----------------
def reproject_point_from_windows(pt, rec_win, cur_win):
    """Map recorded point to current window space."""
    sx = (float(cur_win['w']) / float(rec_win['w'])) if rec_win.get('w') else 1.0
    sy = (float(cur_win['h']) / float(rec_win['h'])) if rec_win.get('h') else 1.0
    rx = float(pt[0]) - float(rec_win['x'])
    ry = float(pt[1]) - float(rec_win['y'])
    return (float(cur_win['x']) + rx * sx, float(cur_win['y']) + ry * sy)

def predict_from_window(rec_step, cur_win):
    """Predict click point from window transformation."""
    rec_win = rec_step.get("window_frame")
    if not rec_win or not cur_win:
        return None

    # Prefer fractions if valid in current window
    frac = rec_step.get("click_frac")
    if frac and "fx" in frac and "fy" in frac:
        fx, fy = float(frac["fx"]), float(frac["fy"])
        px = cur_win["x"] + fx * cur_win["w"]
        py = cur_win["y"] + fy * cur_win["h"]
        # Validate inside current window bounds
        if (cur_win["x"] <= px <= cur_win["x"] + cur_win["w"] and
            cur_win["y"] <= py <= cur_win["y"] + cur_win["h"]):
            return (px, py)

    # Fallback: Δ+scale reprojection from click_point
    cp = rec_step.get("click_point")
    if cp and "x" in cp and "y" in cp:
        rx = float(cp["x"]) - float(rec_win["x"])
        ry = float(cp["y"]) - float(rec_win["y"])
        sx = cur_win["w"]/rec_win["w"] if rec_win["w"] else 1.0
        sy = cur_win["h"]/rec_win["h"] if rec_win["h"] else 1.0
        return (cur_win["x"] + rx * sx, cur_win["y"] + ry * sy)

    return None

def neighbor_scan(seed, recorded_step, radius=NEIGHBOR_RADIUS, step=NEIGHBOR_STEP):
    """Scan for better element near seed point."""
    best_pt, best_el, best_m = None, None, {"error": "no hits"}
    best_score = 1e9
    
    for dx in range(-radius, radius+1, step):
        for dy in range(-radius, radius+1, step):
            cand = (seed[0]+dx, seed[1]+dy)
            el, info = hit(cand)
            if el is None:
                continue
            mism = compare_signature(recorded_step, info)
            mcount = len(mism)
            score = mcount*100 + _dist(seed, cand)
            if score < best_score:
                best_pt, best_el, best_m, best_score = cand, el, mism, score
            if mcount == 0:
                return cand, el, {}
    
    return best_pt, best_el, best_m

def pick_child_clickable(el_parent, recorded_step):
    """Find better clickable child in container."""
    rec_role = recorded_step.get("role")
    rec_label = (recorded_step.get("best_label") or recorded_step.get("title") or None)
    best = (None, 1e9, {})
    
    for ch in _children(el_parent) or []:
        info = element_info(ch)
        mism = compare_signature(recorded_step, info)
        miss_count = len(mism)
        role_ok = rec_role == info.get("AXRole") if rec_role else False
        label_ok = rec_label == info.get("best_label") if rec_label else False
        press_ok = has_axpress(info)
        
        score = miss_count * 100
        if role_ok:
            score -= 150
        if label_ok:
            score -= 200
        if press_ok:
            score -= 100
        
        if score < best[1]:
            best = (ch, score, mism)
    
    return best

def micro_refine_target(seed_point, seed_el, recorded_step, debug=False):
    """Micro-refinement to find better target."""
    if seed_el is None:
        return seed_point, seed_el, {"error": "no seed element"}, "none"

    live_info = element_info(seed_el)
    mism = compare_signature(recorded_step, live_info)
    looks_container = live_info.get("AXRole") in ("AXGroup", getattr(Quartz, "kAXGroupRole", "AXGroup"))
    lacks_press = not has_axpress(live_info)
    label_mismatch = "best_label" in mism
    role_mismatch = "role" in mism

    if looks_container or lacks_press or label_mismatch or role_mismatch:
        ch, score, mism_ch = pick_child_clickable(seed_el, recorded_step)
        if ch is not None:
            f_val, _src = decode_frame(ch, element_only=True)
            if f_val:
                new_point = center_of(f_val)
            else:
                new_point = seed_point
            if debug:
                print(f"[MICRO] child refinement → point={new_point} score={score}")
            return new_point, ch, mism_ch, "child"

    n_point, n_el, n_mism = neighbor_scan(seed_point, recorded_step, radius=16, step=4)
    if n_el is not None:
        if debug:
            print(f"[MICRO] neighbor refinement → point={n_point} mismatches={len(n_mism)}")
        return n_point, n_el, n_mism, "neighbor"

    return seed_point, seed_el, mism, "none"

def ax_full_tree_resolve(recorded_step, root_el, max_depth=MAX_TREE_DEPTH, max_nodes=MAX_TREE_NODES):
    """Full AX tree traversal to find best match."""
    if root_el is None:
        return None, None, 0.0, 0

    def score_element(rec, live):
        score = 0.0
        if rec.get("role") == live.get("AXRole"):
            score += 0.40
        rec_best = rec.get("best_label") or rec.get("title")
        live_best = live.get("best_label")
        if rec_best and live_best:
            rec_toks = set(str(rec_best).lower().split())
            live_toks = set(str(live_best).lower().split())
            if rec_toks:
                score += 0.50 * (len(rec_toks & live_toks) / len(rec_toks))
        if has_axpress(live):
            score += 0.10
        return min(1.0, score)

    best_el = None
    best_info = None
    best_score = -1.0
    visited = 0
    queue = [(root_el, 0)]

    while queue and visited < max_nodes:
        el, d = queue.pop(0)
        visited += 1
        info = element_info(el)
        sc = score_element(recorded_step, info)
        if sc > best_score:
            best_score, best_el, best_info = sc, el, info
        if d < max_depth:
            for ch in _children(el) or []:
                queue.append((ch, d+1))

    return best_el, best_info, best_score, visited


def ax_full_window_strict_search(recorded_step, root_el, window_frame=None, max_depth=20, max_nodes=4000, debug=False, root_window=None, allowed_roles=INTERACTIVE_ROLES):
    VERBOSE = False  # per-node tracing toggle for search; keep summaries only
    """
    Adaptive multi-pass BFS search for best element match.
    
    PROBLEM:
    UI trees can have 10,000+ nodes. Exhaustive search is too slow.
    Prioritizing wrong branches wastes time exploring irrelevant subtrees.
    
    SOLUTION:
    Priority queue BFS that explores most promising branches first.
    
    PRIORITY SCORING (0 = highest priority):
    - Exact role match: -6.0 (explore immediately)
    - Interactive role: -3.0 (buttons, links, inputs)
    - UI containers: -2.0 (toolbars, tab groups)
    - Label similarity: -4.0 × word_overlap (more overlap = higher priority)
    - Spatial proximity: -2.0 × proximity_score (closer = higher priority)
    - Depth penalty: +0.1 to +0.3 per level (prefer shallow nodes)
    
    SEARCH PHASES:
    Phase 1: Quick scan (500 nodes, high-priority only)
      - Catches 90% of cases (exact role + label match)
      - Fast failure if element obviously not present
    
    Phase 2: Focused search (1500 nodes, medium-priority)
      - Explores promising containers and near-matches
      - Handles dynamic content (counts, timestamps changed)
    
    Phase 3: Exhaustive fallback (remaining budget)
      - Deep traversal of entire tree
      - Used when element significantly changed
    
    EARLY TERMINATION:
    - Stops immediately on perfect match (0 mismatches + AXPress)
    - Confidence threshold: score ≥ 0.95 stops after Phase 1
    - Time budget: 60 seconds safety valve
    
    CONTENT FILTERING:
    - Skips bulk text content (AXText, AXStaticText in large tables)
    - Ignores microscopic elements (< 12px × 12px)
    - Filters line-like dividers (< 6px thick, > 60px long)
    - Validates window intersection (multi-monitor support)
    
    Args:
        recorded_step: Dict with recorded element signature
        root_el: Root element to search from (usually window or app)
        window_frame: Current window frame for spatial scoring
        max_depth: Maximum tree depth to traverse
        max_nodes: Maximum nodes to visit (prevents UI freeze)
        debug: Print search progress
        root_window: Window element for intersection validation
        allowed_roles: Set of roles to consider (None = all roles)
        
    Returns:
        tuple: (best_element, best_info, best_score, nodes_visited)
    """
    # --- Runtime budget and caching ---
    TIME_BUDGET_S = 60
    _element_cache = {} 
    
    TEXT_CONTENT_ROLES = {
        "AXText", "AXStaticText", "AXCell", "AXRow"
    }

    BULK_CONTENT_CONTAINERS = {
        "AXTable", "AXList"
    }

    UI_CONTROL_CONTAINERS = {
        "AXToolbar", "AXMenuBar", "AXTabGroup", "AXSplitGroup",
        "AXPopUpButton", "AXComboBox", "AXGroup"
    }
    
    start_ts = time.time()
    if root_el is None:
        return None, None, -1.0, 0


    def _cached_element_info(el):
        """Cache element info to avoid repeated AX API calls"""
        el_id = id(el) 
        if el_id not in _element_cache:
            _element_cache[el_id] = element_info(el)
        return _element_cache[el_id]

    def _calculate_element_promise(el, recorded_step, depth=0, window_frame=None):
        """Calculate how promising this element is for containing our target"""
        try:
            info = _cached_element_info(el)
            role = info.get("AXRole", "")
            
            # Base priority (lower = higher priority)
            priority = 10.0
            
            # Role-based scoring
            target_role = recorded_step.get("role", "")
            if role == target_role:
                priority -= 6.0  # Exact role match
            elif role in CLICKABLE_ROLES:
                priority -= 3.0  # Interactive elements
            elif role in UI_CONTROL_CONTAINERS:
                priority -= 2.0  # UI containers
            elif role in CONTAINER_ROLES:
                priority -= 1.0  # General containers
            
            # Label similarity scoring
            target_label = (recorded_step.get("best_label") or "").lower()
            element_label = (info.get("best_label") or "").lower()
            if target_label and element_label:
                # Simple word overlap similarity
                target_words = set(target_label.split())
                element_words = set(element_label.split())
                if target_words and element_words:
                    overlap = len(target_words & element_words) / len(target_words)
                    priority -= overlap * 4.0
            
            # Spatial proximity (if we have click coordinates)
            if window_frame and "click_frac" in recorded_step:
                frac = recorded_step["click_frac"]
                if "fx" in frac and "fy" in frac:
                    target_x = window_frame["x"] + frac["fx"] * window_frame["w"]
                    target_y = window_frame["y"] + frac["fy"] * window_frame["h"]
                    
                    frame = info.get("frame") or ax_frame_or_compose(el)
                    if frame:
                        el_center_x = frame["x"] + frame["w"] / 2
                        el_center_y = frame["y"] + frame["h"] / 2
                        distance = hypot(el_center_x - target_x, el_center_y - target_y)
                        # Normalize distance (closer = higher priority)
                        max_distance = hypot(window_frame["w"], window_frame["h"])
                        if max_distance > 0:
                            proximity_score = 1.0 - min(distance / max_distance, 1.0)
                            priority -= proximity_score * 2.0
            
            # Depth penalty (but not too harsh for containers)
            if role in CONTAINER_ROLES:
                priority += min(depth * 0.1, 1.0)  # Light penalty for containers
            else:
                priority += min(depth * 0.3, 2.0)  # Heavier penalty for leaves
            try:
                return float(priority)
            except Exception:
                return 15.0
        except Exception:
            return 15.0  # Low priority if we can't analyze

    def _text_similarity(text1, text2):
        """Simple text similarity scoring"""
        if not text1 or not text2:
            return 0.0
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1:
            return 0.0
        return len(words1 & words2) / len(words1)

    def soft_score(rec, live):
        score = 0.0
        if rec.get("role") == live.get("AXRole"):
            score += 0.40
        rec_best = rec.get("best_label") or rec.get("title")
        live_best = live.get("best_label")
        if rec_best and live_best:
            score += 0.50 * _text_similarity(rec_best, live_best)
        if has_axpress(live):
            score += 0.10
        return min(1.0, score)

    def _size_ok(frame):
        if not frame:
            return True
        return (frame.get("w", 0) >= MIN_NODE_WH) and (frame.get("h", 0) >= MIN_NODE_WH)

    def _is_line_like(frame):
        if not frame:
            return False
        w = float(frame.get("w", 0))
        h = float(frame.get("h", 0))
        thin = (w <= TINY_LINE_THICKNESS) or (h <= TINY_LINE_THICKNESS)
        long = (w >= MIN_LINE_LENGTH) or (h >= MIN_LINE_LENGTH)
        return thin and long

    def _intersects_window(live_info):
        if root_window is not None:
            try:
                anc = ax_ancestor(live_info.get("_el"), roles=("AXWindow",))
                if anc is None or anc != root_window:
                    return False
            except Exception:
                return False
        if not window_frame:
            return True
        f = live_info.get("frame") or ax_frame_or_compose(live_info.get("_el"))
        if not f:
            return True
        rx1, ry1 = f["x"], f["y"]
        rx2, ry2 = f["x"] + f["w"], f["y"] + f["h"]
        wx1, wy1 = window_frame["x"], window_frame["y"]
        wx2, wy2 = window_frame["x"] + window_frame["w"], window_frame["y"] + window_frame["h"]
        return not (rx2 < wx1 or rx1 > wx2 or ry2 < wy1 or ry1 > wy2)

    rec_norm_label = _norm_text((recorded_step.get("title") or recorded_step.get("best_label")))

    def _clickable_ancestor_if_label_match(el, live_info, rec_norm_label, max_up=5):
        if rec_norm_label is None:
            return None, None
        def _norm(s):
            if s is None:
                return None
            try:
                import unicodedata
                return unicodedata.normalize("NFKC", str(s)).strip().casefold()
            except Exception:
                return str(s).strip().lower() if isinstance(s, str) else None

        if _norm(live_info.get("best_label")) != rec_norm_label:
            return None, None

        cur = el
        steps = 0
        while cur is not None and steps < max_up:
            role = _to_str(ax_get(cur, "AXRole"))
            if (role in CLICKABLE_ROLES) or is_clickable(cur):
                info = _cached_element_info(cur)
                if _intersects_window(info) and _size_ok(info.get("frame") or ax_frame_or_compose(cur)):
                    return cur, info
                else:
                    return None, None
            cur = _parent(cur)
            steps += 1
        return None, None
    
    def _is_bulk_content(role, info, depth):
        """Detect bulk content that should be skipped, but be less aggressive for web apps."""
        if role in TEXT_CONTENT_ROLES:
            return True
            
        if role in BULK_CONTENT_CONTAINERS:
            children = _children(info.get("_el")) or []
            return len(children) > 100 and depth > 8
            
        children = _children(info.get("_el")) or []
        if len(children) > 200 and depth > 10:
            return True
            
        return False

    def _should_continue_search(visited, budget, best_score, strict_matches, phase_name):
        """Dynamic termination based on search phase and results"""
        # Time budget exceeded (safety valve)
        if (time.time() - start_ts) > TIME_BUDGET_S:
            return False
        # Budget exhausted
        return visited < budget

    def _adaptive_search_phase(phase_name, budget, max_search_depth, use_enhanced_priority=True):
        """Execute one phase of the adaptive search"""
        best_el = None
        best_info = None
        best_score = -1.0
        strict_pool = []
        visited = 0
        import heapq
        priority_queue = []
        counter = 0  # strict tiebreaker to avoid comparing AX objects

        if use_enhanced_priority:
            for child in _children(root_el) or []:
                priority = _calculate_element_promise(child, recorded_step, 1, window_frame)
                if priority is None or not isinstance(priority, (int, float)):
                    priority = 15.0
                heapq.heappush(priority_queue, (float(priority), counter, id(child), child, 1))
                counter += 1
        else:
            # Fallback to original prioritization seeded by root's children
            for child in _children(root_el) or []:
                child_role = _to_str(ax_get(child, "AXRole"))
                priority = _prioritize_element_original(child_role, 1)
                heapq.heappush(priority_queue, (float(priority), counter, id(child), child, 1))
                counter += 1

        while priority_queue and _should_continue_search(visited, budget, best_score, len(strict_pool), phase_name):
            _, _, _, el, d = heapq.heappop(priority_queue)
            visited += 1

            info = _cached_element_info(el)
            info["_el"] = el
            role = info.get("AXRole")
            frame = info.get("frame") or ax_frame_or_compose(el)

            # Content filtering
            if _is_bulk_content(role, info, d):
                continue

            # Window intersection check
            if not _intersects_window(info):
                continue

            # Size filtering
            is_tiny_or_line = (not _size_ok(frame)) or _is_line_like(frame)
            if is_tiny_or_line:
                # Still traverse containers
                if d < max_search_depth and role in CONTAINER_ROLES:
                    for ch in _children(el) or []:
                        if use_enhanced_priority:
                            child_priority = _calculate_element_promise(ch, recorded_step, d+1, window_frame)
                        else:
                            child_role = _to_str(ax_get(ch, "AXRole"))
                            child_priority = _prioritize_element_original(child_role, d+1)

                        if child_priority is None or not isinstance(child_priority, (int, float)):
                            child_priority = 15.0

                        heapq.heappush(priority_queue, (float(child_priority), counter, id(ch), ch, d+1))
                        counter += 1
                continue

            # Strict identity matching
            if strict_identity_ok(recorded_step, info):
                strict_pool.append((el, info))
            else:
                # Bubble up for non-interactive elements
                if role not in INTERACTIVE_ROLES and role not in CONTAINER_ROLES:
                    bubbled_el, bubbled_info = _clickable_ancestor_if_label_match(el, info, rec_norm_label)
                    if bubbled_el is not None and strict_identity_ok(recorded_step, bubbled_info):
                        strict_pool.append((bubbled_el, bubbled_info))
                        continue

                # Soft scoring for interactive elements
                if not allowed_roles or (role in allowed_roles) or (role in CONTAINER_ROLES):
                    sc = soft_score(recorded_step, info)
                    if sc > best_score:
                        best_el, best_info, best_score = el, info, sc

            # Add children to queue
            if d < max_search_depth:
                for ch in _children(el) or []:
                    if use_enhanced_priority:
                        child_priority = _calculate_element_promise(ch, recorded_step, d+1, window_frame)
                    else:
                        child_role = _to_str(ax_get(ch, "AXRole"))
                        child_priority = _prioritize_element_original(child_role, d+1)

                    if child_priority is None or not isinstance(child_priority, (int, float)):
                        child_priority = 15.0

                    heapq.heappush(priority_queue, (float(child_priority), counter, id(ch), ch, d+1))
                    counter += 1

        return best_el, best_info, best_score, strict_pool, visited

    def _prioritize_element_original(role, depth):
        """Original priority function for fallback"""
        if role in UI_CONTROL_CONTAINERS:
            return 0
        if role in CLICKABLE_ROLES:
            return 1
        if role in INTERACTIVE_ROLES:
            return 2
        if role == "AXWebArea":
            return 3
        if role in CONTAINER_ROLES:
            return 4 + min(depth, 5)
        return 10
    
    # Single Exhaustive search
    total_visited = 0
    final_strict_pool = []

    # PHASE 1E: Full budget exhaustive search
    best_el, best_info, best_score, strict_pool, visited = _adaptive_search_phase(
        "EXHAUSTIVE", max_nodes, max_depth, use_enhanced_priority=True
    )
    total_visited += visited
    final_strict_pool.extend(strict_pool)
    
    if best_score >= 0.95 or len(strict_pool) > 0:
        pass
    else:
        # PHASE 2: Focused search (50% of remaining budget)  
        remaining_budget = max_nodes - total_visited
        focused_budget = max(1000, remaining_budget // 2)
        
        if focused_budget > 100:
            f_best_el, f_best_info, f_best_score, f_strict_pool, f_visited = _adaptive_search_phase(
                "FOCUSED", focused_budget, max_depth, use_enhanced_priority=True
            )
            total_visited += f_visited
            final_strict_pool.extend(f_strict_pool)
            
            if f_best_score > best_score:
                best_el, best_info, best_score = f_best_el, f_best_info, f_best_score
        
        # PHASE 3: Exhaustive fallback (remaining budget)
        if best_score < 0.85 and len(final_strict_pool) == 0:
            remaining_budget = max_nodes - total_visited
            if remaining_budget > 100:
                e_best_el, e_best_info, e_best_score, e_strict_pool, e_visited = _adaptive_search_phase(
                    "EXHAUSTIVE", remaining_budget, max_depth, use_enhanced_priority=False
                )
                total_visited += e_visited
                final_strict_pool.extend(e_strict_pool)
                
                if e_best_score > best_score:
                    best_el, best_info, best_score = e_best_el, e_best_info, e_best_score

    # Overall search summary
    if debug:
        print(f"[ADAPT/BFS] Search complete: total_visited={total_visited}, strict_pool={len(final_strict_pool)}, best_score={best_score:.2f}")
    # Process strict matches if found
    if final_strict_pool:
        def strict_rank(t):
            el, info = t
            press_bias = 1 if has_axpress(info) else 0
            dist = 0.0
            frac = recorded_step.get("click_frac")
            if window_frame and frac and "fx" in frac and "fy" in frac:
                px = window_frame["x"] + frac["fx"] * window_frame["w"]
                py = window_frame["y"] + frac["fy"] * window_frame["h"]
                f = ax_frame_or_compose(el) or {"x": px, "y": py, "w": 1, "h": 1}
                cx, cy = f["x"] + f["w"]/2.0, f["y"] + f["h"]/2.0
                dist = hypot(cx - px, cy - py)
            return (-press_bias, dist)

        final_strict_pool.sort(key=strict_rank)
        chosen_el, chosen_info = final_strict_pool[0]
        if debug:
            cf = chosen_info.get("frame") or ax_frame_or_compose(chosen_el)
            print(f"[ADAPT] CHOSEN: role={chosen_info.get('AXRole')} label={chosen_info.get('best_label')} frame={_fmt_rect(cf) if cf else '(no frame)'}")
        return chosen_el, chosen_info, 1.0, total_visited

    return best_el, best_info, best_score, total_visited

def should_allow_container_mismatch(recorded_step, live_info, mismatch_count):
    """Allow 1 mismatch for safe container elements in trusted contexts."""
    if mismatch_count > 1:
        return False
    
    live_role = live_info.get("AXRole")
    recorded_role = recorded_step.get("role")
    is_trusted = recorded_step.get("_trusted_app_context", False)
    
    # Same app + safe container + 1 mismatch = allow
    if (is_trusted and 
        live_role in SAFE_CONTAINER_ROLES and 
        mismatch_count == 1):
        return True
    
    # Safe container matching safe container = allow    
    if (recorded_role in SAFE_CONTAINER_ROLES and 
        live_role in SAFE_CONTAINER_ROLES and 
        mismatch_count == 1):
        return True
        
    return False

# ---------------- Main Engine Class ----------------
class AXEngine:
    def _adapt_full_window(self, recorded_step, *, app_el, win_el, pid, cur_win_frame, debug=False):
        """
        Recovery path: strict full-window AX search rooted at recorded window/app.
        Returns dict with keys:
          executed (bool) - True if AXPress performed and we're done
          el, info, point  - chosen element/info/point when not executed
        """
        # 1) Preconditions: ensure frontmost and dismiss overlays via titlebar nudge
        if NSWorkspace and pid:
            ws = NSWorkspace.sharedWorkspace()
            front_app = ws.frontmostApplication()
            if not (front_app and front_app.processIdentifier() == pid):
                if debug:
                    print("🔄 [ADAPT] Bringing app to front…")
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                if app:
                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    time.sleep(APP_ACTIVATION_DELAY)

        # 2) Root selection
        root = win_el
        if root is None and app_el is not None:
            root = app_el
        if root is None and app_el is None and pid:
            try:
                root = AXUIElementCreateApplication(pid)
            except Exception:
                root = None

        # 3) Full-window strict traversal
        best_el, best_info, best_score, visited = ax_full_window_strict_search(
            recorded_step,
            root,
            window_frame=cur_win_frame,
            max_depth=25,
            max_nodes=20000,
            debug=debug,
            root_window=win_el,
            allowed_roles=None,
        )
        if debug:
            print(f"[ADAPT] visited={visited} best_score={best_score:.2f} strict_ok={strict_identity_ok(recorded_step, best_info) if best_info else False}")
            if best_info:
                bf = best_info.get("frame") or ax_frame_or_compose(best_el)
                print(f"[ADAPT] found role={best_info.get('AXRole')} label={best_info.get('best_label')} title={best_info.get('AXTitle')} frame={_fmt_rect(bf) if bf else '(no frame)'} axpress={has_axpress(best_info)}")

        if best_el is None or best_info is None:
            return {"executed": False, "el": None, "info": None, "point": None}

        # 4/5) If strict match, execute now (AXPress or biased click).
        is_strict = strict_identity_ok(recorded_step, best_info)
        if is_strict:
            if has_axpress(best_info):
                if debug:
                    print("[ADAPT] Strict match: AXPress on chosen node.")
                ok = ax_perform_press(best_el)
                if ok:
                    return {"executed": True, "el": best_el, "info": best_info, "point": None}
                else:
                    if debug:
                        print("[ADAPT] AXPress failed; falling back to click.")

            # Compute a safe click point (validate activation point; else use frame)
            f2, _ = decode_frame(best_el, element_only=True)
            ap = get_activation_point(best_el)
            pt = None

            # Validate activation point - reject obviously bad coordinates
            if ap and f2:
                # Check if activation_point is reasonable relative to element frame
                frame_center_x = f2["x"] + f2["w"]/2
                frame_center_y = f2["y"] + f2["h"]/2

                # Reject if too far from frame or at screen edges
                if (abs(ap[0] - frame_center_x) > f2["w"] * 3 or
                    abs(ap[1] - frame_center_y) > f2["h"] * 3 or 
                    ap[0] <= 1.0 or ap[1] >= 1070):  # Screen edge coords
                    # Bad activation point - fall through to role-based logic
                    if debug:
                        print(f"[ADAPT] Bad activation_point {_fmt_pt(ap)}, using frame-based logic")
                    ap = None  # Set to None AFTER using it in debug
                else:
                    pt = ap
                    if debug:
                        print(f"[ADAPT] Strict match: clicking activation_point at {_fmt_pt(pt)}")

            # If no valid activation point, use role-based clicking
            if pt is None and f2:
                role = best_info.get("AXRole")
                if role in {"AXCheckBox", "AXRadioButton", "AXButton", "AXTab", "AXPopUpButton"}:
                    # Bias left-third, vertically centered to avoid text spans overlaying the control
                    bx = f2["x"] + min(10.0, 0.2 * f2["w"])
                    by = f2["y"] + f2["h"] / 2.0
                    pt = (bx, by)
                    if debug:
                        print(f"[ADAPT] Strict match: biased click at {_fmt_pt(pt)} within frame {_fmt_rect(f2)}")
                else:
                    pt = (f2["x"] + f2["w"]/2, f2["y"] + f2["h"]/2)
                    if debug:
                        print(f"[ADAPT] Strict match: center click at {_fmt_pt(pt)} within frame {_fmt_rect(f2)}")

            if pt:
                hover(pt)
                click(pt, button="left")
                return {
                    "executed": True,
                    "el": best_el,
                    "info": best_info,
                    "point": pt,
                    "button": "left",
                    "method": "mouse_left"
                }
                    
        # Non-strict: Prefer AXPress; else hand back point to caller for L5/L6.
        if has_axpress(best_info):
            if debug:
                print("[ADAPT] Non-strict: Performing AXPress on selected node.")
            ok = ax_perform_press(best_el)
            if ok:
                return {"executed": True, "el": best_el, "info": best_info, "point": None}

        f2, _ = decode_frame(best_el, element_only=True)
        pt = center_of(f2) if f2 else None
        return {"executed": False, "el": best_el, "info": best_info, "point": pt}
    
    def _execute_type_action(self, text: str, target_element=None, debug=False):
        """Adaptive typing: AX setValue → CGEvent paste → fallback"""
        if not text:
            return False
        
        # Strategy 1: AX setValue
        if target_element:
            try:
                from ApplicationServices import AXUIElementSetAttributeValue
                err = AXUIElementSetAttributeValue(target_element, "AXValue", text)
                if err == 0:
                    if debug:
                        print(f"[TYPE] AX setValue: '{text}'")
                    return True
            except Exception:
                pass
        
        # Strategy 2: Clipboard + CGEvent paste
        try:
            import pyperclip
            from Quartz.CoreGraphics import (
                CGEventCreateKeyboardEvent, CGEventSetFlags, CGEventPost,
                kCGHIDEventTap, kCGEventFlagMaskCommand
            )
            
            old_clipboard = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.1)
            
            # Cmd+V using CGEvent (keycode 9 = 'v')
            v_down = CGEventCreateKeyboardEvent(None, 9, True)
            CGEventSetFlags(v_down, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, v_down)
            
            time.sleep(0.05)
            
            v_up = CGEventCreateKeyboardEvent(None, 9, False)
            CGEventPost(kCGHIDEventTap, v_up)
            
            time.sleep(0.1)
            pyperclip.copy(old_clipboard)
            
            if debug:
                print(f"[TYPE] CGEvent paste: '{text}'")
            return True
        except Exception as e:
            if debug:
                print(f"[TYPE] CGEvent failed: {e}")
        
        # Strategy 3: PyAutoGUI fallback
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=0.05)
            if debug:
                print(f"[TYPE] PyAutoGUI fallback: '{text}'")
            return True
        except Exception as e:
            if debug:
                print(f"[TYPE] All failed: {e}")
            return False
        
    def _execute_key_action(self, key: str, debug=False):
        """Execute keyboard key press"""
        if not key:
            return False
        
        try:
            import pyautogui
            
            # Handle key combinations (cmd+c, ctrl+v, etc.)
            if "+" in key:
                parts = key.split("+")
                modifiers = parts[:-1]
                main_key = parts[-1]
                
                # Map modifiers
                mapped = []
                for mod in modifiers:
                    if mod in ['cmd', 'command']:
                        mapped.append('command')
                    elif mod in ['ctrl', 'control']:
                        mapped.append('ctrl')
                    else:
                        mapped.append(mod)
                
                pyautogui.hotkey(*mapped, main_key)
                if debug:
                    print(f"[KEY] Combo: {key}")
            else:
                # Single key press
                pyautogui.press(key)
                if debug:
                    print(f"[KEY] Press: {key}")
            
            return True
        except Exception as e:
            if debug:
                print(f"[KEY] Failed: {e}")
            return False
    
    """
    Implements the full reflection-first execution pipeline for macOS automation.
    Each numbered layer (L0–L7) represents a deterministic phase of validation,
    refinement, and controlled action.

    - L0: Fresh State
        Initialize execution with a cold start. Ensure Accessibility trust is enabled.
        Clear prior app/window state so every step begins clean and consistent.

    - L1: App and Window Resolution
        Verify the intended application and window are active. Resolve PID and app element,
        confirm recorded vs live match, and bring the app to the foreground if needed.

    - L2: Window Geometry Alignment
        Compute the transformation between recorded and live window frames. Calculate deltas (Δ)
        and scale factors, reproject recorded points into the live space, and prepare recovery
        if geometry mismatches are detected.

    - L3: Target Prediction
        Predict the element’s live location from window transforms using fractions, activation
        point, or frame/click center. Run a preflight hit-test to validate the candidate element.

    - L4: Refinement Pipeline
        If mismatches are present, refine via micro-refinement (children/neighbor), strict AX tree
        search, and candidate evaluation. Converge on zero mismatches when possible. Otherwise fall
        back to the best neighbor or validated point.

    - L5: Hit-Test Confirmation
        Hover over the candidate point and re-run the hit-test. Confirm element identity and
        recorded signature alignment before committing to action.

    - L6: Execution with Safeguards
        Perform the final action (AXPress or synthetic click) at the validated point. If safe-click
        mode is enabled, execute only when mismatches are zero. Otherwise attempt a guarded action.

    - L7: Escalation Layer
        If execution fails after retries, escalate to OCR/visual parsing or multimodal reasoning.
        As a last resort, request human correction.
        This is not implemented so you can choose the best approach for your use case.
    """
    
    def __init__(self):
        """Initialize the AX engine."""
        self.recorded_buffer = []
        self.run_loop = None
        self.stop_requested = False
        
    def ensure_trust(self):
        """Ensure accessibility permissions."""
        ensure_trust()
        
    def inspect_step(self, x, y, save_to_buffer=True):
        """
        Inspect element at coordinates and optionally save to buffer.
        
        Args:
            x, y: Screen coordinates
            save_to_buffer: Whether to append to recorded_buffer
            
        Returns:
            dict: Comprehensive element information
        """
        data = inspect_at_point(x, y)
        
        if save_to_buffer:
            try:
                import time as _t
                data['recorded_at'] = _t.strftime('%Y-%m-%d %H:%M:%S')
                data["schema_version"] = SCHEMA_VERSION
                data['click_index'] = len(self.recorded_buffer)
                self.recorded_buffer.append(data)
            except Exception as e:
                print(f"[BUFFER_ERROR] {e}")
                
        return data
        
    def save_inspection_buffer(self, path="inspector.json"):
        """Save recorded buffer to JSON file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.recorded_buffer, f, ensure_ascii=False, indent=2)
            print(f"[SAVED] Wrote {len(self.recorded_buffer)} click(s) to {path}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to write {path}: {e}")
            return False
            
    def clear_buffer(self):
        """Clear the inspection buffer."""
        self.recorded_buffer.clear()
        
    def _execute_enter_key(self, recorded_step, debug=False):
        """Handle Enter key with clean modifier state"""
        app = (recorded_step.get("app") or "").lower()
        
        if debug:
            print(f"[ENTER] Executing for app: {app}")
        
        try:
            import pyautogui
            
            # Release all modifier keys to ensure clean state
            for mod in ['command', 'ctrl', 'alt', 'shift']:
                try:
                    pyautogui.keyUp(mod)
                except:
                    pass
            
            time.sleep(0.05)  # Brief pause after releasing modifiers
            
            # Now press enter cleanly
            pyautogui.press('enter')
            
            if debug:
                print(f"[ENTER] Pressed successfully")
            return True
        except Exception as e:
            if debug:
                print(f"[ENTER] Failed: {e}")
            return False

    def execute_step(self, recorded_step, **kwargs):
        action = (recorded_step.get("action") or "").lower()
        debug = kwargs.get("debug", False)

        # == LX BYPASSES AND OVERRIDES ==

        # Minimal OS-level delegation for Finder file/folder opens
        # Accept both 'open' and 'os_command' to cover orchestrator variants.
        if action in ("open", "os_command"):
                    app = (recorded_step.get("app") or "").lower()
                    url = recorded_step.get("url") or ""
                    path_hint = recorded_step.get("resolved_path") or recorded_step.get("path") or ""
                    target_hint = recorded_step.get("target") or ""

                    if "finder" in app and (url.startswith("file://") or path_hint or target_hint):
                        try:
                            from macos_executor import OSExecutor
                            raw = url or path_hint or target_hint
                            ok = OSExecutor(debug=debug).execute_step({
                                "action": "open",
                                "app": recorded_step.get("app", ""),
                                "url": raw
                            })
                            return bool(ok)
                        except Exception as e:
                            if debug:
                                print(f"[AX→OS] Delegation failed ({e}); continuing with AX pipeline")

                    # App activation - if app already running, activate instead of launching new instance
                    if app and not (url or path_hint or target_hint):
                        app_name = recorded_step.get("app") or recorded_step.get("app_name") or ""
                        
                        if NSWorkspace and app_name:
                            ws = NSWorkspace.sharedWorkspace()
                            for ra in ws.runningApplications():
                                try:
                                    name = str(ra.localizedName()) if ra.localizedName() else None
                                    if name and name.lower() == app_name.lower():
                                        if debug:
                                            print(f"[OPEN] ✅ '{app_name}' already running → activating")
                                        try:
                                            ra.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                                            time.sleep(0.3)
                                            return True
                                        except Exception as e:
                                            if debug:
                                                print(f"[OPEN] ❌ Activation failed: {e}")
                                            return False
                                except:
                                    continue
                            
                            # App not running - launch it
                            if debug:
                                print(f"[OPEN] 🚀 Launching '{app_name}'")
                            try:
                                import subprocess
                                result = subprocess.run(["open", "-a", app_name], 
                                                    capture_output=True, text=True, timeout=5)
                                if result.returncode == 0:
                                    time.sleep(0.5)
                                    return True
                                else:
                                    if debug:
                                        print(f"[OPEN] ❌ Launch failed: {result.stderr}")
                                    return False
                            except Exception as e:
                                if debug:
                                    print(f"[OPEN] ❌ Launch exception: {e}")
                                return False

        # --- Type actions (text input) ---
        if action == "type":
            text = recorded_step.get("text", "")
            target_el = recorded_step.get("_target_element")
            return self._execute_type_action(text, target_el, debug=kwargs.get("debug", False))

        # --- Key actions (keyboard) ---
        if action == "key":
            key = recorded_step.get("key", "")
            debug = kwargs.get("debug", False)

            # Special handler for enter key
            if key == "enter":
                return self._execute_enter_key(recorded_step, debug=debug)

            # All other keys use generic handler
            return self._execute_key_action(key, debug=debug)

        # --- Click actions ---
        if action == "click":
            
            # --- Menu roles bypass: use AXPress on menu items/menus directly ---
            role_str = (recorded_step.get("ax_role") or recorded_step.get("role") or "").strip()
            if role_str in {"AXMenu", "AXMenuBar", "AXMenuBarItem", "AXMenuItem"}:
                if kwargs.get("debug", False):
                    print(f"[MENU] Bypass L0–L7 for role={role_str}")
                return _execute_menu_click(recorded_step, debug=kwargs.get("debug", False))
            
            # Right-click bypass (coordinate-based)
            req_button = (recorded_step.get("button") or "left").strip().lower()
            if req_button == "right":
                pt = recorded_step.get("coordinates")
                if pt:
                    try:
                        hover(tuple(pt))
                    except Exception:
                        pass  # best-effort hover
                    try:
                        click(tuple(pt), button="right")
                    except Exception as e:
                        return {"executed": False, "reason": f"click failed: {e}"}
                    return {
                        "executed": True,
                        "point": tuple(pt),
                        "button": "right",
                        "method": "mouse_right"
                    }
                else:
                    return {
                        "executed": False,
                        "reason": "no coordinates for right-click"
                    }

        # --- Fallback: run full L0-L7 pipeline (left-clicks and other actions) ---
        return self._run_once(recorded_step, **kwargs)
        
    def _run_once(self, recorded_step, *, do_hover=False, do_click=False, safe_click=True, recover=True, debug=True, diag=False):
        """Internal execution implementation with multi-layered browser resolution."""
        
        # L0 - Fresh State 
        self.ensure_trust()
        if debug:
            print("🧼 L0: Cold start – cleared prior state")
        
        rec_app = recorded_step.get("app_name")
        rec_title = recorded_step.get("window_title")

        # --- L0: Multi-layered Browser-aware Resolution ---
        # Intentional Chrome priority:
        # Although we aim to be browser-agnostic, Chrome currently provides the most
        # reliable and consistent Accessibility (AX) tree exposure on macOS.
        # Safari and Firefox frequently fail to return AXFrames or ActivationPoints.
        # Comet (Perplexity) behaves correctly, but Atlas (OpenAI) has a confirmed issue where it
        # opens multiple blank windows, breaking automation.
        # Until full cross-browser validation is achieved, Chrome remains the dependable fallback.
        
        pid = None
        app_el = None
        win_el = None

        # Layer 1: Primary Browser-aware resolver
        
        pid, app_el, win_el = resolve_app_window_by_recording(rec_app, rec_title, debug=debug)
        if debug and pid:
            print(f"🎯 L0: Primary resolver found pid={pid}")

        # Layer 2: Blacklist guard - reject system processes
        if pid is not None:
            chosen_name = app_name_for_pid(pid)
            if chosen_name and chosen_name in SYSTEM_PROCESS_BLACKLIST:
                if debug:
                    print(f"🛡️ L0: Rejected blacklisted process '{chosen_name}', trying fallbacks")
                pid = app_el = win_el = None

        # Layer 3: Frontmost browser fallback
        if pid is None and NSWorkspace is not None:
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is not None:
                bundle = str(front.bundleIdentifier()) if front.bundleIdentifier() else ""
                
                # Browser bundle mapping
                BROWSER_BUNDLES = {
                    "com.google.Chrome": ["chrome", "google chrome", "gmail"],
                    "com.apple.Safari": ["safari"],
                    "org.mozilla.firefox": ["firefox"],
                    "com.microsoft.edgemac": ["edge"],
                    "com.operasoftware.Opera": ["opera"]
                }
                
                # Check if frontmost app matches requested browser
                is_target_browser = False
                if rec_app:
                    rec_app_lower = rec_app.lower()
                    for bundle_id, app_names in BROWSER_BUNDLES.items():
                        if bundle == bundle_id and any(name in rec_app_lower for name in app_names):
                            is_target_browser = True
                            break
                else:
                    # If no specific app requested, accept any browser
                    is_target_browser = bundle in BROWSER_BUNDLES

                if is_target_browser:
                    pid = front.processIdentifier()
                    app_el = AXUIElementCreateApplication(pid)
                    wins = get_windows(app_el)
                    # Prefer main or focused window
                    chosen_win = None
                    for w in wins or []:
                        try:
                            if (AXGet(w, "AXMain") is True or 
                                AXGet(w, ATTR.get("AXFocused", "AXFocused")) is True):
                                chosen_win = w
                                break
                        except:
                            continue
                    win_el = chosen_win or (wins[0] if wins else None)
                    if debug:
                        print(f"🌟 L0: Frontmost browser selected pid={pid}")

        # Layer 4: Browser finder last resort
        if pid is None:
            browsers = find_browser() or []

            target_bundle = "com.google.Chrome"
            if rec_app and "safari" in rec_app.lower():
                target_bundle = "com.apple.Safari"
            elif rec_app and "firefox" in rec_app.lower():
                target_bundle = "org.mozilla.firefox"

            for bpid, bname, bid in browsers:
                if bid == target_bundle:
                    pid = bpid
                    app_el = AXUIElementCreateApplication(pid)
                    wins = get_windows(app_el)
                    win_el = wins[0] if wins else None
                    if debug:
                        print(f"🔎 L0: Fallback found {bname} pid={bpid}")
                    break
        

        # Layer 5: Generic frontmost app fallback (non-browser)
        if pid is None and NSWorkspace is not None:
            front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front_app is not None:
                pid = front_app.processIdentifier()
                app_el = AXUIElementCreateApplication(pid)
                wins = get_windows(app_el)
                win_el = wins[0] if wins else None
                if debug:
                    print(f"🪄 L0: Fallback to frontmost app {front_app.localizedName()} pid={pid}")


        # --- Final L0 validation (relaxed) ---
        if pid is None:
            print("❌ L0: Could not resolve target process")
            return False

        if win_el is None:
            # If we resolved PID but not window, allow continuation with warning
            app_name = app_name_for_pid(pid) or "Unknown"
            print(f"⚠️ L0: Window not resolved for {app_name} (pid={pid}) — continuing with PID match only")
        else:
            if debug:
                print(f"✅ L0: App/Window resolved — pid={pid}")

        # Continue even if no window title match, as long as PID is valid
        
        # --- L1: Identity Validation & App Activation ---
        def _normalize_space(s: str) -> str:
            if s is None:
                return ""
            return (
                str(s)
                .replace("\u202f", " ")
                .replace("\u00a0", " ")
                .strip()
            )

        def _strip_dynamic_bits(title: str) -> str:
            """Remove volatile parts: unread counts, emails, timestamps, Chrome suffixes."""
            if not title:
                return ""
            t = _normalize_space(title)
            t = re.sub(r"\(\d[\d,]*\)", "", t)                           
            t = re.sub(r"\b[^\s@]+@[^\s@]+\b", "", t)                  
            t = re.sub(r"\b\d{1,2}:\d{2}\s?[AP]M\b", "", t, flags=re.I)
            t = re.sub(r"\s*-\s*Google Chrome\b.*$", "", t, flags=re.I)
            t = re.sub(r"\s+-\s+", " - ", t)
            t = re.sub(r"\s{2,}", " ", t)
            return t.strip().casefold()

        def _titles_semantic_equal(rec_title: str, live_title: str) -> bool:
            """Check if window titles match semantically, allowing for dynamic content."""
            if not rec_title and not live_title:
                return True
            if not rec_title or not live_title:
                return False
            
            rec = _strip_dynamic_bits(rec_title)
            live = _strip_dynamic_bits(live_title)
            
            # Exact match after normalization
            if rec == live:
                return True
            
            # Extract app name from title using " - " pattern
            # "Activity - Nolte - Slack" → ["activity", "nolte", "slack"]
            rec_parts = [p.strip() for p in rec.split(" - ") if p.strip()]
            live_parts = [p.strip() for p in live.split(" - ") if p.strip()]
            
            if not rec_parts or not live_parts:
                return rec == live
            
            # Compare app name (rightmost segment) + context (second from right)
            rec_suffix = " - ".join(rec_parts[-2:]) if len(rec_parts) >= 2 else rec_parts[-1]
            live_suffix = " - ".join(live_parts[-2:]) if len(live_parts) >= 2 else live_parts[-1]
            
            # Match if suffixes match (e.g., "nolte - slack" matches "nolte - slack")
            return rec_suffix == live_suffix

        def _recorded_app_to_canonical(app: str) -> str:
            if not app:
                return ""
            a = _normalize_space(app)
            if " - Google Chrome" in a or a.strip().casefold() in {"gmail", "chrome", "google chrome"}:
                return "google chrome"
            return a.strip().casefold()

        # Get current app/window info
        cur_title = AXGet(win_el, ATTR["AXTitle"]) if win_el else None
        _, app_name = pid_and_app(app_el) if app_el else (None, None)
        cur_win_frame, _ = decode_frame(win_el)

        # Canonicalize app names/titles
        live_app_name = app_name_for_pid(pid) if pid else None
        rec_app_raw   = (recorded_step.get("app") or recorded_step.get("app_name") or rec_app or None)
        rec_title_raw = (recorded_step.get("window_title") or recorded_step.get("title") or rec_title or None)

        rec_app_canon  = _recorded_app_to_canonical(rec_app_raw)
        live_app_canon = (clean_text(live_app_name) if live_app_name else "")

        # Validate app
        try:
            app_ok = bool(
                resolve_app_name_smart(rec_app_raw or live_app_name, live_app_name, cur_title)
                or (rec_app_canon and live_app_canon and rec_app_canon == live_app_canon)
            )
        except Exception:
            app_ok = (rec_app_canon and live_app_canon and rec_app_canon == live_app_canon)

        # Validate window (soft/advisory)
        win_ok = _titles_semantic_equal(rec_title_raw or "", cur_title or "")

        # Generic safeguard: tolerate generic/volatile titles
        GENERIC_TITLES = {"new tab", "tab", "untitled", "document", "home", "start page"}
        if app_ok and rec_title_raw and rec_title_raw.strip().lower() in GENERIC_TITLES:
            win_ok = True

        # Trusted context promotion (for Chrome specifically)
        if app_ok and (live_app_canon == "google chrome"):
            recorded_step["_trusted_app_context"] = True

        # Final validation check (relaxed when PID already matched)
        if not app_ok:
            same_pid_active = bool(pid and app_el)
            if same_pid_active:
                if debug:
                    print("⚠️ L1: App name mismatch ignored — PID verified, continuing.")
                    print(f"    Expected app='{rec_app_canon or rec_app_raw}'")
                    print(f"    Found app='{live_app_canon or live_app_name or '(unknown)'}'")
                app_ok = True
            else:
                if debug:
                    print("❌ L1: App mismatch – stopping (no PID match)")
                    print(f"    Expected app='{rec_app_canon or rec_app_raw}'")
                    print(f"    Found app='{live_app_canon or live_app_name or '(unknown)'}'")
                return False

        # Window mismatch is non-blocking
        if not win_ok and debug:
            print("⚠️ L1: Window title mismatch (non-blocking)")
            print("    Expected: window='{}'".format(_strip_dynamic_bits(rec_title_raw or "")))
            print("    Found: window='{}'".format(_strip_dynamic_bits(cur_title or "")))

        # Frontmost check
        is_frontmost = None
        if NSWorkspace and pid:
            ws = NSWorkspace.sharedWorkspace()
            front_app = ws.frontmostApplication()
            if front_app:
                is_frontmost = (front_app.processIdentifier() == pid)

        if debug:
            print("🪪 L1: Identity")
            print(f"📦 app: current={live_app_name or '(unknown)'} | recorded={rec_app_raw or '(unknown)'} → {'✅ pass' if app_ok else '❌ fail'}")
            print(f"🪟 window: current={cur_title} | recorded={rec_title_raw} → {'✅ pass' if win_ok else '❌ fail'}")
            if is_frontmost is not None:
                print(f"🖥️ frontmost: {'✅ yes' if is_frontmost else '❌ no'}")

            # Active screen
            if cur_win_frame:
                screens = collect_screens_info()
                active_screen = pick_screen_for_rect(cur_win_frame, screens)
                if active_screen:
                    scr_name = active_screen.get("name")
                    scr_id = active_screen.get("id")
                    scr_bounds = active_screen.get("bounds_points")
                    print(f"🖥️ active screen: {scr_name or '(unnamed)'} id={scr_id} bounds={scr_bounds}")

        if cur_win_frame and debug:
            print(f"📐 window_frame (live): {_fmt_rect(cur_win_frame)}")

        if is_frontmost is False and NSRunningApplication and pid:
            if debug:
                print("🔄 App is not frontmost. Bringing to front...")
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if app:
                app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                time.sleep(APP_ACTIVATION_DELAY)

                front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
                is_now_front = bool(front_app and front_app.processIdentifier() == pid)
                is_now_active = bool(app.isActive()) if hasattr(app, "isActive") else None
                if is_now_front:
                    if debug: print("✅ App is now frontmost.")
                else:
                    if debug:
                        if is_now_active is True:
                            print("✅ App activation passed")
                        else:
                            print("⏳ App activation requested, verifying again...")
                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    time.sleep(APP_ACTIVATION_DELAY)
                    front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
                    if front_app and front_app.processIdentifier() == pid:
                        if debug: print("✅ App is now frontmost (after retry).")
                    else:
                        if debug: print("⚠️ App activation still not frontmost after retry.")

        # --- L2: Window Projection & Coordinate Mathematics ---
        
        rec_win = recorded_step.get("window_frame")
        if debug:
            print("\n🧪 L2: Window projection")
        
        if cur_win_frame and rec_win:
            dx = float(cur_win_frame['x']) - float(rec_win['x'])
            dy = float(cur_win_frame['y']) - float(rec_win['y'])
            sx = (float(cur_win_frame['w']) / float(rec_win['w'])) if rec_win['w'] else 1.0
            sy = (float(cur_win_frame['h']) / float(rec_win['h'])) if rec_win['h'] else 1.0
            
            within_pos = abs(dx) <= POS_TOL_PX and abs(dy) <= POS_TOL_PX
            within_size = abs(sx - 1.0) <= SIZE_TOL_REL and abs(sy - 1.0) <= SIZE_TOL_REL
            status = "✅ pass" if (within_pos and within_size) else "❤️‍🩹 recover (reprojecting)"
            using = "fractions" if (recorded_step.get("click_frac") is not None) else "Δ+scale"
            
            if debug:
                print(f"📐 current origin: ({cur_win_frame['x']:.1f}, {cur_win_frame['y']:.1f}) | recorded origin: ({rec_win['x']:.1f}, {rec_win['y']:.1f})")
                print(f"📐 current size: ({cur_win_frame['w']:.1f}, {cur_win_frame['h']:.1f}) | recorded size: ({rec_win['w']:.1f}, {rec_win['h']:.1f})")
                print(f"🔀 Δ=(+{dx:.1f}, +{dy:.1f}) 🔎 scale=(×{sx:.3f}, ×{sy:.3f}) using={using} → {status}")
                print("🎯 L2: window transform computed. Target reprojection deferred to L3.")
        else:
            can_frac = (recorded_step.get("click_frac") is not None)
            if cur_win_frame and can_frac:
                if debug:
                    print("🪟 window frame present; fractions recorded, but no recorded window frame → ❤️‍🩹 recover pending (using recorded seed)")
            else:
                if debug:
                    print("🪟 window frame insufficient and no fractions → ❌ fail (no projection path)")


        # L3 - Compute predicted target
        pred = None

        role = recorded_step.get("role")
        best_label = (recorded_step.get("best_label") or "").lower()

        # --- Container override ---
        if role in ["AXGroup", "AXHostingView", "AXSplitGroup", "AXScrollArea"] or "scroll" in best_label:
            raw_click = recorded_step.get("raw_click_point")
            if raw_click and isinstance(raw_click, dict) and "x" in raw_click and "y" in raw_click:
                pred = (raw_click["x"], raw_click["y"])
                if debug:
                    print(f"⚠️ L3: Container using raw_click_point {pred}")
                
                hover(pred)
                click(pred)
                if debug:
                    print(f"🎯 L3: Container direct click at {pred}")
                return True

        # --- Normal reprojection path ---
        elif cur_win_frame and rec_win:
            rec_frame = recorded_step.get("frame")
            if rec_frame and all(k in rec_frame for k in ("x","y","w","h")):
                elem_center = (float(rec_frame["x"]) + float(rec_frame["w"])/2.0,
                               float(rec_frame["y"]) + float(rec_frame["h"])/2.0)
                pred = reproject_point_from_windows(elem_center, rec_win, cur_win_frame)
                if debug:
                    print(f"🎯 reprojected from element frame → {_fmt_pt(pred)}")
            elif recorded_step.get("activation_point"):
                ap = recorded_step["activation_point"]
                if "x" in ap and "y" in ap:
                    pred = reproject_point_from_windows((float(ap["x"]), float(ap["y"])), rec_win, cur_win_frame)
                    if debug:
                        print(f"🎯 reprojected from activation_point → {_fmt_pt(pred)}")
            elif recorded_step.get("click_frac"):
                frac = recorded_step["click_frac"]
                if "fx" in frac and "fy" in frac:
                    fx, fy = float(frac["fx"]), float(frac["fy"])
                    pred = (cur_win_frame["x"] + fx * cur_win_frame["w"],
                            cur_win_frame["y"] + fy * cur_win_frame["h"])
                    if debug:
                        print(f"🎯 reprojected from fractions → {_fmt_pt(pred)}")
            elif recorded_step.get("click_point"):
                cp = recorded_step["click_point"]
                if "x" in cp and "y" in cp:
                    pred = reproject_point_from_windows((float(cp['x']), float(cp['y'])), rec_win, cur_win_frame)
                    if debug:
                        print(f"🎯 reprojected from click_point → {_fmt_pt(pred)}")

        chosen = pred or (center_of(cur_win_frame) if cur_win_frame else (100, 100))
        if debug:
            print(f"🎯 L3: final chosen point {chosen}")

        # Preflight hit 
        el, live = hit(chosen)
        if el is None or (live.get("AXRole") in ("AXWindow","AXGroup") and not has_axpress(live)):
            # Focus safeguards
            front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
            if app_el and front_app and front_app.processIdentifier() != pid:
                if debug:
                    print("🔄 Bringing app to front…")
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                if app:
                    try:
                        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                        time.sleep(APP_ACTIVATION_DELAY)
                        # Verify frontmost/active
                        front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
                        is_now_front = bool(front_app and front_app.processIdentifier() == pid)
                        is_now_active = bool(app.isActive()) if hasattr(app, "isActive") else None
                        if not is_now_front:
                            if debug:
                                if is_now_active is True:
                                    print("⚠️ App activation passed retrying…")
                                else:
                                    print("⏳ App activation requested, verifying again…")
                            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                            time.sleep(APP_ACTIVATION_DELAY)
                            front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
                            if front_app and front_app.processIdentifier() == pid:
                                if debug:
                                    print("✅ App is now frontmost (after retry).")
                            else:
                                if debug:
                                    print("⚠️ App activation still not frontmost after retry.")
                    except Exception as e:
                        print(f"[ERROR] App activation error: {e}")

            # Retry hit-test
            el, live = hit(chosen)
            if el is None:
                print(f"❌ Preflight retry failed at {_fmt_pt(chosen)}")
                return False
        
        is_trusted = recorded_step.get("_trusted_app_context", False)
        mism = compare_signature(recorded_step, live, trusted_context=is_trusted)
        context_mode = "trusted" if is_trusted else "strict"
        if debug:
            print(f"[context] Validation mode: {context_mode}")
        if debug:
            print(f"\n🧪 L3: Preflight")
            print(f"🎯 chosen (preflight) point: {_fmt_pt(chosen)} mismatches={len(mism)}")

        # L3 Perfect Match Bypass - Skip L4-L7 if preflight perfect
        if isinstance(mism, dict) and len(mism) == 0:
            if debug:
                print("🦋 L3: Perfect preflight match → skipping L4-L7 pipeline")
            if do_click:
                if debug:
                    print(f"✅ L3: Direct execution → {_fmt_pt(chosen)}")
                hover(chosen)
                click(chosen)
                return True
            return True

        # Show recorded vs live labels
        rec_label = recorded_best_label(recorded_step) or None
        print(f"Recorded AX element: {rec_label} | Live AX element: {live.get('best_label')} | mismatches={len(mism)}")

        # L4 - Refinement pipeline
        need_micro = bool(mism) or (not has_axpress(live)) or (live.get('AXRole') in ('AXGroup', getattr(Quartz, 'kAXGroupRole', 'AXGroup')))
        if need_micro:
            chosen, el, mism, micro_src = micro_refine_target(chosen, el, recorded_step, debug=debug)
            live = element_info(el) if el else live
            if debug:
                print(f"[MICRO] source={micro_src} final_point={chosen} mismatches={len(mism) if isinstance(mism, dict) else 'n/a'}")

        # Full tree resolve if still mismatching
        if bool(mism):
            root = nearest_window(el) or win_el or el
            best_el, best_info, best_score, visited = ax_full_tree_resolve(recorded_step, root)
            if best_el is not None and best_score >= 0.55:
                f2, _ = decode_frame(best_el, element_only=True)
                ap2 = get_activation_point(best_el)
                
                # Validate activation point - reject screen edge coordinates
                if ap2 and f2:
                    frame_center_x = f2["x"] + f2["w"]/2
                    frame_center_y = f2["y"] + f2["h"]/2
                    
                    # Reject if at screen edges or too far from element
                    if (ap2[0] <= 1.0 or ap2[1] >= 1070 or 
                        abs(ap2[0] - frame_center_x) > f2["w"] * 3 or
                        abs(ap2[1] - frame_center_y) > f2["h"] * 3):
                        # Use frame center instead
                        chosen = center_of(f2) if f2 else chosen
                        hint = 'frame_center'
                    else:
                        chosen = ap2
                        hint = 'activation_point'
                else:
                    chosen = center_of(f2) if f2 else chosen
                    hint = 'frame_center' if f2 else 'fallback'
                
                el = best_el
                live = best_info
                is_trusted = recorded_step.get("_trusted_app_context", False)
                mism = compare_signature(recorded_step, live, trusted_context=is_trusted)
                if debug:
                    print(f"[AX_RESOLVE] visited={visited} best_score={best_score:.2f} hint={hint} point={chosen}")

        # Build candidates from current element
        f_el, _ = decode_frame(el, element_only=True)
        ap = get_activation_point(el)
        candidates = []
        if ap:
            candidates.append((ap, "activation_point"))
        if f_el:
            candidates.append((center_of(f_el), "frame_center"))
        candidates.append((chosen, "validated_point"))

        # Skip last-mile if perfect preflight
        if isinstance(mism, dict) and len(mism) == 0:
            if debug:
                print("🦋 L4: Evolution → skipped (perfect preflight).")
            final_pt = chosen
            final_src = "preflight"
        else:
            if debug:
                print(f"🧬 L4: candidates={[(s, _fmt_pt(p)) for p,s in candidates]}")
            
            # Evaluate candidates
            best_candidate = None
            best_mismatch_count = None
            best_distance = None
            final_pt = None
            final_src = None
            chosen_el = None
            found_perfect = False
            
            for pt, srcname in candidates:
                el2, live2 = hit(pt)
                if el2 is None:
                    if debug and False:  # verbose candidate trace disabled
                        print(f"[L4] Candidate {srcname} at {_fmt_pt(pt)}: hit failed, skipping.")
                    continue
                
                # Focus safeguard for containers
                info2 = element_info(el2)
                if (info2.get("AXRole") in ("AXWindow", "AXGroup") and not has_axpress(info2)):
                    if debug and False:  # verbose candidate trace disabled
                        print(f"[L4] Candidate {srcname} at {_fmt_pt(pt)}: container/no AXPress, ensuring focus.")
                    front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
                    if app_el and front_app and front_app.processIdentifier() != pid:
                        if debug:
                            print("[L4] Bringing app to front for focus safeguard…")
                        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                        if app:
                            try:
                                app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                                time.sleep(APP_ACTIVATION_DELAY)
                                # Verify frontmost/active
                                front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
                                is_now_front = bool(front_app and front_app.processIdentifier() == pid)
                                is_now_active = bool(app.isActive()) if hasattr(app, "isActive") else None
                                if not is_now_front:
                                    if debug:
                                        if is_now_active is True:
                                            print("⚠️ App activation passed retrying…")
                                        else:
                                            print("⏳ App activation requested, verifying again…")
                                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                                    time.sleep(APP_ACTIVATION_DELAY)
                                    front_app = NSWorkspace.sharedWorkspace().frontmostApplication() if NSWorkspace else None
                                    if front_app and front_app.processIdentifier() == pid:
                                        if debug:
                                            print("✅ App is now frontmost (after retry).")
                                    else:
                                        if debug:
                                            print("⚠️ App activation still not frontmost after retry.")
                            except Exception as e:
                                print(f"[ERROR] App activation error: {e}")
                    
                    # Retry after focus
                    el2, live2 = hit(pt)
                    if el2 is None:
                        if debug and False:  # verbose candidate trace disabled
                            print(f"[L4] Candidate {srcname} at {_fmt_pt(pt)}: focus safeguard failed, skipping.")
                        continue
                    info2 = element_info(el2)
                
                is_trusted = recorded_step.get("_trusted_app_context", False)
                mism2 = compare_signature(recorded_step, info2, trusted_context=is_trusted)
                mismatch_count = len(mism2)
                dist_to_seed = _dist(pt, chosen)
                
                if debug and False:  # verbose candidate trace disabled
                    print(f"[L4] Candidate {srcname} at {_fmt_pt(pt)}: mismatches={mismatch_count} dist={dist_to_seed:.2f}")
                
                if mismatch_count == 0:
                    if debug:
                        print(f"[L4] Candidate {srcname} at {_fmt_pt(pt)}: accepted (0 mismatches).")
                    final_pt, final_src, chosen_el = pt, srcname, el2
                    found_perfect = True
                    break
                
                if (best_candidate is None or
                    mismatch_count < best_mismatch_count or
                    (mismatch_count == best_mismatch_count and dist_to_seed < best_distance)):
                    best_candidate = (pt, srcname, el2, mism2)
                    best_mismatch_count = mismatch_count
                    best_distance = dist_to_seed
            
            # Use best candidate if no perfect match
            if not found_perfect:
                if best_candidate is not None:
                    final_pt, final_src, chosen_el, best_mism = best_candidate
                    if debug:
                        print(f"[L4] Best candidate chosen: {final_src} at {_fmt_pt(final_pt)} with {len(best_mism)} mismatches.")
                else:
                    if debug:
                        print("[L4] No candidate hit succeeded, falling back to neighbor snap or fallback validated.")
            
            # Tight neighbor snap if needed
            if (final_pt is None or 
                (chosen_el and len(compare_signature(recorded_step, element_info(chosen_el))) != 0)):
                seed_for_snap = ap or (center_of(f_el) if f_el else chosen)
                n_pt, n_el, n_m = neighbor_scan(seed_for_snap, recorded_step, 
                                              radius=TIGHT_NEIGHBOR_RADIUS, step=TIGHT_NEIGHBOR_STEP)
                if n_el is not None and isinstance(n_m, dict) and len(n_m) == 0:
                    if debug:
                        print(f"[L4] Neighbor snap accepted at {_fmt_pt(n_pt)}.")
                    final_pt, final_src, chosen_el = n_pt, "neighbor_snap", n_el
            
            # Fallback to last candidate
            if final_pt is None:
                final_pt, final_src, chosen_el = candidates[-1][0], "fallback_validated", el
                if debug:
                    print(f"[L4] Fallback to validated point at {_fmt_pt(final_pt)}.")
            
            el = chosen_el or el

        # L4b – Strict full-window adaptation if we still mismatch
        if isinstance(mism, dict) and len(mism) != 0:
            if debug:
                print("\n[ADAPT] L4b: entering strict full-window search (no scope).")
            adapt = self._adapt_full_window(
                recorded_step,
                app_el=app_el,
                win_el=win_el,
                pid=pid,
                cur_win_frame=cur_win_frame,
                debug=debug
            )
            if adapt.get("executed"):
                # Action was performed via AXPress; we can finish successfully.
                return True
            if adapt.get("el") is not None:
                el = adapt["el"]
                live = adapt["info"]
                if adapt.get("point") is not None:
                    final_pt = adapt["point"]
                # Recompute mismatches based on adapted element
                is_trusted = recorded_step.get("_trusted_app_context", False)
                mism2 = compare_signature(recorded_step, live, trusted_context=is_trusted)
                if debug:
                    print(f"[ADAPT] chosen via full-window search: mismatches={len(mism2)}")
                mism = mism2

        # L5 - Hit-Test (hover-over check)
        if do_hover or not do_click:
            if debug:
                print("\n🪄 L5: Hover preflight")
            hover(final_pt, debug=True)
            elh, liveh = hit(final_pt)
            if elh is None:
                print("❌ hover re-hit failed")
                return False
            hm = compare_signature(recorded_step, liveh)
            if debug:
                print(f"🔎 hover match mismatches={len(hm)}")
            el = elh
            mism = hm

        # L6 - Last recovery try with click safeguard
        if do_click:
            if safe_click and len(mism) != 0:
                if should_allow_container_mismatch(recorded_step, live, len(mism)):
                    if debug:
                        print(f"🛡️ L6: Container exception – allowing {len(mism)} mismatch for safe element")
                else:
                    print("⛔ L6: Safe-click enabled – preflight mismatches remain. Skipping click.")
                    return False
            if debug:
                print(f"✅ L6: Click {final_src} → {_fmt_pt(final_pt)}")
            click(final_pt)
            return True

        return len(mism) == 0
        
    # L7 - Escalation handling
    def execute_step_with_retries(self, recorded_step, tries=3, **kwargs):
        """Execute step with L7 escalation loop (A: OCR + Computer Vision or B: Multimodal LLM )."""
        ok = False
        for attempt in range(1, tries+1):
            print(f"\n====== Attempt {attempt}/{tries} ======")
            ok = self.execute_step(recorded_step, **kwargs)
            if ok:
                break
            time.sleep(0.15)
        
        if not ok and tries > 1:
            print("📈 L7: Escalation exhausted. Request Human Revision.")
        
        return ok
        
    def load_recorded_step(self, path, index=None):
        """Load recorded step from JSON file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(path) as f:
            data = json.load(f)
        
        items = data if isinstance(data, list) else [data]
        idx = index if index is not None else len(items)-1
        
        if not (0 <= idx < len(items)):
            raise IndexError(f"Index {idx} out of range (0..{len(items)-1})")
        
        return items[idx], len(items), idx
