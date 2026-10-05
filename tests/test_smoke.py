import promptgame
from promptgame.infrastructure.config import load_config
from promptgame.main import build, seed_source


def test_package_imports():
    assert promptgame.__doc__


def test_build_wires_components(tmp_path):
    config = load_config({"PROMPTGAME_LOG_DIR": str(tmp_path), "PROMPTGAME_SEED": "11"})
    session, client, log = build(config)
    assert session.seed == 11 and client.model == config.model
    log.close()


def test_random_seed_when_not_configured():
    seeds = {seed_source(load_config({}))() for _ in range(5)}
    assert len(seeds) > 1
