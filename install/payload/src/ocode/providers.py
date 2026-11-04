"""Claves globales de proveedores y sus ficheros de entorno.

Cada clave se guarda en `config\\secrets\\<id>.env` y se inyecta en cada
contenedor con `--env-file`, de modo que nunca aparece en la línea de comandos
ni en la vista «Comando Docker». Este módulo no registra ni imprime la clave.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    env_var: str
    filename: str
    label: str
    hint: str
    description: str = ""
    legacy_env_var: str | None = None


PROVIDERS: dict[str, Provider] = {
    # OpenCode Console exige su clave en OPENCODE_API_KEY: su lógica interna
    # (`hasKey`) y el transporte HTTP usan ese nombre fijo. Sin clave funciona
    # en modo gratuito; con clave atribuye el uso a la cuenta.
    "opencode": Provider(
        id="opencode",
        name="OpenCode Console",
        env_var="OPENCODE_API_KEY",
        filename="opencode-console.env",
        label="io.ocode.opencode",
        hint="opencode/<modelo>",
        description=(
            "Sin clave funciona en modo gratuito. Con clave, el uso se atribuye "
            "a tu cuenta y se habilitan los modelos de pago. Es independiente "
            "de OpenCode Go."
        ),
    ),
    "opencode-go": Provider(
        id="opencode-go",
        name="OpenCode Go",
        env_var="OPENCODE_GO_API_KEY",
        filename="opencode-go.env",
        label="io.ocode.opencode-go",
        hint="opencode-go/<modelo>",
        description=(
            "Suscripción Go. Usa una variable y un fichero propios; no comparte "
            "clave con OpenCode Console."
        ),
        legacy_env_var="OPENCODE_API_KEY",
    ),
    "openai": Provider(
        id="openai",
        name="OpenAI",
        env_var="OPENAI_API_KEY",
        filename="openai.env",
        label="io.ocode.openai",
        hint="openai/<modelo>",
        description="Acceso directo a OpenAI con tu propia clave.",
    ),
    "openrouter": Provider(
        id="openrouter",
        name="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        filename="openrouter.env",
        label="io.ocode.openrouter",
        hint="openrouter/<modelo>",
        description=(
            "Acceso a múltiples modelos de distintos proveedores a través de "
            "OpenRouter con tu propia clave."
        ),
    ),
}

MIN_LENGTH = 16


def provider(provider_id: str) -> Provider:
    try:
        return PROVIDERS[provider_id]
    except KeyError:
        raise KeyError(f"Proveedor desconocido: {provider_id}") from None


def env_file(paths, provider_id: str) -> Path:
    """Ruta del fichero de entorno, exista o no."""
    return paths.secrets_dir / provider(provider_id).filename


def key_configured(paths, provider_id: str) -> bool:
    return _read_key(env_file(paths, provider_id), provider(provider_id).env_var) is not None


def key_fingerprint(paths, provider_id: str) -> str | None:
    key = _read_key(env_file(paths, provider_id), provider(provider_id).env_var)
    if key is None:
        return None
    entry = provider(provider_id)
    # El nombre de la variable forma parte de la huella: renombrarla obliga a
    # recrear el contenedor aunque la clave no cambie.
    payload = f"{entry.env_var}\0{key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def key_last4(paths, provider_id: str) -> str | None:
    key = _read_key(env_file(paths, provider_id), provider(provider_id).env_var)
    if key is None or len(key) < 4:
        return None
    return key[-4:]


def save_key(paths, provider_id: str, key: str) -> None:
    """Valida y guarda la clave de forma atómica. Nunca incluye la clave en errores."""
    entry = provider(provider_id)
    value = _validate(key)
    _write_key_file(env_file(paths, provider_id), entry.env_var, value)


def migrate_legacy_keys(paths) -> list[str]:
    """Renombra variables antiguas en los ficheros de entorno de ocode.

    OpenCode Go usaba `OPENCODE_API_KEY`, el mismo nombre que OpenCode Console
    necesita. Si se dejara así, el contenedor recibiría una clave de Go con el
    nombre de Console y ambas dejarían de ser independientes. La reescritura es
    atómica y elimina la variable antigua aunque ya exista la nueva. No se crea
    copia de seguridad: duplicaría el secreto.
    """
    migrated = []
    for entry in PROVIDERS.values():
        if not entry.legacy_env_var:
            continue
        path = env_file(paths, entry.id)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue

        current = _read_key(path, entry.env_var)
        legacy = _read_key(path, entry.legacy_env_var)
        value = current or legacy
        if value is None:
            continue
        if current is not None and entry.legacy_env_var not in _declared_vars(text):
            continue

        _write_key_file(path, entry.env_var, value)
        migrated.append(entry.id)
    return migrated


def _write_key_file(path: Path, env_var: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{env_var}={value}\n")
        _restrict_permissions(Path(temp_name))
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def clear_key(paths, provider_id: str) -> None:
    """Elimina la clave; no falla si ya no existe."""
    try:
        env_file(paths, provider_id).unlink()
    except FileNotFoundError:
        pass


def _validate(key: str) -> str:
    value = key.strip()
    if not value:
        raise ValueError("La clave no puede estar vacía.")
    if len(value) < MIN_LENGTH:
        raise ValueError(
            f"La clave debe tener al menos {MIN_LENGTH} caracteres."
        )
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise ValueError(
            "La clave no puede contener espacios ni caracteres de control."
        )
    return value


def _declared_vars(text: str) -> set[str]:
    """Nombres de variable declarados en un fichero de entorno, sin valores."""
    names = set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, _ = line.partition("=")
        if separator:
            names.add(name)
    return names


def _read_key(path: Path, env_var: str) -> str | None:
    """Lee la primera entrada válida; un fichero vacío o mal formado no cuenta."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or name != env_var:
            continue
        try:
            valid = _validate(value)
        except ValueError:
            return None
        # No se pasa a Docker un valor con espacios que él leería literalmente.
        return valid if valid == value else None
    return None


def _restrict_permissions(path: Path) -> None:
    """Best effort: limita el fichero al usuario actual en Windows."""
    if os.name != "nt":
        return
    user = os.environ.get("USERNAME")
    if not user:
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass
