"""Renders email bodies from the Jinja2 files in app/templates/."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

# Loads templates from app/templates. HTML is auto-escaped; a missing variable is an error, not a blank.
_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)

def vnd(amount: int) -> str:
    """Format an amount as Vietnamese dong, e.g. 15000000 -> "15,000,000 ₫"."""
    return f"{amount:,} ₫"

_env.filters["vnd"] = vnd

def render(name: str, **context) -> tuple[str, str]:
    """Render `<name>.txt` and `<name>.html` with the same data. Returns (text, html)."""
    return (_env.get_template(f"{name}.txt").render(**context),
            _env.get_template(f"{name}.html").render(**context))
