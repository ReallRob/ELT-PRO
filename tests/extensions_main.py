"""Load external packages from extensions/site-packages and print a DataFrame."""

from pathlib import Path
import sys


def default_site_packages():
    """Find the external site-packages directory for source and frozen runs."""
    if getattr(sys, "frozen", False):
        # Onefile builds extract __file__ into a temporary directory. The exe
        # itself stays in the distributable folder beside extensions/.
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parents[1]
    return app_dir / "extensions" / "site-packages"


def main(site_packages=None):
    site_packages = Path(site_packages or default_site_packages()).resolve()
    if not site_packages.is_dir():
        raise SystemExit(f"Extensions site-packages directory not found: {site_packages}")

    # Put external packages before PyInstaller's internal import locations.
    sys.path.insert(0, str(site_packages))

    import openpyxl
    import pandas as pd
    import selenium
    from selenium.webdriver.common.by import By

    df = pd.DataFrame({"value": [2, 3]})
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "loaded from extensions"

    print(df)
    print(f"openpyxl cell: {workbook.active['A1'].value}")
    print(f"selenium: {selenium.__version__}, By.ID={By.ID}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
