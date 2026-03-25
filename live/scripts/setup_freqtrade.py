"""
Setup script for Freqtrade environment.

Creates necessary directories, symlinks the Freqtrade generic 
strategy file into the user_data/strategies folder, and prints instructions.
"""
import os
import shutil
from pathlib import Path

from loguru import logger


def setup_freqtrade():
    base_dir = Path(__file__).parent.parent
    user_data = base_dir / "user_data"
    
    # Create required freqtrade directories
    dirs_to_create = [
        user_data / "backtest_results",
        user_data / "data",
        user_data / "hyperopts",
        user_data / "logs",
        user_data / "strategies",
    ]
    
    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created directory: {d}")

    # Symlink or Copy sonicr_ft.py 
    src_strategy = base_dir.parent / "strategies" / "freqtrade" / "sonicr_ft.py"
    dst_strategy = user_data / "strategies" / "sonicr_strategy.py"

    if dst_strategy.exists():
        dst_strategy.unlink()

    try:
        # Try symlink first
        os.symlink(src_strategy, dst_strategy)
        logger.info(f"Symlinked {src_strategy.name} -> {dst_strategy}")
    except OSError:
        # Fallback to copy on Windows if symlink privilege is missing
        shutil.copy2(src_strategy, dst_strategy)
        logger.info(f"Copied {src_strategy.name} -> {dst_strategy}")

    print("\n" + "="*50)
    print("✅ Freqtrade Live Environment Setup Complete!")
    print("="*50)
    print("Next steps:")
    print("1. Edit live/user_data/config.json with your API keys.")
    print("2. (Optional) Edit config/strategies/sonicr_strategy.yaml to adjust SonicR parameters.")
    print("3. Run: cd live && docker compose up -d")
    print("4. Check logs: docker compose logs -f freqtrade")


if __name__ == "__main__":
    setup_freqtrade()
