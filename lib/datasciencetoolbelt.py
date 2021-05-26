from schema import Schema, Or
from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns

ConfigSchema = Schema({
    "seaborn_context": Or("talk", "notebook", "paper", "poster"),
    "savefig": {
        "dir": Path,
        "enable": bool,
    }
})

_config = None

def setup(config):
    global _config
    if _config is not None:
        raise Exception("can only setup once")
    _config = ConfigSchema.validate(config)

    # configure seaborn
    sns.set()
    sns.set_style("whitegrid")
    sns.set_palette(sns.color_palette('muted'))
    sns.set_context(_config["seaborn_context"])

    if not _config["savefig"]["dir"].is_dir():
        raise Exception(f"savefig.dir={config['savefig']['dir']} must be a directory")


def savefig(name: str):
    global _config

    if not _config["savefig"]["enable"]:
        return

    formats = [
        # ("png", 100, ".100dpi.png"),
        # ("png", 200, ".200dpi.png"),
        # ("png", 300, ".300dpi.png"),
        # ("png", 400, ".400dpi.png"),
        ("pdf", 300, ".pdf"),
    ]
    for format, dpi, suffix in formats:
        p = (_config["savefig"]["dir"] / name).with_suffix(suffix)
        plt.savefig(p, format=format, dpi=dpi, pad_inches=0.02, bbox_inches='tight')
