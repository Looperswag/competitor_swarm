"""Motif miner tests."""

import pytest

from src.analysis.motif_miner import MotifMiner
from src.core import phase_executor as phase_executor_module
from src.environment import StigmergyEnvironment

if phase_executor_module.SIGNALS_AVAILABLE:
    from src.schemas.signals import (
        Actionability,
        Dimension,
        Sentiment,
        Signal,
        SignalType,
    )


@pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_motif_miner_returns_traceable_insights_for_cross_agent_topic(tmp_path):
    env = StigmergyEnvironment(cache_path=str(tmp_path))
    env.begin_run("run-motif", clear=True)

    signals = [
        Signal(
            id="sig-1",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.MARKET,
            evidence="pricing strategy affects enterprise conversion and churn",
            confidence=0.82,
            strength=0.72,
            sentiment=Sentiment.NEUTRAL,
            actionability=Actionability.SHORT_TERM,
            author_agent="market",
        ),
        Signal(
            id="sig-2",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.TECHNICAL,
            evidence="pricing complexity increases integration and billing burden",
            confidence=0.78,
            strength=0.68,
            sentiment=Sentiment.NEGATIVE,
            actionability=Actionability.SHORT_TERM,
            author_agent="technical",
            references=["sig-1"],
        ),
        Signal(
            id="sig-3",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.UX,
            evidence="pricing onboarding clarity improves activation for teams",
            confidence=0.8,
            strength=0.7,
            sentiment=Sentiment.POSITIVE,
            actionability=Actionability.INFORMATIONAL,
            author_agent="experience",
            references=["sig-1"],
        ),
    ]
    for signal in signals:
        env.add_signal(signal)

    claims = [
        {
            "claim_id": "claim-red-1",
            "side": "red",
            "evidence_signal_ids": ["sig-1", "sig-2"],
        },
        {
            "claim_id": "claim-blue-1",
            "side": "blue",
            "evidence_signal_ids": ["sig-1", "sig-3"],
        },
    ]

    insights, traces = MotifMiner(env).mine(claims=claims, limit=5)

    assert insights
    assert traces
    assert all("motif_type" in insight for insight in insights)
    assert all(insight.get("evidence_signal_ids") for insight in insights)
    assert all(trace.get("signal_ids") for trace in traces)
