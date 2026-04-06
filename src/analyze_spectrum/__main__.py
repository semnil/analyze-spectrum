"""Allow running as `python -m analyze_spectrum`."""

import sys

from analyze_spectrum.cli import main

sys.exit(main())
