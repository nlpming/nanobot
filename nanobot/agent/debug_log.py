"""Debug logging for agent thought/action/observation output."""

from dataclasses import dataclass


@dataclass
class DebugLogConfig:
    thought_max_len: int = 200
    arg_max_len: int = 100
    arg_val_max_len: int = 40
    obs_max_len: int = 150


_config = DebugLogConfig()


def set_config(
    thought_max_len: int | None = None,
    arg_max_len: int | None = None,
    arg_val_max_len: int | None = None,
    obs_max_len: int | None = None,
) -> None:
    global _config
    if thought_max_len is not None:
        _config.thought_max_len = thought_max_len
    if arg_max_len is not None:
        _config.arg_max_len = arg_max_len
    if arg_val_max_len is not None:
        _config.arg_val_max_len = arg_val_max_len
    if obs_max_len is not None:
        _config.obs_max_len = obs_max_len


def print_thought(content: str) -> None:
    content = (content or "").strip()
    if len(content) > _config.thought_max_len:
        content = content[:_config.thought_max_len] + "…"
    print(f"\033[1;34m▸ Thought\033[0m {content}", flush=True)


def print_action(name: str, arguments: dict | list) -> None:
    if isinstance(arguments, dict):
        vals = list(arguments.values())
    else:
        vals = arguments or []
    args_str = ", ".join(str(v)[:_config.arg_val_max_len] for v in vals)
    if len(args_str) > _config.arg_max_len:
        args_str = args_str[:_config.arg_max_len] + "…"
    print(f"\033[1;32m▸ Action\033[0m \033[36m{name}\033[0m({args_str})", flush=True)


def print_observation(name: str, result: str) -> None:
    obs = (result or "(empty)").strip()
    if len(obs) > _config.obs_max_len:
        obs = obs[:_config.obs_max_len] + "…"
    print(f"\033[1;33m▸ Obs\033[0m \033[36m{name}\033[0m: {obs}", flush=True)