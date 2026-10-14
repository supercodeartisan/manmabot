"""Bot package (was login_beta/): drives the Purple login + game flow.

Split into win/ (windowing, OCR, Interception driver wrapper), input/
(event router), and vision/ (person detection); data assets live under
bot/data/ (anchors, character templates, OCR server lists, models, the
Interception driver DLL).

Bot modules run both from the source tree and inside the frozen bundle as
loose .py subpackages, so resolve paths through bot_dir()/data_dir()/asset()
instead of __file__-relative lookups."""
import os

_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BOT_DIR, "data")


def bot_dir():
    return _BOT_DIR


def data_dir():
    return _DATA_DIR


def asset(*parts):
    return os.path.join(_DATA_DIR, *parts)
