import os
import sys
from pathlib import Path

# Mark environment as serverless on Vercel
os.environ["VERCEL"] = "1"

# Add repository root to Python path so app modules import reliably
ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.main import app
