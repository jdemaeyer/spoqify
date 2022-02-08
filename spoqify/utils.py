import os
from contextlib import suppress


def load_dotenv():
    with suppress(FileNotFoundError):
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    os.environ.setdefault(*line.split('=', 1))
