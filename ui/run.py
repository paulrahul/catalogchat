#!/usr/bin/env python3
"""
Launch script for the CatalogChat Streamlit UI.

Usage:
    python -m ui.run
    # or
    python ui/run.py
"""
import subprocess
import sys
from pathlib import Path


def main():
    # Get the path to the app.py file
    ui_dir = Path(__file__).parent
    app_path = ui_dir / "app.py"

    # Run streamlit
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(app_path),
        "--server.headless", "true",
        "--theme.primaryColor", "#96B6C5",
        "--theme.backgroundColor", "#F1F0E8",
        "--theme.secondaryBackgroundColor", "#EEE0C9",
        "--theme.textColor", "#3A4A50",
    ]

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nShutting down...")
    except subprocess.CalledProcessError as e:
        print(f"Error running Streamlit: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
