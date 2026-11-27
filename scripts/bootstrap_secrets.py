"""Bootstraps local cryptographic secrets vault without any hardcoded keys in source code."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.security.secrets import SecretsManager


def main() -> None:
    vault_path = SecretsManager.ensure_vault()
    print(f"Secrets vault ready at: {vault_path}")


if __name__ == "__main__":
    main()
