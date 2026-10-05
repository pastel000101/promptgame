import promptgame
from promptgame.main import main


def test_package_imports():
    assert promptgame.__doc__


def test_main_returns_zero():
    assert main() == 0
