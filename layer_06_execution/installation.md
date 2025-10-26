# Installation Guide

## Prerequisites

- **macOS 10.14+** (Mojave or newer)
- **Python 3.9+** (check with `python3 --version`)
- **Xcode Command Line Tools** (run `xcode-select --install` if needed)
- **Git** (check with `git --version`)

## Installation

### 1. Clone the Repository
```bash
# Clone from GitHub
git clone https://github.com/luislozanogmia/artificial_mind.git

# Navigate to the AX Executor directory
cd artificial_mind/layer_06_execution
```

### 2. Create Virtual Environment
```bash
# Create isolated Python environment
python3 -m venv .venv

# Activate the environment
source .venv/bin/activate

# Verify activation (you should see (.venv) in your prompt)
```

### 3. Install Dependencies
```bash
# Upgrade pip to latest version
pip install --upgrade pip

# Install required packages
pip install -r requirements.txt

# This will install:
# - PyObjC frameworks (macOS automation)
# - pyperclip (clipboard management)
# - pyautogui (keyboard fallback)
```

**Expected output:**
```
Successfully installed pyobjc-core-10.x pyobjc-framework-Cocoa-10.x ...
```

### 4. Grant macOS Permissions

**Critical:** AX Executor requires two system permissions to function.

#### Step 1: Open System Settings
```bash
# Quick way to open System Settings
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

Or manually: **System Settings → Privacy & Security**

#### Step 2: Grant Accessibility Permission

1. Scroll down to **Accessibility**
2. Click the **(+)** button
3. Add **Terminal** (or your Python IDE: VS Code, PyCharm, etc.)
4. **Toggle OFF then ON** to refresh permission
5. Click **Done**

#### Step 3: Grant Input Monitoring Permission

1. In the same Privacy & Security section, select **Input Monitoring**
2. Add **Terminal** (or your Python IDE)
3. **Toggle OFF then ON** to refresh permission
4. Click **Done**

**Important:** You must **restart your Terminal** after granting permissions.

### 5. Verify Installation
```bash
# Close and reopen Terminal (to apply permissions)
# Navigate back to the project
cd ~/artificial_mind/layer_06_execution
source .venv/bin/activate

# Test the installation
python3 -c "from ax_executor import AXEngine; print('✅ Installation successful!')"
```

**Expected output:**
```
✅ Installation successful!
```

## Quick Start

### Record UI Interactions
```bash
python test_ax_inspector.py
```

**What to do:**
1. The inspector starts running
2. Click on any UI elements you want to record
3. Each click prints detailed accessibility information
4. Press **Ctrl+C** when done
5. Data is saved to `inspector.json`

**Example output:**
```
AX click-inspector running. Click anywhere to print element info. Ctrl+C to exit.

AXButton • Send • Mail
{
  "role": "AXButton",
  "best_label": "send",
  "app_name": "Mail",
  ...
}
[BUFFERED] Click #0 (session total: 1)
```

### Replay Recorded Interactions
```bash
python test_ax_execute.py
```

**Example output:**
```
🎯 Using element #0 of 1: AXButton • Send
🧼 L0: Cold start – cleared prior state
📦 L1: app=Mail pid=1234 | window_title=New Message
...
✅ Execution successful!
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'objc'"

**Cause:** Virtual environment not activated or PyObjC not installed.

**Solution:**
```bash
source .venv/bin/activate
pip install --upgrade pyobjc-core pyobjc-framework-Cocoa
```

---

### "AXIsProcessTrusted returns False"

**Cause:** Accessibility permission not granted or Terminal not restarted.

**Solution:**
1. Open **System Settings → Privacy & Security → Accessibility**
2. Find **Terminal** in the list
3. Toggle it **OFF then ON**
4. **Quit Terminal completely** (⌘Q)
5. Reopen Terminal and try again

---

### "Failed to create event tap"

**Cause:** Input Monitoring permission not granted.

**Solution:**
1. Open **System Settings → Privacy & Security → Input Monitoring**
2. Add **Terminal** using the **(+)** button
3. Toggle it **OFF then ON**
4. Restart Terminal
5. Try: `python test_ax_inspector.py` again

---

### Inspector records but clicks don't work in execute

**Cause:** Window or app changed since recording.

**Solution:**
```bash
# Use diagnostics to see what's different
python test_ax_execute.py --hover --diag --index 0

# Look for mismatches in:
# - App name (should match recorded app)
# - Window geometry (may need resize tolerance)
# - Element labels (may have changed)
```

---

### "Permission denied" when creating .venv

**Cause:** Insufficient permissions in project directory.

**Solution:**
```bash
# Clone to your home directory instead
cd ~
git clone https://github.com/luislozanogmia/artificial_mind.git
cd artificial_mind/layer_06_execution
python3 -m venv .venv
```

---

## Updating

To get the latest version:
```bash
cd ~/artificial_mind/layer_06_execution

# Deactivate virtual environment if active
deactivate

# Pull latest changes
git pull origin main

# Reactivate and update dependencies
source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

## Uninstalling
```bash
# Remove virtual environment
cd ~/artificial_mind/layer_06_execution
rm -rf .venv

# Remove repository (if desired)
cd ~
rm -rf artificial_mind
```

## Support

- **Repository:** https://github.com/luislozanogmia/artificial_mind
- **Issues:** https://github.com/luislozanogmia/artificial_mind/issues
- **Documentation:** See `README.md` for architecture details

## System Requirements Summary

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| macOS | 10.14 (Mojave) | 12.0+ (Monterey) |
| Python | 3.9 | 3.11+ |
| RAM | 4 GB | 8 GB+ |
| Disk Space | 500 MB | 1 GB |
| Permissions | Accessibility + Input Monitoring | Required |

---

**Next Steps:** See `README.md` for architecture overview and usage examples.