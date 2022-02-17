import os
import time
from contextlib import suppress


def load_dotenv():
    with suppress(FileNotFoundError):
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    os.environ.setdefault(*line.split('=', 1))


class RecentCounter:

    def __init__(self, max_age=86400):
        self.max_age = max_age
        self.history = []

    def record(self):
        self.history.append(time.time())

    def clean(self, key=None):
        threshold = time.time() - self.max_age
        for idx, x in enumerate(self.history):
            if x > threshold:
                break
        else:
            idx = len(self.history)
        self.history = self.history[idx:]

    def get(self):
        self.clean()
        return len(self.history)
