"""Cross-process checkpoints with an unrelated app and a config-file-only root."""

import textwrap

import pytest
import test_checkpoint_integration as checkpoint_harness

MANAGED_ENV = ("YAI_WORKSPACE_ROOT", "YAI_TOOL_TIMEOUT", "YAI_TOOL_ENV_INHERIT", "YAI_TOOL_OUTPUT_MAX_CHARS")


@pytest.mark.parametrize("worker", [False, True], ids=["sync", "stream-worker"])
def test_other_application_does_not_change_config_root_or_cross_process_rewind(tmp_path, monkeypatch, worker):
    """Keep entry/REPL/client/tools/save/capture/rewind real in each interpreter."""
    source = checkpoint_harness.CLI_PROCESS
    anchor = "    import yaicli.cli as cli_module\n"
    assert source.count(anchor) == 1
    unrelated_application = textwrap.indent(
        textwrap.dedent(
            """\
            from copy import deepcopy
            from types import SimpleNamespace
            decoy_config = deepcopy(dict(cli_module.cfg))
            decoy_config.update(
                WORKSPACE_ROOT=str(Path(payload["report"]).parent / "unrelated-workspace"),
                CHAT_HISTORY_DIR=str(Path(payload["report"]).parent / "unrelated-sessions"),
                MODEL="unrelated-model",
            )
            decoy = cli_module.CLI(config=decoy_config, client=SimpleNamespace())
            report["unrelated_root"] = decoy.config["WORKSPACE_ROOT"]
            """
        ),
        "    ",
    )
    source = source.replace(anchor, anchor + unrelated_application)
    anchor = '        report["chat"] = cli.chat.to_dict()\n'
    assert source.count(anchor) == 1
    source = source.replace(
        anchor,
        anchor
        + '        report["runtime_root"] = cli.config["WORKSPACE_ROOT"]\n'
        + f'        report["managed_env_after"] = {{key: os.environ.get(key) for key in {MANAGED_ENV!r}}}\n',
    )
    monkeypatch.setattr(checkpoint_harness, "CLI_PROCESS", source)
    project = tmp_path / "project"
    cwd = project / "nested"
    cwd.mkdir(parents=True)
    options = {"workspace_from_config": True, "cwd": cwd, "worker": worker}
    _, created = checkpoint_harness.run_cli(
        tmp_path,
        ["--chat", "Runtime owned root", "--allowed-tools", "fs_write_file"],
        inputs=["write the itinerary", "pack for the weekend"],
        **options,
    )
    path, saved = checkpoint_harness.saved_chats(tmp_path)["Runtime owned root"]
    session_id = saved["checkpoint_session_id"]
    before = checkpoint_harness.manifest(tmp_path, session_id)
    assert created["workspace_env_at_start"] is None
    assert created["runtime_root"] == before["root"] == str(project)
    assert created["unrelated_root"] == str(tmp_path / "unrelated-workspace")
    assert created["managed_env_after"] == dict.fromkeys(MANAGED_ENV)
    assert all((request["thread"] != "MainThread") is worker for request in created["requests"])
    assert (cwd / "trip.md").read_bytes() == checkpoint_harness.TRIP_SECOND.encode()
    assert (cwd / "packing.md").read_bytes() == checkpoint_harness.PACKING.encode()
    assert saved["checkpoint_head"] == before["head"] == 2
    assert before["session_path"] == str(path.resolve())

    _, reopened = checkpoint_harness.run_cli(tmp_path, ["--resume"], inputs=["/checkpoints"], **options)
    assert reopened["chat"]["history"] == saved["history"]
    assert reopened["chat"]["checkpoint_session_id"] == session_id
    assert reopened["managed_env_after"] == dict.fromkeys(MANAGED_ENV)
    assert checkpoint_harness.manifest(tmp_path, session_id) == before

    result, rewound = checkpoint_harness.run_cli(tmp_path, ["--resume"], inputs=["/rewind 1"], answers=["y"], **options)
    after = checkpoint_harness.manifest(tmp_path, session_id)
    assert "Rewound to #1." in result.stdout
    assert rewound["workspace_env_at_start"] is None
    assert rewound["runtime_root"] == before["root"] == after["root"]
    assert rewound["managed_env_after"] == dict.fromkeys(MANAGED_ENV)
    assert rewound["chat"]["checkpoint_head"] == after["head"] == 1
    assert [record["id"] for record in after["records"]] == [0, 1]
    assert after["next"] > 2
    assert (cwd / "trip.md").read_bytes() == checkpoint_harness.TRIP_FIRST.encode()
    assert not (cwd / "packing.md").exists()
    assert not (tmp_path / "unrelated-workspace").exists()
    assert not (tmp_path / "unrelated-sessions").exists()
