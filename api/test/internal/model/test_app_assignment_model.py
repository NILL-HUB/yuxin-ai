from uuid import uuid4

from internal.model.app import AppAssignment


class TestAppAssignmentModel:
    def test_should_define_app_assignment_table_and_fields(self):
        assignment = AppAssignment(
            app_id=uuid4(),
            account_id=uuid4(),
            assigned_by=uuid4(),
            status="active",
        )

        assert AppAssignment.__tablename__ == "app_assignment"
        assert assignment.status == "active"
        assert assignment.app_id is not None
        assert assignment.account_id is not None
        assert assignment.assigned_by is not None
        assert hasattr(assignment, "assigned_at")
        assert hasattr(assignment, "revoked_at")

    def test_should_define_unique_assignment_constraint(self):
        indexes = {index.name: index for index in AppAssignment.__table__.indexes}

        assert "app_assignment_app_account_unique_idx" in indexes
        assert indexes["app_assignment_app_account_unique_idx"].unique is True
        assert [column.name for column in indexes["app_assignment_app_account_unique_idx"].columns] == ["app_id", "account_id"]
        assert "app_assignment_account_status_idx" in indexes
        assert [column.name for column in indexes["app_assignment_account_status_idx"].columns] == ["account_id", "status"]
