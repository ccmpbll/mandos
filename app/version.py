"""Set by the image build (VERSION build arg); "dev" when run from a checkout."""
import os

VERSION = os.environ.get("MANDOS_VERSION", "dev")
