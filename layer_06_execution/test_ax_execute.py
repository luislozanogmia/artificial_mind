#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AX Executor - Research Preview CLI Wrapper
==========================================

MRE L0-L7 pipeline executor for recorded accessibility interactions.
Executes automation steps with structural validation and refinement.

Usage:
    python test_ax_execute.py [options]
    
Options:
    --index N          Use element N from inspector.json (default: last)
    --click, -c        Perform actual click
    --click-if-match   Click only if preflight validation passes
    --diag             Show detailed L1/L2/L3 diagnostics
    --escalate         Retry up to 3 times (L7 Vision)

Examples:
    python test_ax_execute.py --index 0
    python test_ax_execute.py --click-if-match --escalate
    python test_ax_execute.py --click --diag

Part of the AX Executor research preview - experimental automation technology.
Implements Mirror-Reflection Engine (MRE) for robust automation.
"""

import sys
import os
from ax_executor import AXEngine

class AXExecutorCLI:
    """CLI wrapper for AX execution using unified engine."""
    
    def __init__(self):
        self.engine = AXEngine()
        self.inspector_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inspector.json")
    
    def parse_args(self, argv):
        """Parse command line arguments."""
        args = {
            'index': None,
            'do_click': False,
            'safe_click': False,
            'diag': False,
            'escalate': False,
            'debug': True  # Always on for CLI
        }
        
        i = 0
        while i < len(argv):
            arg = argv[i]
            
            if arg == '--index' and i + 1 < len(argv):
                try:
                    args['index'] = int(argv[i + 1])
                    i += 1
                except ValueError:
                    print(f"Error: Invalid index '{argv[i + 1]}'")
                    sys.exit(1)
            elif arg in ('--click', '-c'):
                args['do_click'] = True
            elif arg in ('--click-if-match', '--safe-click'):
                args['do_click'] = True
                args['safe_click'] = True
            elif arg in ('--diag', '--diagnostics'):
                args['diag'] = True
            elif arg == '--escalate':
                args['escalate'] = True
            elif arg.startswith('--'):
                print(f"Warning: Unknown option '{arg}' ignored")
            
            i += 1
        
        return args
    
    def run(self, argv):
        """Main execution logic."""
        args = self.parse_args(argv)
        
        # Load recorded step
        try:
            rec, total, sel = self.engine.load_recorded_step(self.inspector_path, args['index'])
            print(f"🎯 Using element #{sel} of {total}: {rec.get('role','?')} • {rec.get('best_label') or rec.get('title') or 'No label'}")
            if args['diag']:
                print(f"[INFO] schema version: {rec.get('schema_version','?')}")
        except FileNotFoundError:
            print(f"Error: inspector.json not found at {self.inspector_path}")
            print("Run test_ax_inspector.py first to record element interactions.")
            sys.exit(1)
        except (IndexError, KeyError) as e:
            print(f"Error loading recorded step: {e}")
            sys.exit(1)

        # Execute with appropriate method
        if args['escalate']:
            tries = 3
            success = False
            for attempt in range(1, tries+1):
                print(f"[RETRY] Attempt {attempt}/{tries}")
                success = self.engine.execute_step(
                    rec,
                    do_click=args['do_click'],
                    safe_click=args['safe_click'],
                    debug=args['debug'],
                    diag=args['diag']
                )
                if success:
                    break
        else:
            success = self.engine.execute_step(
                rec,
                do_click=args['do_click'],
                safe_click=args['safe_click'],
                debug=args['debug'],
                diag=args['diag']
            )
        
        # Report result
        if success:
            print(f"\n✅ Execution successful!")
        else:
            print(f"\n❌ Execution failed - mismatches detected")
            if not args['do_click']:
                print("💡 Try --click or --click-if-match to attempt execution")
        
        return success

def print_usage():
    """Print usage information."""
    print("""
AX Executor - MRE L0-L7 Pipeline

Usage: python test_ax_execute.py [options]

Options:
  --index N           Use element N from inspector.json (default: last)
  --click, -c         Perform actual click
  --click-if-match    Click only if validation passes (safe mode)
  --diag              Show detailed L1/L2/L3 diagnostics
  --escalate          Retry up to 3 times (L7 Vision)

Examples:
  python test_ax_execute.py --index 0
  python test_ax_execute.py --click-if-match --escalate
  python test_ax_execute.py --click --diag

Note: Run test_ax_inspector.py first to record interactions.
""")

def interactive_mode(executor):
    """Interactive menu for element/action selection."""
    print("\n⚙️ AX Executor Interactive Mode")
    print("==================================\n")
    import json
    try:
        with open(executor.inspector_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            elements = data
        else:
            elements = data.get("elements") or data
        if not isinstance(elements, list):
            raise ValueError("Invalid inspector.json format: 'elements' not a list")
    except FileNotFoundError:
        print(f"Error: inspector.json not found at {executor.inspector_path}")
        print("Run test_ax_inspector.py first to record element interactions.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Could not load or parse inspector.json: {e}")
        print("Run test_ax_inspector.py first to record element interactions.")
        sys.exit(1)

    if not elements:
        print("No elements found in inspector.json. Run test_ax_inspector.py first.")
        sys.exit(1)

    print("Available Elements:")
    for idx, el in enumerate(elements):
        role = el.get("role", "?")
        label = el.get("best_label") or el.get("title") or "No label"
        print(f"  [{idx}]  {role:12}  {label}")
    print()
    default_idx = len(elements) - 1
    try:
        sel = input(f"Select element index [default: {default_idx}]: ").strip()
        if sel == "":
            idx = default_idx
        else:
            idx = int(sel)
        if not (0 <= idx < len(elements)):
            print(f"Invalid index {idx}.")
            sys.exit(1)
    except ValueError:
        print("Invalid input. Please enter a valid index number.")
        sys.exit(1)

    print("\nActions:")
    print("  1. click")
    print("  2. click-if-match")
    action_map = {"1": "click", "2": "click-if-match"}
    action = input("Select action [1-click, 2-click-if-match] [default: click]: ").strip()
    if action == "":
        action = "1"
    if action not in action_map:
        print("Invalid action selection.")
        sys.exit(1)
    act = action_map[action]

    # Compose args for executor.run()
    argv = ["--index", str(idx)]
    if act == "click":
        argv.append("--click")
    elif act == "click-if-match":
        argv.append("--click-if-match")
    want_diag = input("Show detailed diagnostics? [y/N]: ").strip().lower()
    if want_diag == "y":
        argv.append("--diag")
    print("\n[INFO] Executing selected action...\n")
    executor.run(argv)


def main():
    """Entry point."""
    argv = sys.argv[1:]
    if '--help' in argv or '-h' in argv:
        print_usage()
        sys.exit(0)
    if not argv:
        executor = AXExecutorCLI()
        interactive_mode(executor)
        sys.exit(0)
    executor = AXExecutorCLI()
    try:
        success = executor.run(argv)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Execution cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()