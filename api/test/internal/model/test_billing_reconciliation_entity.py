from internal.model.billing import BillingUsageEvent, BillingReconciliation


def test_usage_event_columns():
    keys = BillingUsageEvent.__table__.columns.keys()
    for col in ("task_id", "model_id", "source_type", "input_tokens", "output_tokens",
                "estimated_credits", "actual_credits", "cost_credits", "billing_basis",
                "is_estimated", "created_at"):
        assert col in keys, col


def test_reconciliation_columns():
    keys = BillingReconciliation.__table__.columns.keys()
    for col in ("task_id", "account_id", "estimated_credits", "actual_credits",
                "cost_credits", "diff_credits", "status", "alert_flags"):
        assert col in keys, col