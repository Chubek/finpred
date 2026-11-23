"""Share the production GrammarEmbed selection with direct consumer builds."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from on1x_grammar import flags
