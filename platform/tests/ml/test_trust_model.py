"""
Tests — Trust Score ML Model
══════════════════════════════
Verifies XGBoost prediction, formula fallback, and model lifecycle.
XGBoost and model I/O are mocked to avoid training overhead in CI.
"""
import sys
import types
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from src.ml.trust_model import TrustFeatures, TrustMLModel, _W_EXEC, _W_SLA, _W_ENDORSE, _W_AUDIT, _W_SEC


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def model():
    """Fresh model instance with no loaded ML model."""
    m = TrustMLModel()
    m._model     = None
    m._available = False
    return m


class _FakeArray(list):
    def __getitem__(self, index):
        return super().__getitem__(index)


@pytest.fixture
def fake_ml_modules():
    fake_numpy = types.ModuleType("numpy")
    fake_numpy.float32 = float
    fake_numpy.bool_ = bool   # pytest.approx uses np.bool_ internally
    fake_numpy.array = lambda values, dtype=None: values
    fake_numpy.isscalar = lambda value: not isinstance(value, (list, tuple, dict, set))

    fake_xgboost = types.ModuleType("xgboost")

    class FakeDMatrix:
        def __init__(self, values):
            self.values = values

    fake_xgboost.DMatrix = FakeDMatrix
    fake_xgboost.Booster = MagicMock()

    with patch.dict(sys.modules, {"numpy": fake_numpy, "xgboost": fake_xgboost}):
        yield fake_xgboost


@pytest.fixture
def high_trust_features():
    return TrustFeatures(
        task_completion_rate=0.95,
        sla_adherence=0.90,
        endorsement_count=80,
        audit_completeness=0.88,
        security_incidents=0,
        tenure_days=400,
        rep_balance=0.75,
    )


@pytest.fixture
def low_trust_features():
    return TrustFeatures(
        task_completion_rate=0.10,
        sla_adherence=0.15,
        endorsement_count=0,
        audit_completeness=0.20,
        security_incidents=5,
        tenure_days=10,
        rep_balance=0.05,
    )


# ── Feature vector tests ──────────────────────────────────────────────────────

class TestTrustFeatures:
    def test_to_array_length(self, high_trust_features):
        arr = high_trust_features.to_array()
        assert len(arr) == 7

    def test_all_floats(self, high_trust_features):
        arr = high_trust_features.to_array()
        assert all(isinstance(v, float) for v in arr)

    def test_endorsement_normalized(self):
        f = TrustFeatures(
            task_completion_rate=0.5, sla_adherence=0.5,
            endorsement_count=200,  # >100 → capped at 1.0
            audit_completeness=0.5, security_incidents=0,
            tenure_days=100, rep_balance=0.5,
        )
        arr = f.to_array()
        assert arr[2] == 1.0   # endorsement_norm capped at 1.0

    def test_security_incidents_degrade_score(self):
        clean = TrustFeatures(
            task_completion_rate=0.5, sla_adherence=0.5,
            endorsement_count=0, audit_completeness=0.5,
            security_incidents=0, tenure_days=100, rep_balance=0.5,
        )
        dirty = TrustFeatures(
            task_completion_rate=0.5, sla_adherence=0.5,
            endorsement_count=0, audit_completeness=0.5,
            security_incidents=3, tenure_days=100, rep_balance=0.5,
        )
        assert clean.to_array()[4] > dirty.to_array()[4]

    def test_tenure_normalized(self):
        f = TrustFeatures(
            task_completion_rate=0.5, sla_adherence=0.5,
            endorsement_count=0, audit_completeness=0.5,
            security_incidents=0, tenure_days=1000,  # >730 → capped at 1.0
            rep_balance=0.5,
        )
        assert f.to_array()[5] == 1.0


# ── Model availability tests ──────────────────────────────────────────────────

class TestModelAvailability:
    def test_is_available_false_when_not_loaded(self, model):
        assert model.is_available() is False

    def test_is_available_true_when_loaded(self, model):
        model._model     = MagicMock()
        model._available = True
        assert model.is_available() is True

    def test_load_returns_false_when_file_missing(self, model, tmp_path):
        result = model.load(tmp_path / "nonexistent.json")
        assert result is False
        assert model.is_available() is False

    def test_load_returns_true_when_file_exists(self, model, tmp_path, fake_ml_modules):
        fake_model_path = tmp_path / "trust_model.json"
        fake_model_path.write_text("{}")  # non-empty file

        mock_booster = MagicMock()
        with patch.object(fake_ml_modules, "Booster", return_value=mock_booster) as mock_cls:
            result = model.load(fake_model_path)

        assert result is True
        assert model.is_available() is True


# ── Formula fallback tests ────────────────────────────────────────────────────

class TestFormulaFallback:
    def test_perfect_agent_scores_near_1(self, model):
        f = TrustFeatures(
            task_completion_rate=1.0, sla_adherence=1.0,
            endorsement_count=100, audit_completeness=1.0,
            security_incidents=0, tenure_days=730, rep_balance=1.0,
        )
        score = model._formula_fallback(f)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_zero_agent_scores_zero(self, model):
        f = TrustFeatures(
            task_completion_rate=0.0, sla_adherence=0.0,
            endorsement_count=0, audit_completeness=0.0,
            security_incidents=0, tenure_days=0, rep_balance=0.0,
        )
        # security_incidents=0 → security_score=1.0 → contributes _W_SEC
        score = model._formula_fallback(f)
        assert score == pytest.approx(_W_SEC, abs=0.001)

    def test_weights_sum_to_one(self):
        total = _W_EXEC + _W_SLA + _W_ENDORSE + _W_AUDIT + _W_SEC
        assert total == pytest.approx(1.0)

    def test_fallback_used_when_model_unavailable(self, model, low_trust_features):
        score = model.predict(low_trust_features)
        assert 0.0 <= score <= 1.0


# ── ML prediction tests ───────────────────────────────────────────────────────

class TestMLPrediction:
    def test_prediction_in_bounds(self, model, high_trust_features, fake_ml_modules):
        """Score must always be ∈ [0, 1]."""
        mock_booster = MagicMock()
        mock_booster.predict.return_value = _FakeArray([0.85])
        model._model     = mock_booster
        model._available = True

        score = model.predict(high_trust_features)
        assert 0.0 <= score <= 1.0

    def test_high_features_higher_score_than_low(self, model, high_trust_features, low_trust_features):
        high_score = model._formula_fallback(high_trust_features)
        low_score  = model._formula_fallback(low_trust_features)
        assert high_score > low_score

    def test_ml_path_called_when_model_available(self, model, high_trust_features, fake_ml_modules):
        mock_booster = MagicMock()
        mock_booster.predict.return_value = _FakeArray([0.77])
        model._model     = mock_booster
        model._available = True

        score = model.predict(high_trust_features)
        mock_booster.predict.assert_called_once()
        assert score == pytest.approx(0.77, abs=0.001)

    def test_prediction_clamped_above_1(self, model, high_trust_features, fake_ml_modules):
        mock_booster = MagicMock()
        mock_booster.predict.return_value = _FakeArray([1.5])  # Out of range
        model._model     = mock_booster
        model._available = True
        assert model.predict(high_trust_features) <= 1.0

    def test_prediction_clamped_below_0(self, model, low_trust_features, fake_ml_modules):
        mock_booster = MagicMock()
        mock_booster.predict.return_value = _FakeArray([-0.2])  # Out of range
        model._model     = mock_booster
        model._available = True
        assert model.predict(low_trust_features) >= 0.0
