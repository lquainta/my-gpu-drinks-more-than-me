#!/usr/bin/env python3
"""Launch DEPTHS:  python3 depths/play.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from depths.app import main  # noqa: E402

if __name__ == "__main__":
    main()
