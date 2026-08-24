"""Registry of prediction models.

Each entry is (model_version, predict_fn). predict_fn(fixture, db_path=...)
must return a dict with at least a "probabilities" key shaped like:
    {"1X2": {"home": .., "draw": .., "away": ..},
     "OU_2.5": {"over": .., "under": ..},
     "BTTS": {"yes": .., "no": ..}}

To add a new model:
    1. Write predict_fn(fixture, db_path=None) -> {...} somewhere in this package.
    2. Import it below and append (your_model_version_string, predict_fn) to MODELS.
Nothing else in the app needs to change - the fixture page, the prediction
form, and scoring all already loop over whatever's registered here.
"""

from .runner import compute_model_prediction, MODEL_VERSION as ELO_POISSON_VERSION

MODELS = [
    (ELO_POISSON_VERSION, compute_model_prediction),
    # Add future models here, e.g.:
    # ("market_implied_v1", compute_market_implied_prediction),
    # ("dixon_coles_v1", compute_dixon_coles_prediction),
]


def compute_all(fixture, db_path=None):
    """Run every registered model against this fixture, tagged with its
    registry model_version (not whatever the function happens to set
    internally - the registry is the single source of truth for naming)."""
    out = []
    for model_version, predict_fn in MODELS:
        result = predict_fn(fixture, db_path=db_path)
        result["model_version"] = model_version
        out.append(result)
    return out


def get_model(model_version):
    """Look up a single registered model by its version string."""
    for version, predict_fn in MODELS:
        if version == model_version:
            return predict_fn
    return None
