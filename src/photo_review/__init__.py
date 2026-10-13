from dotenv import find_dotenv, load_dotenv

from .cli import cli


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    cli()
