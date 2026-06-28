#!/usr/bin/env python3
"""
Generates a macOS Launch Agent plist that runs accountant.py every day at 7:00am.

Usage:
    python scheduler.py

On Linux / Windows the script prints cross-platform alternatives instead.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

PLIST_LABEL = "com.accountant.daily"
PLIST_PATH  = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
RUN_HOUR    = 7
RUN_MINUTE  = 0


def _generate_plist(python_path: str, script_path: str, log_dir: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
        <string>--now</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{RUN_HOUR}</integer>
        <key>Minute</key>
        <integer>{RUN_MINUTE}</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>{log_dir}/launchd_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/launchd_stderr.log</string>

    <key>WorkingDirectory</key>
    <string>{Path(script_path).parent}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def _setup_macos() -> None:
    python_path = sys.executable
    script_path = str(Path(__file__).parent.resolve() / "accountant.py")
    log_dir     = str(Path(__file__).parent.resolve() / "logs")

    plist_content = _generate_plist(python_path, script_path, log_dir)

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_content)
    print(f"Plist written: {PLIST_PATH}")

    # Unload any previous version silently, then load
    subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True,
    )
    result = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"Launch agent loaded successfully.")
        print(f"\nAccountant will run automatically every day at {RUN_HOUR:02d}:{RUN_MINUTE:02d}.")
        print("To unload:  launchctl unload ~/Library/LaunchAgents/com.accountant.daily.plist")
    else:
        print(f"launchctl load returned code {result.returncode}.")
        print("Try manually: launchctl load", PLIST_PATH)
        if result.stderr:
            print("stderr:", result.stderr.strip())


def _print_windows_instructions() -> None:
    script_path = str(Path(__file__).parent.resolve() / "accountant.py")
    python_path = sys.executable
    print("\nWindows Task Scheduler setup:")
    print("─" * 60)
    print("Run the following in an elevated PowerShell prompt:\n")
    print(f'$action  = New-ScheduledTaskAction -Execute "{python_path}" -Argument "{script_path} --now"')
    print(f'$trigger = New-ScheduledTaskTrigger -Daily -At 7am')
    print(f'Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "Accountant" -RunLevel Highest')
    print()


def _print_linux_instructions() -> None:
    script_path = str(Path(__file__).parent.resolve() / "accountant.py")
    python_path = sys.executable
    print("\nLinux cron setup — add this line with: crontab -e")
    print("─" * 60)
    print(f"0 7 * * 1-5  {python_path} {script_path} --now")
    print()


def main() -> None:
    system = platform.system()
    print("=" * 60)
    print("  Accountant — Scheduler Setup")
    print("=" * 60)

    if system == "Darwin":
        _setup_macos()
    elif system == "Windows":
        print("\nDetected Windows — generating Task Scheduler instructions.")
        _print_windows_instructions()
    else:
        print("\nDetected Linux — generating cron instructions.")
        _print_linux_instructions()


if __name__ == "__main__":
    main()
