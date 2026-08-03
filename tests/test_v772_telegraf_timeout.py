from pathlib import Path


def test_legacy_timeout_patch_is_replaced_by_modular_inputs():
    script = Path('update.sh').read_text(encoding='utf-8')
    assert 'remove_legacy_telegraf_blocks' in script
    assert '90-home-server-monitor.conf' in script
    assert 'commands = ["/usr/local/bin/hsm-collect storage"]' in script
    assert 'timeout = "20s"' in script
    assert 'commands = ["/usr/local/bin/hsm-collect raid"]' in script
    assert 'timeout = "15s"' in script
    assert 'commands = ["/usr/local/bin/hsm-collect ups"]' in script
    assert 'timeout = "5s"' in script
    assert 'commands = ["/usr/local/bin/hsm-collect proxmox"]' in script
    assert 'timeout = "10s"' in script
