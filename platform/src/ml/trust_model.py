"""
AgentX Platform — Trust Score ML Model
═══════════════════════════════════════
XGBoost-based trust score predictor with formula fallback.

Features:
  - 7-feature input vector (task completion, SLA, endorsements, audit, security, tenure, REP)
  - Gradient-boosted model trained on synthetic + real agent data
  - Fallback to Sprint-2 weighted formula if model unavailable
  - RMSE < 0.05 target on held-out test set

SOURCE: phase5_implementation_plan.md Sprint 4 — Trust Score ML
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Model paths ───────────────────────────────────────────────────────────────

_PLATFORM_ROOT = Path(__file__).parent.parent.parent          # platform/
_MODEL_PATH    = _PLATFORM_ROOT / "models" / "trust_model_v1.json"

# ── Sprint 2 formula weights (fallback) ──────────────────────────────────────

_W_EXEC    = 0.35
_W_SLA     = 0.25
_W_ENDORSE = 0.20
_W_AUDIT   = 0.12
_W_SEC     = 0.08


# ── Feature vector ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TrustFeatures:
    """7-feature input for ML trust model."""
    task_completion_rate: float   # 0.0–1.0 execution success rate
    sla_adherence:        float   # 0.0–1.0 SLA compliance rate
    endorsement_count:    int     # raw peer endorsement count
    audit_completeness:   float   # 0.0–1.0 audit transparency
    security_incidents:   int     # count of security events (0 = clean)
    tenure_days:          int     # days since account creation
    rep_balance:          float   # normalized REP token balance (0–1)

    def to_array(self):
        """Return feature vector as list[float] for XGBoost DMatrix."""
        # Normalize endorsement_count (cap at 100)
        norm_endorse  = min(self.endorsement_count / 100.0, 1.0)
        # Security: 0 incidents = 1.0 (perfect), each incident degrades by 0.2
        security_score = max(0.0, 1.0 - self.security_incidents * 0.2)
        # Tenure: normalize to [0,1] cap at 2 years (730 days)
        norm_tenure   = min(self.tenure_days / 730.0, 1.0)

        return [
            float(self.task_completion_rate),
            float(self.sla_adherence),
            norm_endorse,
            float(self.audit_completeness),
            security_score,
            norm_tenure,
            float(self.rep_balance),
        ]


# ── ML Model ─────────────────────────────────────────────────────────────────

class TrustMLModel:
    """
    XGBoost wrapper for trust score prediction.
    Automatically falls back to the Sprint-2 weighted formula when
    the model file is missing or XGBoost is unavailable.
    """

    def __init__(self, model_path: Path = _MODEL_PATH):
        self._model_path = model_path
        self._model      = None
        self._available  = False

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(self, path: Optional[Path] = None) -> bool:
        """
        Load pre-trained XGBoost model from JSON file.
        Returns True if loaded successfully.
        """
        target = Path(path) if path else self._model_path
        if not target.exists():
            logger.warning("Trust ML model not found at %s — using formula fallback", target)
            return False

        try:
            import xgboost as xgb  # noqa: PLC0415
            booster = xgb.Booster()
            booster.load_model(str(target))
            self._model     = booster
            self._available = True
            logger.info("Trust ML model loaded from %s", target)
            return True
        except Exception as exc:
            logger.warning("Trust ML model load failed (%s) — using formula fallback", exc)
            return False

    def is_available(self) -> bool:
        """True if ML model is loaded and ready."""
        return self._available

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, features: TrustFeatures) -> float:
        """
        Predict trust score ∈ [0.0, 1.0].
        Uses ML model if available, else falls back to weighted formula.
        """
        if self._available and self._model is not None:
            return self._predict_ml(features)
        return self._formula_fallback(features)

    def _predict_ml(self, features: TrustFeatures) -> float:
        """XGBoost inference path."""
        import numpy as np    # noqa: PLC0415
        import xgboost as xgb  # noqa: PLC0415

        X    = np.array([features.to_array()], dtype=np.float32)
        dmat = xgb.DMatrix(X)
        raw  = float(self._model.predict(dmat)[0])
        return round(max(0.0, min(1.0, raw)), 4)

    def _formula_fallback(self, features: TrustFeatures) -> float:
        """
        Sprint-2 weighted formula using mapped feature values.
        Maps the 7-feature input to the 5 canonical trust factors.
        """
        arr                 = features.to_array()
        execution_success   = arr[0]
        sla_compliance      = arr[1]
        peer_endorsements   = arr[2]
        audit_transparency  = arr[3]
        security_record     = arr[4]
        # tenure + rep_balance not used in formula (ignored gracefully)

        raw = (
            execution_success  * _W_EXEC
            + sla_compliance   * _W_SLA
            + peer_endorsements * _W_ENDORSE
            + audit_transparency * _W_AUDIT
            + security_record  * _W_SEC
        )
        return round(max(0.0, min(1.0, raw)), 4)

    # ── Training (generates synthetic bootstrap model) ─────────────────────────

    def train_synthetic(self, output_path: Optional[Path] = None, n_samples: int = 2000) -> Path:
        """
        Generate synthetic training data (using formula as ground truth + noise)
        and train XGBoost model. Saves to output_path (defaults to _MODEL_PATH).
        Used for bootstrapping and CI/CD pipelines.
        Returns path to saved model.
        """
        import numpy as np    # noqa: PLC0415
        import xgboost as xgb  # noqa: PLC0415

        rng = np.random.default_rng(42)

        # Random features
        task_rate    = rng.uniform(0.0, 1.0, n_samples)
        sla_rate     = rng.uniform(0.0, 1.0, n_samples)
        endorse_norm = rng.uniform(0.0, 1.0, n_samples)
        audit        = rng.uniform(0.0, 1.0, n_samples)
        sec_score    = rng.choice([1.0, 0.8, 0.6, 0.4, 0.2, 0.0], n_samples,
                                   p=[0.6, 0.15, 0.1, 0.08, 0.05, 0.02])
        tenure_norm  = rng.uniform(0.0, 1.0, n_samples)
        rep_norm     = rng.uniform(0.0, 1.0, n_samples)

        X = np.column_stack([
            task_rate, sla_rate, endorse_norm, audit, sec_score, tenure_norm, rep_norm,
        ]).astype(np.float32)

        # Ground truth: formula + small noise
        y_clean = (
            task_rate    * _W_EXEC
            + sla_rate   * _W_SLA
            + endorse_norm * _W_ENDORSE
            + audit      * _W_AUDIT
            + sec_score  * _W_SEC
        )
        y = np.clip(y_clean + rng.normal(0, 0.01, n_samples), 0.0, 1.0).astype(np.float32)

        # Split 80/20
        split  = int(0.8 * n_samples)
        dtrain = xgb.DMatrix(X[:split], label=y[:split])
        dval   = xgb.DMatrix(X[split:], label=y[split:])

        params = {
            "objective":    "reg:squarederror",
            "max_depth":    4,
            "eta":          0.1,
            "n_estimators": 200,
            "subsample":    0.8,
            "verbosity":    0,
        }
        model = xgb.train(
            params, dtrain,
            num_boost_round=200,
            evals=[(dval, "val")],
            verbose_eval=False,
        )

        # Validate RMSE
        preds = model.predict(dval)
        rmse  = float(np.sqrt(np.mean((preds - y[split:]) ** 2)))
        logger.info("Trust ML synthetic model RMSE=%.4f (target <0.05)", rmse)

        save_path = output_path or self._model_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(str(save_path))
        logger.info("Trust ML model saved to %s", save_path)
        return save_path


# ── Singleton + auto-load ─────────────────────────────────────────────────────

trust_model = TrustMLModel()
# Attempt to load pre-trained model at import time (silent if missing)
trust_model.load()
