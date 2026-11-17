"""persist() removes only the launch agents it manages (11-15: it removed the AD Coin worker daemon's plist)."""

from scripts.service_deploy import Deployment


def test_persist_keeps_other_launch_agents_under_the_same_prefix(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    deployment = Deployment(tmp_path / 'root')
    agents = home / 'Library/LaunchAgents'
    agents.mkdir(parents=True)
    state = {'phase': 'running', 'services': {'frontend': {'active': 'b'}, 'admin': {'active': 'a'}}}
    for role, slot in (('frontend', 'b'), ('admin', 'a'), ('jobs', 'main'), ('execution', 'main'), ('proxy', 'main')):
        (deployment.directory / (deployment.label(role, slot) + '.plist')).write_text('<plist/>')
    daemon = agents / (deployment.prefix + '.adcoin-worker.plist')
    daemon.write_text('<plist>daemon</plist>')
    stale = agents / (deployment.label('frontend', 'a') + '.plist')       # the slot that stopped serving
    stale.write_text('<plist>old slot</plist>')
    stranger = agents / 'com.example.other.plist'
    stranger.write_text('<plist/>')
    deployment.persist(state)
    assert daemon.read_text() == '<plist>daemon</plist>'                   # survives every deploy
    assert stranger.exists()
    assert not stale.exists()                                                # managed and not wanted: removed
    assert (agents / (deployment.label('frontend', 'b') + '.plist')).exists()
    assert sorted(p.name for p in agents.glob(deployment.prefix + '.*.plist')) == sorted(
        [deployment.label(r, s) + '.plist' for r, s in (('frontend', 'b'), ('admin', 'a'), ('jobs', 'main'),
                                                          ('execution', 'main'), ('proxy', 'main'))]
        + [daemon.name])
    deployment.persist({'phase': 'stopped', 'services': {}})                # a full stop still keeps the daemon
    assert daemon.exists() and not (agents / (deployment.label('frontend', 'b') + '.plist')).exists()


def test_the_daemon_release_is_pinned_once_and_the_prune_keeps_it(tmp_path):
    """PM 11-15: the daemon's release folder was protected only while its process ran."""
    from scripts.adcoin_worker_env import PIN_TAG, pin_release
    deployment = Deployment(tmp_path / 'root')
    pinned = deployment.directory / 'pinned-releases.txt'
    pinned.write_text('align-admin-20261113-r2\n# a comment\n')
    pin_release(str(pinned), 'adv-frontend-20261114-r1')
    pin_release(str(pinned), 'day15-frontend-20261115-r1')               # a reinstall replaces the old pin
    lines = pinned.read_text().splitlines()
    assert lines[:2] == ['align-admin-20261113-r2', '# a comment']          # other teams' lines untouched
    assert [line for line in lines if line.endswith(PIN_TAG)] == ['day15-frontend-20261115-r1  ' + PIN_TAG]
    names = {'day15-frontend-20261115-r1', 'adv-frontend-20261114-r1', 'align-admin-20261113-r2', 'other-r1'}
    assert deployment.waiting_releases(names) == {'day15-frontend-20261115-r1', 'align-admin-20261113-r2'}
    for bad in ('', 'a/b', 'x # y'):
        try:
            pin_release(str(pinned), bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_the_install_script_pins_before_it_loads_the_daemon():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / 'deploy/launchd/install-adcoin-worker.sh').read_text()
    # 11-15 (480e9b19): the bootout/bootstrap step moved to adcoin-worker-load.sh, called after the pin
    assert text.index('pin_release') < text.index('bash "$ROOT/deploy/launchd/adcoin-worker-load.sh"')
    load = (Path(__file__).resolve().parents[1] / 'deploy/launchd/adcoin-worker-load.sh').read_text()
    assert 'bootstrap "$DOMAIN" "$P"' in load
