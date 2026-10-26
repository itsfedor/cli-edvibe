import pathlib

from setuptools import setup, find_packages

_here = pathlib.Path(__file__).parent
_long = (_here / "README.md").read_text(encoding="utf-8")


setup(
    name="cli-edvibe",
    version="1.0.0",
    description="Unofficial CLI for edvibe.com: lessons, homework and materials over the reverse-engineered WebSocket RPC",
    long_description=_long,
    long_description_content_type="text/markdown",
    author="Fedor Molodtsov",
    url="https://github.com/itsfedor/cli-edvibe",
    license="AGPL-3.0-only",
    packages=find_packages(include=["cli_edvibe*"]),
    python_requires=">=3.9",
    install_requires=["requests>=2.28", "websocket-client>=1.6", "click>=8.0"],
    entry_points={
        "console_scripts": [
            "cli-edvibe=cli_edvibe.edvibe_cli:cli",
            # legacy name (pre-1.0), kept as an alias so existing scripts keep working
            "cli-anything-edvibe=cli_edvibe.edvibe_cli:cli",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Operating System :: OS Independent",
    ],
)
