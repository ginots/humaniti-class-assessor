"""One live synthetic-only Gemini request. Never prints prompts, responses or key."""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'tests')]
from assessment import AppError, assess
from synthetic import payload
import time

if __name__ == '__main__':
    try:
        started = time.monotonic()
        result = assess(payload())
        print('Synthetic Gemini connectivity: PASS; model=' + result['model'] + '; validated evidence items=' + str(len(result['evidence'])) + '; category present=' + str(result['overall_category'] is not None) + '; elapsed_seconds=' + str(round(time.monotonic()-started,1)))
    except AppError as error:
        print('Synthetic Gemini connectivity:', error.code, '-', error.message)
        raise SystemExit(1)
