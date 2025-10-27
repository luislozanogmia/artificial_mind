import os
import time
from ax_executor import AXEngine

if __name__ == "__main__":
    print("🧠 Opening TextEdit for typing test...")
    # Ensure a new instance opens with a blank doc
    os.system("open -n -a TextEdit")
    time.sleep(2)

    # Force creation of a new document window via AppleScript
    os.system(
        """osascript -e 'tell application "TextEdit"
            activate
            if not (exists window 1) then
                make new document
            else
                make new document
            end if
        end tell'"""
    )

    time.sleep(2)

    engine = AXEngine()
    engine.ensure_trust()

    print("⌨️ Starting keyboard typing test in TextEdit...")
    success = engine._execute_type_action("Hello World from AX Executor", debug=True)

    if success:
        print("✅ Typing test completed successfully in TextEdit.")
    else:
        print("❌ Typing test failed. Check accessibility permissions or app focus.")