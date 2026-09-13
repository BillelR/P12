"""
Configuration pytest : ajoute src/ au path pour permettre les imports
directs des modules du projet (google_maps_client, etl, generate_activities,
cdc_consumer) depuis les fichiers de test.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
