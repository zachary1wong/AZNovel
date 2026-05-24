"""Config management CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from aznovel.storage import project_fs
from aznovel.utils.rich_ui import console, error, info, success, warn

# Global config file location
_GLOBAL_CONFIG = Path.home() / ".aznovel" / "config.json"
_PROFILES_FILE = Path.home() / ".aznovel" / "llm_profiles.json"

DEFAULT_CONFIG = {
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": "",
    "base_url": "",
    "temperature": 0.7,
    "max_tokens": 4096,
    "word_target": 2000,
}


def load_config(profile_name: str | None = None) -> dict:
    """Load config (project-level overrides global, skipping empty values).

    If profile_name is given, load that profile directly from llm_profiles.json
    and skip the global config file (safe for concurrent use).
    """
    config = dict(DEFAULT_CONFIG)

    if profile_name:
        # Load from named profile — no file write, safe for concurrency
        profiles = load_profiles()
        found = [p for p in profiles if p.get("name") == profile_name]
        if not found:
            error(f"未找到 LLM 配置: {profile_name}")
            error(f"可用配置: {', '.join(p['name'] for p in profiles)}")
            raise typer.Exit(1)
        profile = found[0]
        config.update({
            "provider": profile.get("provider", "openai"),
            "model": profile.get("model", ""),
            "api_key": profile.get("api_key", ""),
            "base_url": profile.get("base_url", ""),
        })
    else:
        # Load global config
        if _GLOBAL_CONFIG.exists():
            config.update(json.loads(_GLOBAL_CONFIG.read_text(encoding="utf-8")))

    # Load project-level override (only non-empty values)
    root = project_fs.find_project_root()
    if root:
        proj_config = root / ".aznovel" / "config.json"
        if proj_config.exists():
            proj_data = json.loads(proj_config.read_text(encoding="utf-8"))
            config.update({k: v for k, v in proj_data.items() if v != "" and v is not None})

    return config


def build_llm_config(profile_name: str | None = None):
    """Build LLMConfig from config or named profile."""
    from aznovel.llm.base import LLMConfig

    config_data = load_config(profile_name=profile_name)
    if not config_data.get("api_key"):
        error("未设置 API Key。请运行: aznovel config set api_key YOUR_KEY")
        raise typer.Exit(1)

    return LLMConfig(
        provider=config_data["provider"],
        model=config_data["model"],
        api_key=config_data["api_key"],
        base_url=config_data.get("base_url", ""),
        temperature=config_data.get("temperature", 0.7),
        max_tokens=config_data.get("max_tokens", 4096),
    )


def save_config(config: dict, *, global_level: bool = False) -> None:
    """Save config to file."""
    if global_level:
        path = _GLOBAL_CONFIG
    else:
        root = project_fs.find_project_root()
        if root is None:
            error("未找到项目。请先运行 'aznovel init'")
            raise typer.Exit(1)
        path = root / ".aznovel" / "config.json"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def run_config(
    action: str,
    key: str | None,
    value: str | None,
    global_level: bool,
) -> None:
    """Handle config command."""
    if action == "get":
        config = load_config()
        if key:
            val = config.get(key)
            if val is None:
                error(f"未知配置项: {key}")
                raise typer.Exit(1)
            if key == "api_key" and val:
                masked = val[:8] + "..." + val[-4:] if len(val) > 12 else "***"
                console.print(f"{key} = {masked}")
            else:
                console.print(f"{key} = {val}")
        else:
            table = Table(title="当前配置", show_header=True)
            table.add_column("键", style="bold")
            table.add_column("值")
            for k, v in config.items():
                display = str(v)
                if k == "api_key" and display:
                    display = display[:8] + "..." + display[-4:] if len(display) > 12 else "***"
                table.add_row(k, display)
            console.print(table)

    elif action == "set":
        if not key or not value:
            error("用法: aznovel config set <key> <value>")
            raise typer.Exit(1)
        if key not in DEFAULT_CONFIG:
            error(f"未知配置项: {key}")
            console.print(f"可用配置: {', '.join(DEFAULT_CONFIG.keys())}")
            raise typer.Exit(1)

        config = load_config()
        target_type = type(DEFAULT_CONFIG[key])
        if target_type == int:
            config[key] = int(value)
        elif target_type == float:
            config[key] = float(value)
        else:
            config[key] = value

        save_config(config, global_level=global_level)
        scope = "全局" if global_level else "项目"
        success(f"{scope}配置已更新: {key} = {value}")

    elif action == "profiles":
        profiles = load_profiles()
        if not profiles:
            info("还没有保存任何 LLM 配置。")
            info("运行 'aznovel config init' 或在项目初始化时创建。")
        else:
            table = Table(title="已保存的 LLM 配置", show_header=True)
            table.add_column("序号", style="bold")
            table.add_column("名称")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("URL")
            for i, p in enumerate(profiles, 1):
                url = p.get("base_url", "") or "(默认)"
                table.add_row(str(i), p["name"], p.get("provider", ""), p.get("model", ""), url)
            console.print(table)

    elif action == "init":
        info("AZNovel 配置向导\n")
        provider = typer.prompt("API 提供商 (openai/anthropic)", default="openai")
        model = typer.prompt("模型名称", default="gpt-4o")
        api_key = typer.prompt("API Key", hide_input=True)
        base_url = ""
        if provider == "openai":
            base_url = typer.prompt("Base URL (留空使用默认)", default="")
        config = {
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        save_config(config, global_level=True)
        success("配置已保存到 ~/.aznovel/config.json")

    else:
        error(f"未知操作: {action}。可用: get, set, init")
        raise typer.Exit(1)


# ── LLM Profile Management ─────────────────────────────────────────────────

def load_profiles() -> list[dict]:
    """Load all saved LLM profiles."""
    if not _PROFILES_FILE.exists():
        return []
    try:
        data = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
        return data.get("profiles", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_profiles(profiles: list[dict]) -> None:
    """Save LLM profiles to file."""
    _PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROFILES_FILE.write_text(
        json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_profile(profile: dict) -> None:
    """Add or update an LLM profile."""
    profiles = load_profiles()
    # Update existing if same name
    for i, p in enumerate(profiles):
        if p.get("name") == profile["name"]:
            profiles[i] = profile
            save_profiles(profiles)
            return
    profiles.append(profile)
    save_profiles(profiles)


def select_or_create_profile() -> dict | None:
    """Interactive profile selection. Returns selected config dict or None if cancelled."""
    profiles = load_profiles()

    if profiles:
        console.print("\n[bold cyan]可用的 LLM 配置:[/]\n")
        for i, p in enumerate(profiles, 1):
            url_display = p.get("base_url", "") or "(默认)"
            console.print(f"  [bold]{i}[/]. {p['name']}  [dim]{p.get('model', '')} | {url_display}[/]")
        console.print(f"  [bold]n[/]. 新建配置")
        console.print()

        choice = console.input("[bold green]选择配置 (输入编号或 n) > [/]")

        if choice.strip().lower() == "n":
            return _create_new_profile()

        try:
            idx = int(choice.strip()) - 1
            if 0 <= idx < len(profiles):
                selected = profiles[idx]
                info(f"已选择: {selected['name']}")
                return selected
            else:
                warn("无效选择，将创建新配置。")
                return _create_new_profile()
        except ValueError:
            warn("无效输入，将创建新配置。")
            return _create_new_profile()
    else:
        console.print("\n[bold]首次使用，请配置 LLM 连接。[/]\n")
        return _create_new_profile()


def _create_new_profile() -> dict | None:
    """Interactively create a new LLM profile."""
    info("新建 LLM 配置\n")

    name = typer.prompt("配置名称（用于标识，如 MiMo、GPT-4o）")
    provider = typer.prompt("API 类型", default="openai",
                            help="openai 兼容 OpenAI/DeepSeek/Qwen/本地模型等，anthropic 兼容 Claude")

    base_url = typer.prompt("API URL（留空使用默认）", default="")
    api_key = typer.prompt("API Key", hide_input=True)
    model = typer.prompt("Model ID（模型标识）")

    profile = {
        "name": name,
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }

    add_profile(profile)
    success(f"配置 '{name}' 已保存！")
    return profile


def apply_profile_to_config(profile: dict, target_path: Path) -> None:
    """Write a profile's LLM settings to a config file (project or global)."""
    config = {}
    if target_path.exists():
        try:
            config = json.loads(target_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    config.update({
        "provider": profile.get("provider", "openai"),
        "model": profile.get("model", ""),
        "api_key": profile.get("api_key", ""),
        "base_url": profile.get("base_url", ""),
    })

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
