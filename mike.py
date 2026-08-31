#!/usr/bin/env python3
"""Entry point so `mike` works from a clone without installation: python3 mike.py …"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mike.main import main  # noqa: E402

main()
