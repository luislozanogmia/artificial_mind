# AX Executor — macOS Accessibility Automation Engine  

**Part of the [Artificial Mind](https://github.com/luislozanogmia/artificial_mind) framework**

The execution layer that turns AI reasoning into deterministic, safe macOS automation.

---

## 🧩 Artificial Mind – Layer Overview

| Layer | Name | Purpose |
|:------|:------|:---------|
| **01** | **Perception Layer** | Captures input from users and systems, enabling the architecture to sense and interpret context. |
| **02** | **Grounding Layer** | Maintains real-time state and execution history, giving the system a stable foundation. |
| **03** | **Validation Layer** | Filters and rejects invalid outputs before generation, ensuring structural and semantic coherence. |
| **04** | **System Identity Layer** | Preserves consistent behavior across sessions, users, and model swaps through rule-based control. |
| **05** | **Expression Layer** | Translates validated intent into language, enabling reasoning continuity and clear communication. |
| **06** | **Execution Layer** ← **You Are Here** | Delivers deterministic, reliable automation that acts on the world with safety and control. |

---

## 🤔 What Is AX Executor?

**AX Executor is Layer 06 (Execution) from the Artificial Mind framework**, released as a standalone open-source tool.

It implements a research-grade **L0–L7 validation pipeline** for safe, reproducible macOS UI automation. Where other automation tools break on window resizes or app updates, AX Executor adapts through structural validation and intelligent refinement.

**Why standalone?** This layer is useful beyond the full Artificial Mind system—for RPA tools, testing frameworks, agent orchestrators (n8n, LangChain), and any system that needs reliable macOS automation.

> **Note:** The complete 6-layer Artificial Mind framework (including reasoning, memory, and validation layers) will be available separately (at the time of this writing only Execution is available). 

---

## 🧩 Components Included

| File | Purpose |
|------|----------|
| `ax_executor.py`     | Core Accessibility engine with full L0-L7 pipeline, inspection API, and execution logic. |
| `mac_executor.py`    | System-level executor for macOS file operations (open, copy, move, create) without GUI interaction. |
| `test_ax_inspector.py` | Interactive click inspector—record UI element signatures for automation. |
| `test_ax_execute.py` | Execution CLI—replay recorded steps with validation and diagnostics. |
| `requirements.txt` | Dependencies (PyObjC, Quartz, AppKit). |
| `INSTALL.md` | Setup guide and macOS permission configuration. |

---

> **Note:** A Windows-compatible executor is in development and will extend the same L0–L7 pipeline using the Windows UI Automation (UIA) API.

## ⚙️ L0–L7 Pipeline Architecture

AX Executor implements a **7-layer validation pipeline** that makes automation robust:

| Layer | Purpose | Core Function |
|:------|:---------|:--------------|
| **L0** | **Fresh State** | Clear stale context; ensure accessibility trust. |
| **L1** | **Identity Validation** | Match app name + window title semantically. |
| **L2** | **Window Projection** | Reproject recorded coordinates across resizes. |
| **L3** | **Target Prediction** | Estimate element location using geometry + fractions. |
| **L4** | **Refinement Pipeline** | Micro-refine via children, neighbors, and tree search. |
| **L5** | **Hit-Test Confirmation** | Hover-validate element before execution. |
| **L6** | **Safeguarded Execution** | Execute with AXPress or synthetic click. |
| **L7** | **Escalation** | Retry loop with OCR/visual fallbacks (future). |

Each layer builds on the previous with intelligent fallbacks at every stage.

---

## 🧩 Core Features

- **Full AX Schema (70+ attributes):** Stable across macOS 12–15.  
- **Deterministic Validation:** Zero clicks without structural match.  
- **Window-Adaptive:** Survives resizes, moves, and multi-monitor setups.  
- **Semantic Labeling:** Combines title + role + parent chain for robust matching.  
- **Safe Fallbacks:** Activation Point → Frame Center → Neighbor Scan → Tree Search.  
- **Multi-Display Ready:** HiDPI-aware with screen-specific coordinate mapping.  

> **Research Note:** `ax_executor.py` implements a shared AX element schema aimed at making macOS automation reproducible and easier to integrate into other agent frameworks.


---

## 🚀 Quick Start

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/luislozanogmia/artificial_mind.git
cd artificial_mind/layer_06_execution

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**See [INSTALL.md](INSTALL.md) for detailed setup and permissions.**

---

### 2. Enable macOS Permissions

**Required:** Accessibility + Input Monitoring permissions.
```bash
# Quick access to System Settings
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

1. **System Settings → Privacy & Security → Accessibility**  
   Add Terminal (or your IDE), toggle OFF then ON
2. **System Settings → Privacy & Security → Input Monitoring**  
   Add Terminal (or your IDE), toggle OFF then ON
3. **Restart Terminal**

---

### 3. Record UI Interactions
```bash
python test_ax_inspector.py
```

Click on any UI elements. Each click records comprehensive AX data to `inspector.json`.

**Example output:**
```
AXButton • Send • Mail
{
  "role": "AXButton",
  "best_label": "send",
  "app_name": "Mail",
  "click_point": {"x": 850.0, "y": 120.0},
  "window_frame": {"x": 100, "y": 50, "w": 1200, "h": 800}
  ...
}
[BUFFERED] Click #0 (session total: 1)
```

Press **Ctrl+C** to save and exit.

---

### 4. Replay with Validation
```bash
# Dry run (validation only, no click)
python test_ax_execute.py --hover --index 0

# Safe execution (click only if validation passes)
python test_ax_execute.py --click-if-match

# Force execution with retries
python test_ax_execute.py --click --escalate

# Show detailed L0-L7 diagnostics
python test_ax_execute.py --hover --diag
```

**Example output:**
```
🎯 Using element #0: AXButton • Send
🧼 L0: Cold start – cleared prior state
📦 L1: app=Mail pid=1234 ✅ pass
🪟 L2: Δ=(+0.0, +0.0) scale=(×1.000, ×1.000)
🎯 L3: predicted → (850.0, 120.0)
✅ Execution successful!
```

---

## 📚 Learn More
- **[Artificial Mind White Paper](https://github.com/luislozanogmia/artificial_mind)** – Full 6-layer architecture overview

---

## 🤝 Contributing

AX Executor is research-grade software. Contributions welcome for:

- Additional macOS version support (10.14–15.x)
- Enhanced element detection strategies
- OCR/visual fallback integration (L7 Vision)
- Cross-app compatibility testing

See [CONTRIBUTING.md](#) for guidelines.

---

## 📜 License

**MIT License** with attribution requirement.

Copyright © 2025 Luis Lozano

Permission is hereby granted to use, copy, modify, and distribute this software with proper attribution to the Artificial Mind project.

See [LICENSE](LICENSE) for full terms.

---

## 🙏 Acknowledgments

Built as part of the **Artificial Mind** research project—a 6-layer framework for building reliable, interpretable AI agents.

- **Research Team:** [Luis Lozano](https://github.com/luislozanogmia)
- **Framework:** [Artificial Mind](https://github.com/luislozanogmia/artificial_mind)

---

**Repository:** https://github.com/luislozanogmia/artificial_mind/tree/main/layer_06_execution  
