"""
AgentX Platform — Retrain Trust Model Job
══════════════════════════════════════════
Celery task: weekly re-training of XGBoost trust score model.

Steps:
  1. Export agent feature data from database
  2. Train XGBoost model on exported data
  3. Validate on holdout set (RMSE < 0.05)
  4. Deploy new model artifact if validation passes

SOURCE: phase5_implementation_plan.md Sprint 4 — Data Pipeline
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from .celery_app import celery_app

logger = logging.getLogger(__name__)

_RMSE_THRESHOLD = 0.05


# ── Export helpers ────────────────────────────────────────────────────────────

async def _export_training_data(conn) -> tuple[list, list]:
    """
    Export agent features + trust scores from DB.
    Returns (X, y) as plain Python lists ready for numpy conversion.
    """
    rows = await conn.fetch(
        """
        SELECT
            a.agent_did,
            COALESCE(tb.execution_success,   0.5) AS task_completion_rate,
            COALESCE(tb.sla_compliance,      0.5) AS sla_adherence,
            COALESCE(tb.peer_endorsements,   0.0) AS endorsement_norm,
            COALESCE(tb.audit_transparency,  0.5) AS audit_completeness,
            COALESCE(tb.security_record,     1.0) AS security_score,
            EXTRACT(DAY FROM NOW() - a.created_at) / 730.0 AS tenure_norm,
            COALESCE(tok.balance / 10000.0,  0.0) AS rep_norm,
            a.trust_score
        FROM agents a
        LEFT JOIN agent_trust_breakdown tb ON tb.agent_did = a.agent_did
        LEFT JOIN token_balances tok ON tok.agent_did = a.agent_did
        WHERE a.status = 'ACTIVE'
        """
    )

    X, y = [], []
    for row in rows:
        X.append([
            float(row["task_completion_rate"]),
            float(row["sla_adherence"]),
            float(row["endorsement_norm"]),
            float(row["audit_completeness"]),
            float(row["security_score"]),
            float(row["tenure_norm"]),
            float(row["rep_norm"]),
        ])
        y.append(float(row["trust_score"]))

    return X, y


# ── Training logic ────────────────────────────────────────────────────────────

async def _run_retrain(min_samples: int = 50) -> dict:
    """
    Core retraining logic (separated for testability).
    Returns result dict with {status, rmse, samples, model_path}.
    """
    import numpy as np            # noqa: PLC0415
    import xgboost as xgb         # noqa: PLC0415

    from ..database       import get_db          # noqa: PLC0415
    from ..ml.trust_model import TrustMLModel, _MODEL_PATH  # noqa: PLC0415

    # 1. Export data
    async with get_db() as conn:
        X_list, y_list = await _export_training_data(conn)

    if len(X_list) < min_samples:
        logger.warning(
            "retrain_trust_model: only %d samples (need %d) — using synthetic bootstrap",
            len(X_list), min_samples,
        )
        m = TrustMLModel()
        path = m.train_synthetic(output_path=_MODEL_PATH)
        m.load(path)
        return {"status": "synthetic", "samples": len(X_list), "model_path": str(path)}

    # 2. Prepare arrays
    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)

    # 3. 80/20 split
    split  = max(int(0.8 * len(X)), 1)
    dtrain = xgb.DMatrix(X[:split], label=y[:split])
    dval   = xgb.DMatrix(X[split:], label=y[split:])

    params = {
        "objective":  "reg:squarederror",
        "max_depth":  4,
        "eta":        0.1,
        "subsample":  0.8,
        "verbosity":  0,
    }
    model = xgb.train(
        params, dtrain,
        num_boost_round=200,
        evals=[(dval, "val")],
        verbose_eval=False,
    )

    # 4. Validate
    preds = model.predict(dval)
    rmse  = float(np.sqrt(np.mean((preds - y[split:]) ** 2)))
    logger.info("retrain_trust_model: RMSE=%.4f (threshold=%.2f)", rmse, _RMSE_THRESHOLD)

    if rmse > _RMSE_THRESHOLD:
        logger.warning(
            "retrain_trust_model: RMSE %.4f > threshold %.2f — model NOT deployed",
            rmse, _RMSE_THRESHOLD,
        )
        return {"status": "validation_failed", "rmse": rmse, "samples": len(X)}

    # 5. Deploy
    _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(_MODEL_PATH))

    # Hot-reload singleton
    from ..ml.trust_model import trust_model  # noqa: PLC0415
    trust_model.load(_MODEL_PATH)

    logger.info("retrain_trust_model: deployed new model (RMSE=%.4f)", rmse)
    return {
        "status":     "deployed",
        "rmse":       rmse,
        "samples":    len(X),
        "model_path": str(_MODEL_PATH),
        "deployed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Celery task ───────────────────────────────────────────────────────────────

@celery_app.task(name="jobs.retrain_trust_model", bind=True, max_retries=1)
def retrain_trust_model(self):
    """
    Celery task: retrain XGBoost trust model on latest agent data.
    Scheduled weekly by Celery Beat.
    """
    try:
        loop   = asyncio.new_event_loop()
        result = loop.run_until_complete(_run_retrain())
        loop.close()
        return result
    except Exception as exc:
        logger.error("retrain_trust_model task failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)
