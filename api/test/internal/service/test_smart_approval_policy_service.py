from types import SimpleNamespace

from internal.model.tool_governance_entity import ToolGovernancePolicy
from internal.service.smart_approval_policy_service import SmartApprovalPolicyService


class _FakeQuery:
    def __init__(self, policy):
        self._policy = policy

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if self._policy is None:
            return None
        if not self._policy.enabled or self._policy.require_confirmation:
            return None
        return self._policy


class _FakeSession:
    def __init__(self, policy):
        self._policy = policy

    def query(self, model):
        assert model is ToolGovernancePolicy
        return _FakeQuery(self._policy)


class _FakeDb:
    def __init__(self, policy):
        self.session = _FakeSession(policy)


def _policy(**overrides):
    base = {
        "tool_name": "run_os_task",
        "enabled": True,
        "require_confirmation": False,
        "risk_level": "high",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_auto_approve_when_policy_marks_not_require_confirmation():
    service = SmartApprovalPolicyService(db=_FakeDb(_policy()))

    assert service.should_auto_approve("run_os_task") is True


def test_does_not_auto_approve_when_no_policy():
    service = SmartApprovalPolicyService(db=_FakeDb(None))

    assert service.should_auto_approve("run_os_task") is False


def test_does_not_auto_approve_dangerous_policy():
    service = SmartApprovalPolicyService(
        db=_FakeDb(_policy(risk_level="dangerous"))
    )

    assert service.should_auto_approve("run_os_task") is False


def test_does_not_auto_approve_when_require_confirmation_true():
    service = SmartApprovalPolicyService(
        db=_FakeDb(_policy(require_confirmation=True))
    )

    assert service.should_auto_approve("run_os_task") is False


def test_does_not_auto_approve_dangerous_container_command():
    service = SmartApprovalPolicyService(db=_FakeDb(_policy()))

    assert (
        service.should_auto_approve(
            "run_os_task",
            tool_input={"command": "docker run --privileged -it ubuntu bash"},
        )
        is False
    )


def test_does_not_auto_approve_podman_root_mount():
    service = SmartApprovalPolicyService(db=_FakeDb(_policy()))

    assert (
        service.should_auto_approve(
            "run_os_task",
            tool_input={"command": "podman run -v /:/host ubuntu"},
        )
        is False
    )


def test_auto_approves_safe_container_command():
    service = SmartApprovalPolicyService(db=_FakeDb(_policy()))

    assert (
        service.should_auto_approve(
            "run_os_task",
            tool_input={"command": "docker ps"},
        )
        is True
    )


def test_contains_dangerous_container_command():
    assert SmartApprovalPolicyService.contains_dangerous_container_command(
        "docker run --network host nginx"
    ) is True
    assert SmartApprovalPolicyService.contains_dangerous_container_command(
        "podman exec --cap-add=ALL app sh"
    ) is True
    assert SmartApprovalPolicyService.contains_dangerous_container_command(
        "docker run -p 8080:80 nginx"
    ) is False
