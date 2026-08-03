from pathlib import Path


def test_update_uses_four_modular_telegraf_inputs():
    text = Path("update.sh").read_text(encoding="utf-8")
    for module in ("storage", "raid", "ups", "proxmox"):
        assert f'hsm-collect {module}' in text
    assert '90-home-server-monitor.conf' in text
    assert 'remove_legacy_telegraf_blocks' in text


def test_legacy_monolithic_command_is_not_written_to_managed_config():
    for name in ("install.sh", "update.sh"):
        text = Path(name).read_text(encoding="utf-8")
        managed = text[text.index('install_telegraf_config()'):text.index('remove_legacy_telegraf_blocks()')]
        assert '/opt/home-server-monitor/collector.py' not in managed
