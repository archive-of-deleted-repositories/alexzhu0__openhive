"""Unit tests for core.team"""

from openhive.core.team import Agent, AgentRole, AgentState, Team


def test_team_create():
    """测试团队创建"""
    team = Team(name="test-team", description="test")
    assert team.name == "test-team"
    assert len(team.agents) == 0


def test_team_add_agent():
    """测试添加 Agent"""
    team = Team(name="test-team")
    agent = Agent(name="test-agent", role=AgentRole.SPECIALIST)

    team.add_agent(agent)
    assert len(team.agents) == 1
    assert team.get_agent("test-agent") == agent


def test_team_remove_agent():
    """测试移除 Agent"""
    team = Team(name="test-team")
    agent = Agent(name="test-agent", role=AgentRole.SPECIALIST)
    team.add_agent(agent)

    team.remove_agent(agent.id)
    assert len(team.agents) == 0


def test_team_get_agents_by_role():
    """测试按角色筛选 Agent"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    team.add_agent(Agent(name="spec1", role=AgentRole.SPECIALIST))
    team.add_agent(Agent(name="spec2", role=AgentRole.SPECIALIST))

    assert len(team.get_agents_by_role(AgentRole.SPECIALIST)) == 2
    assert team.orchestrator.name == "orch"
