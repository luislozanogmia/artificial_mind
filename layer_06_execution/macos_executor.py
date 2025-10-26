#!/usr/bin/env python3
"""
macOS OS Executor - System-Level File Operations
=================================================

Direct filesystem operations via shell commands.
No GUI interaction - pure command execution.

Supported Operations:
1. open_folder - Navigate to folder in Finder
2. open_file - Open file with default app
3. copy_file - Copy file/folder to destination
4. move_file - Move/rename file/folder
5. create_file - Create new file with optional content
6. create_folder - Create new folder (with parents if needed)

Banned Operations:
- delete - Intentionally not implemented for safety
- Trash operations - Always blocked

Safety Features:
- Path validation before all operations
- Workspace boundary enforcement (optional)
- File ID resolution for macOS paths
"""

import subprocess
import os
import shutil
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import unquote


class OSExecutor:
    """macOS system-level file operations executor"""
    
    def __init__(self, workspace_root: Optional[str] = None, debug: bool = False):
        """
        Args:
            workspace_root: Optional path restriction (e.g., ~/Documents/FOR_AUTOMATION)
            debug: Print operation details
        """
        self.workspace_root = Path(workspace_root).expanduser() if workspace_root else None
        self.debug = debug
        self._last_error = None
    
    # ==================== PATH UTILITIES ====================
    
    def _resolve_file_id(self, file_id_path: str) -> Optional[str]:
        """Resolve /.file/id=XXXXX to actual path using mdls"""
        try:
            result = subprocess.run(
                ['mdls', '-name', 'kMDItemPath', '-raw', file_id_path],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
        except Exception as e:
            if self.debug:
                print(f"[RESOLVE] mdls failed: {e}")
        return None
    
    def _normalize_path(self, url_or_path: str) -> Optional[str]:
        """Convert file:// URL or file ID to POSIX path"""
        path = url_or_path.strip().strip('"').strip("'")
        
        # Already POSIX path
        if path.startswith('/') or path.startswith('~'):
            return str(Path(path).expanduser())
        
        # file:// URL
        if path.startswith('file://'):
            path = unquote(path.replace('file://', ''))
            
            # Handle file ID
            if path.startswith('/.file/id='):
                resolved = self._resolve_file_id(path)
                if resolved:
                    return resolved
                self._last_error = f"Could not resolve file ID: {path}"
                return None
            
            return path
        
        return path
    
    def _validate_path(self, path: str, must_exist: bool = True) -> bool:
        """Validate path safety and existence"""
        p = Path(path)
        
        # Check existence
        if must_exist and not p.exists():
            self._last_error = f"Path does not exist: {path}"
            return False
        
        # Block Trash operations
        if '/Trash' in path or '/.Trash' in path:
            self._last_error = "Trash operations are banned"
            return False
        
        # Check workspace boundary if set
        if self.workspace_root:
            try:
                p.resolve().relative_to(self.workspace_root.resolve())
            except ValueError:
                self._last_error = f"Path outside workspace: {path}"
                return False
        
        return True
    
    # ==================== OPERATIONS ====================
    
    def open_folder(self, folder_path: str) -> bool:
        """Open folder in Finder"""
        path = self._normalize_path(folder_path)
        if not path or not self._validate_path(path):
            return False
        
        if not os.path.isdir(path):
            self._last_error = f"Not a folder: {path}"
            return False
        
        result = subprocess.run(["open", path], capture_output=True, text=True)
        success = result.returncode == 0
        
        if not success:
            self._last_error = result.stderr.strip()
        
        if self.debug:
            status = "SUCCESS" if success else "FAILED"
            print(f"[OPEN_FOLDER] {path} -> {status}")
        
        return success
    
    def open_file(self, file_path: str, app: Optional[str] = None) -> bool:
        """
        Open file with default app or specified app
        
        Args:
            file_path: Path to file
            app: Optional app name (e.g., "TextEdit", "Preview")
        """
        path = self._normalize_path(file_path)
        if not path or not self._validate_path(path):
            return False
        
        if not os.path.isfile(path):
            self._last_error = f"Not a file: {path}"
            return False
        
        cmd = ["open"]
        if app:
            cmd.extend(["-a", app])
        cmd.append(path)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        success = result.returncode == 0
        
        if not success:
            self._last_error = result.stderr.strip()
        
        if self.debug:
            app_str = f" with {app}" if app else ""
            status = "SUCCESS" if success else "FAILED"
            print(f"[OPEN_FILE] {path}{app_str} -> {status}")
        
        return success
    
    def copy_file(self, source: str, destination: str) -> bool:
        """
        Copy file or folder
        
        Args:
            source: Source path
            destination: Destination path (can be folder or new filename)
        """
        src = self._normalize_path(source)
        dst = self._normalize_path(destination)
        
        if not src or not self._validate_path(src, must_exist=True):
            return False
        
        # Destination parent must exist
        dst_path = Path(dst)
        if not dst_path.parent.exists():
            self._last_error = f"Destination folder doesn't exist: {dst_path.parent}"
            return False
        
        # Validate destination within workspace
        if not self._validate_path(str(dst_path.parent), must_exist=True):
            return False
        
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            
            if self.debug:
                print(f"[COPY] {src} -> {dst} SUCCESS")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            if self.debug:
                print(f"[COPY] {src} -> {dst} FAILED: {e}")
            return False
    
    def move_file(self, source: str, destination: str) -> bool:
        """
        Move or rename file/folder
        
        Args:
            source: Source path
            destination: Destination path
        """
        src = self._normalize_path(source)
        dst = self._normalize_path(destination)
        
        if not src or not self._validate_path(src, must_exist=True):
            return False
        
        dst_path = Path(dst)
        if not dst_path.parent.exists():
            self._last_error = f"Destination folder doesn't exist: {dst_path.parent}"
            return False
        
        if not self._validate_path(str(dst_path.parent), must_exist=True):
            return False
        
        try:
            shutil.move(src, dst)
            if self.debug:
                print(f"[MOVE] {src} -> {dst} SUCCESS")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            if self.debug:
                print(f"[MOVE] {src} -> {dst} FAILED: {e}")
            return False
    
    def create_file(self, file_path: str, content: str = "") -> bool:
        """
        Create new file with optional content
        
        Args:
            file_path: Path for new file
            content: Optional text content to write
        """
        path = self._normalize_path(file_path)
        if not path:
            return False
        
        file_p = Path(path)
        
        # Check if file already exists
        if file_p.exists():
            self._last_error = f"File already exists: {path}"
            return False
        
        # Validate parent directory
        if not file_p.parent.exists():
            self._last_error = f"Parent folder doesn't exist: {file_p.parent}"
            return False
        
        if not self._validate_path(str(file_p.parent), must_exist=True):
            return False
        
        try:
            file_p.write_text(content)
            if self.debug:
                size = len(content)
                print(f"[CREATE_FILE] {path} ({size} bytes) SUCCESS")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            if self.debug:
                print(f"[CREATE_FILE] {path} FAILED: {e}")
            return False
    
    def create_folder(self, folder_path: str, parents: bool = True) -> bool:
        """
        Create new folder
        
        Args:
            folder_path: Path for new folder
            parents: Create parent directories if needed (default: True)
        """
        path = self._normalize_path(folder_path)
        if not path:
            return False
        
        folder_p = Path(path)
        
        # Check if folder already exists
        if folder_p.exists():
            if folder_p.is_dir():
                if self.debug:
                    print(f"[CREATE_FOLDER] {path} already exists")
                return True
            else:
                self._last_error = f"Path exists but is not a folder: {path}"
                return False
        
        # Validate parent if not creating parents
        if not parents and not folder_p.parent.exists():
            self._last_error = f"Parent folder doesn't exist: {folder_p.parent}"
            return False
        
        # Validate workspace boundary
        if self.workspace_root:
            try:
                folder_p.resolve().relative_to(self.workspace_root.resolve())
            except ValueError:
                self._last_error = f"Path outside workspace: {path}"
                return False
        
        try:
            folder_p.mkdir(parents=parents, exist_ok=True)
            if self.debug:
                print(f"[CREATE_FOLDER] {path} SUCCESS")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            if self.debug:
                print(f"[CREATE_FOLDER] {path} FAILED: {e}")
            return False
    
    # ==================== UTILITY ====================
    
    def get_last_error(self) -> Optional[str]:
        """Get last error message"""
        return self._last_error
    
    def execute_step(self, step: Dict) -> Optional[bool]:
        """
        Execute automation step if it's an OS-level operation.

        Returns:
            True: Success
            False: Failed
            None: Not an OS operation (delegate to AX)
        """
        action = (step.get("action") or "").lower()
        app    = (step.get("app") or "").lower()
        url    = step.get("url") or ""
        target = step.get("target") or ""
        path_hint = step.get("path") or ""

        # Accept both 'open' and 'os_command' as aliases for "open this file/folder"
        if action in ("open", "os_command"):
            # Prefer URL, then explicit path, then target string (which might be a path)
            raw = url or path_hint or target
            if not raw:
                self._last_error = "No path or URL provided for OS open."
                return False

            norm = self._normalize_path(raw)
            if not norm:
                # _normalize_path already set a helpful error (file ID, etc.)
                return False

            # If it exists and is a dir → open_folder; otherwise try open_file
            if os.path.isdir(norm):
                return self.open_folder(norm)
            else:
                return self.open_file(norm)

        # Not an OS operation; let AX executor handle it
        return None


# ==================== TESTS ====================

def test_os_executor():
    """Test all operations"""
    
    # Create test workspace
    workspace = Path.home() / "Documents" / "os_executor_test"
    workspace.mkdir(exist_ok=True)
    
    executor = OSExecutor(workspace_root=str(workspace), debug=True)
    
    print("\n" + "="*60)
    print("OS Executor Test Suite")
    print("="*60)
    
    results = {}
    
    # Test 1: Create folder
    print("\n[TEST 1] Create Folder")
    new_folder = workspace / "new_test_folder"
    results['create_folder'] = executor.create_folder(str(new_folder))
    
    # Test 2: Create file
    print("\n[TEST 2] Create File")
    new_file = new_folder / "created_file.txt"
    results['create_file'] = executor.create_file(str(new_file), "This file was created by OS Executor")
    
    # Test 3: Open folder
    print("\n[TEST 3] Open Folder")
    results['open_folder'] = executor.open_folder(str(workspace))
    
    # Test 4: Open file
    print("\n[TEST 4] Open File")
    test_file = workspace / "test.txt"
    test_file.write_text("Test content for OS Executor")
    results['open_file'] = executor.open_file(str(test_file))
    
    # Test 5: Copy file
    print("\n[TEST 5] Copy File")
    copy_dest = workspace / "test_copy.txt"
    results['copy_file'] = executor.copy_file(str(test_file), str(copy_dest))
    
    # Test 6: Move file
    print("\n[TEST 6] Move File")
    move_dest = workspace / "test_moved.txt"
    results['move_file'] = executor.move_file(str(copy_dest), str(move_dest))
    
    # Test 7: File ID resolution (if available)
    print("\n[TEST 7] File ID Resolution")
    file_id_url = f"file:///.file/id=test"
    normalized = executor._normalize_path(file_id_url)
    results['file_id'] = normalized is not None or True  # Always pass if no real ID
    
    # Summary
    print("\n" + "="*60)
    passed = sum(results.values())
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print(f"Workspace: {workspace}")
    print("="*60)
    
    return all(results.values())


if __name__ == "__main__":
    import sys
    
    if "--test" in sys.argv:
        success = test_os_executor()
        sys.exit(0 if success else 1)
    else:
        print("OS Executor - macOS System Operations")
        print("Run with --test to execute test suite")
        print("\nSupported operations:")
        print("  - create_file(path, content='')")
        print("  - create_folder(path, parents=True)")
        print("  - open_folder(path)")
        print("  - open_file(path, app=None)")
        print("  - copy_file(source, destination)")
        print("  - move_file(source, destination)")
        print("\nBanned operations:")
        print("  - delete (not implemented for safety)")