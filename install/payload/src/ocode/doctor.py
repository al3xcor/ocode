from pathlib import Path
from . import providers
from .docker import docker_available, image_exists
from .store import provider_env_snippet, provider_env_status, project_overrides_providers


def doctor(paths, cfg, projects):
    lines = []

    ok, detail = docker_available(cfg)
    lines.append(("✓" if ok else "✗") + f" Runtime contenedores: {detail}")

    lines.append(
        ("✓" if paths.global_agents.exists() else "✗")
        + f" AGENTS: {paths.global_agents}"
    )
    lines.append(
        ("✓" if paths.opencode_config.exists() else "✗")
        + f" OpenCode config: {paths.opencode_config}"
    )

    separated, separation_detail = provider_env_status(paths.opencode_config)
    if separated:
        lines.append(
            "✓ Separación Console/Go: OpenCode Go usa su propia variable"
        )
    else:
        lines.append(f"✗ Separación Console/Go: {separation_detail}")
        lines.append("  Añade a config\\opencode.jsonc:")
        lines.extend(f"  {line}" for line in provider_env_snippet().splitlines())

    for provider in providers.PROVIDERS.values():
        if providers.key_configured(paths, provider.id):
            last4 = providers.key_last4(paths, provider.id)
            suffix = f" (…{last4})" if last4 else ""
            lines.append(
                f"✓ Clave {provider.name}: configurada{suffix} · fichero legible"
            )
        elif providers.env_file(paths, provider.id).exists():
            lines.append(f"✗ Clave {provider.name}: fichero ilegible o no válido")
        else:
            suffix = " (modo gratuito sin clave)" if provider.id == "opencode" else ""
            lines.append(f"• Clave {provider.name}: no configurada{suffix}")

    for name, runtime in cfg.runtimes.items():
        exists = image_exists(cfg, runtime.image)
        lines.append(
            f"{'✓' if exists else '•'} Runtime {name}: {runtime.image}"
        )

    for p in projects:
        exists = Path(p.workspace).is_dir()
        lines.append(
            ("✓" if exists else "✗")
            + f" {p.name}/{p.branch}: {p.workspace}"
        )
        project_config = paths.project_config(p.project_id)
        if (
            p.project_config_enabled
            and project_config.exists()
            and project_overrides_providers(project_config)
        ):
            lines.append(
                f"• {p.name}/{p.branch}: su opencode.jsonc declara providers y "
                "puede anular la separación Console/Go"
            )

    return "\n".join(lines)
