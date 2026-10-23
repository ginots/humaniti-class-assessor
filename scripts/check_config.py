"""Print configuration booleans only, never dotenv contents or credentials."""
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assessment import load_env
load_env()
print('GEMINI_API_KEY configured:', bool(os.environ.get('GEMINI_API_KEY')))
print('Requested model is allowed:', os.environ.get('GEMINI_MODEL','gemini-3.8-flash') == 'gemini-3.8-flash')
print('Credential remains server-side; no key or .env content displayed.')
