"""OpenHive CLI."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.tree import Tree

from openhive.core.config import AgentConfig, TeamConfig, load_config
from openhive.core.swarm import SwarmExecutionPolicy
from openhive.core.memory import MemoryGraphInMemory, MemoryNode
from openhive.core.message import MessageBusLocal, MessageType
from openhive.core.team import Agent, AgentRole, Team
from openhive.integrations.llm import MiniMaxClient

app = typer.Typer(help="OpenHive - multi-agent collaboration framework")
console = Console()


def _create_llm_client(config: TeamConfig):
    """Create an LLM client."""
    api_key = config.llm.api_key or os.getenv(f"{config.llm.provider.upper()}_API_KEY", "")
    if not api_key:
        console.print(
            "[yellow]Warning: no LLM API key configured; using mock mode.[/yellow]"
        )
        return MockLLMClient()
    return MiniMaxClient(
        api_key=api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        max_tokens=config.llm.max_tokens,
        temperature=config.llm.temperature,
    )


class MockLLMClient:
    """Mock LLM client used when no API key is configured."""

    async def complete(self, prompt: str) -> str:
        await asyncio.sleep(0.1)
        if "decompose" in prompt.lower() or "分解" in prompt:
            return (
                '[{"name": "research_topic", "description": "Research topic context", '
                '"specialist": "research"}, {"name": "analyze_content", '
                '"description": "Analyze core content", "specialist": "analysis"}]'
            )
        return "Mock LLM response."


@app.command()
def init(
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
    force: bool = typer.Option(False, help="Overwrite an existing config"),
) -> None:
    """Initialize a new OpenHive team config."""
    path = Path(config_path)
    if path.exists() and not force:
        console.print(f"[yellow]Config already exists: {config_path}[/yellow]")
        console.print("Use --force to overwrite it.")
        return

    config = TeamConfig(
        name="my-team",
        description="My first OpenHive team",
        agents=[
            AgentConfig(name="orchestrator", role="orchestrator", description="Task planner and coordinator"),
            AgentConfig(name="research", role="specialist", description="Research specialist"),
            AgentConfig(name="analysis", role="specialist", description="Analysis specialist"),
        ],
    )

    import yaml

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(), f, allow_unicode=True, sort_keys=False)

    console.print(f"[green]Created config file: {config_path}[/green]")
    console.print("[dim]Default agents: orchestrator, research, analysis[/dim]")


@app.command()
def status(
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
) -> None:
    """Show team status."""
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config_path}[/red]")
        return

    table = Table(title=f"Team status: {config.name}")
    table.add_column("Name", style="cyan")
    table.add_column("Role", style="magenta")
    table.add_column("Description", style="green")

    for agent in config.agents:
        table.add_row(agent.name, agent.role, agent.description)

    console.print(table)
    console.print(f"\n[dim]LLM: {config.llm.provider} ({config.llm.model})[/dim]")
    if config.enterprise.policy:
        policy = config.enterprise.policy
        console.print(
            "[dim]Enterprise swarm: "
            f"parallelism={policy.parallelism}, "
            f"redundancy={policy.redundancy}, "
            f"risk_threshold={policy.high_risk_threshold}, "
            f"min_chars={policy.min_result_chars}, "
            f"evidence_weight={policy.scorer_evidence_weight:.2f}"
            f"/length_weight={policy.scorer_length_weight:.2f}"
            f"/structure_weight={policy.scorer_structure_weight:.2f}"
            f"/confidence_threshold={policy.winner_confidence_threshold:.2f}"
            f"/max_retries={policy.max_retry_rounds}[/dim]"
        )
    console.print(f"[dim]Redis: {config.redis.host}:{config.redis.port}[/dim]")
    console.print(
        f"[dim]Database: "
        f"{config.database.host}:{config.database.port}/"
        f"{config.database.database}[/dim]"
    )


@app.command()
def agent_add(
    name: str = typer.Option(..., prompt="Agent name"),
    role: AgentRole = typer.Option(AgentRole.SPECIALIST, prompt="Agent role"),
    description: str = typer.Option("", prompt="Agent description"),
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
) -> None:
    """Add an agent to the config."""
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config_path}[/red]")
        return

    agent = AgentConfig(name=name, role=role.value, description=description)
    config.agents.append(agent)

    from openhive.core.config import save_config

    save_config(config, config_path)
    console.print(f"[green]Added agent: {name} ({role.value})[/green]")


@app.command()
def run(
    goal: str = typer.Option(..., prompt="Task goal"),
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
) -> None:
    """Run a goal with the configured team."""
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print("Run first: openhive init")
        raise typer.Exit(1)

    asyncio.run(_run_async(goal, config))


@app.command()
def run_auto(
    goal: str = typer.Option(..., prompt="Task goal"),
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
) -> None:
    """Auto-assemble specialists and run a goal."""
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print("Run first: openhive init")
        raise typer.Exit(1)

    asyncio.run(_run_auto_async(goal, config))


async def _run_async(goal: str, config: TeamConfig) -> None:
    """Run a task asynchronously."""
    from openhive.agent.orchestrator import OrchestratorAgent
    from openhive.agent.specialist import SpecialistAgent
    from typing import Any
    from uuid import UUID
    import hashlib

    console.print(Panel(f"[bold cyan]OpenHive task run[/bold cyan]\n{goal}"))

    # Generate a stable team_id from the config name for cross-command memory.
    team_uuid_str = hashlib.md5(config.name.encode()).hexdigest()[:32]
    team_uuid = UUID(team_uuid_str)

    # Initialize runtime components with file-backed memory.
    memory = MemoryGraphInMemory(persist_path=f".openhive_memory_{config.name}.json")
    await memory.connect()

    message_bus = MessageBusLocal()
    await message_bus.connect()

    # Create the team with the stable UUID.
    team = Team(name=config.name, description=config.description, id=team_uuid)

    # Create the LLM client.
    llm = _create_llm_client(config)

    # Create agent definitions from config.
    agents_map: dict[str, Agent] = {}
    for agent_config in config.agents:
        agent_def = Agent(
            name=agent_config.name,
            role=AgentRole(agent_config.role),
            description=agent_config.description,
        )
        team.add_agent(agent_def)
        agents_map[agent_config.name] = agent_def

    # Create agent instances.
    agent_instances: dict[str, Any] = {}
    for name, agent_def in agents_map.items():
        if agent_def.role == AgentRole.ORCHESTRATOR:
            agent_instances[name] = OrchestratorAgent(
                agent_def=agent_def,
                team=team,
                memory=memory,
                message_bus=message_bus,
                llm_client=llm,
            )
        elif agent_def.role == AgentRole.SPECIALIST:
            specialty = "general"
            if "research" in name.lower():
                specialty = "research"
            elif "analysis" in name.lower():
                specialty = "analysis"
            elif "writing" in name.lower():
                specialty = "writing"

            agent_instances[name] = SpecialistAgent(
                agent_def=agent_def,
                team=team,
                memory=memory,
                message_bus=message_bus,
                llm_client=llm,
                specialty=specialty,
            )

    # Start all agents.
    for agent in agent_instances.values():
        await agent.start()

    policy = SwarmExecutionPolicy.from_mapping(config.enterprise.policy.model_dump())

    # Get the orchestrator.
    orchestrator = agent_instances.get("orchestrator")
    if not orchestrator:
        console.print("[red]Error: config is missing an orchestrator agent[/red]")
        raise typer.Exit(1)

    # Send the task directly to the orchestrator.
    console.print("[dim]Decomposing task...[/dim]")

    try:
        result = await orchestrator.execute_task(
            {"goal": goal, "swarm_policy": policy.to_dict()}
        )
        _display_result(result)
    except Exception as e:
        console.print(f"[red]Execution failed: {e}[/red]")

    # Cleanup.
    for agent in agent_instances.values():
        await agent.stop()
    await message_bus.disconnect()
    await memory.disconnect()


def _display_result(result: dict) -> None:
    """Display an execution result."""
    console.print("\n")

    if not result:
        console.print("[yellow]No result returned[/yellow]")
        return

    tree = Tree("[bold green]Execution result[/bold green]")

    if "summary" in result:
        tree.add(f"Summary: {result['summary']}")

    if "goal" in result:
        tree.add(f"Goal: {result['goal']}")

    if "subtasks" in result:
        subtasks_tree = tree.add("[bold]Subtasks:[/bold]")
        for subtask in result["subtasks"]:
            name = subtask.get("name", "?")
            specialist = subtask.get("specialist", "?")
            desc = subtask.get("description", "")[:50]
            subtasks_tree.add(f"• {name} ({specialist}): {desc}")

    if "results" in result:
        results_tree = tree.add("[bold]Task outputs:[/bold]")
        for r in result["results"]:
            if isinstance(r, dict):
                status_icon = "✓" if r.get("status") == "done" else "✗"
                name = r.get("name", "?")
                results_tree.add(f"{status_icon} {name}")
                if "result" in r:
                    res = r["result"]
                    if isinstance(res, dict):
                        for k, v in res.items():
                                if k not in ("task_name", "specialty", "type"):
                                    val_str = str(v)[:80]
                                    results_tree.add(f"    {k}: {val_str}")

    decisions = result.get("decisions", [])
    if decisions:
        decision_tree = tree.add("[bold]Swarm arbitration:[/bold]")
        for d in decisions:
            if isinstance(d, dict):
                dec = d.get("decision", {})
                if isinstance(dec, dict):
                    task = dec.get("task_name", "?")
                    chosen = dec.get("chosen", "?")
                    confidence = dec.get("winner_confidence", 0.0)
                    attempts = dec.get("attempts", 1)
                    retry_reason = dec.get("retry_reason")
                    routing_notes = dec.get("routing_notes")
                    if isinstance(routing_notes, list) and routing_notes:
                        route_desc = "；".join(str(item) for item in routing_notes)
                    else:
                        route_desc = ""
                    decision_line = (
                        f"{task} -> {chosen} (confidence {confidence:.2f}, "
                        f"attempts {attempts})"
                    )
                    if retry_reason:
                        decision_line += f"（{retry_reason}）"
                    if route_desc:
                        decision_line += f" | routing: {route_desc}"
                    decision_tree.add(decision_line)

    console.print(tree)
    console.print("\n[dim]Team memory saved. Use memory-list to inspect it.[/dim]")


async def _run_auto_async(goal: str, config: TeamConfig) -> None:
    """Auto-assemble a team with TeamAssembler and execute."""
    from openhive.agent.orchestrator import OrchestratorAgent
    from openhive.agent.specialist import SpecialistAgent
    from openhive.core.assembler import TeamAssembler
    from openhive.skills.registry import get_global_registry
    from openhive.runtime.oacp_client import OACPClient
    from typing import Any
    from uuid import UUID
    import hashlib

    console.print(Panel(f"[bold cyan]OpenHive auto-assembled run[/bold cyan]\n{goal}"))

    # Generate a stable team_id.
    team_uuid_str = hashlib.md5(config.name.encode()).hexdigest()[:32]
    team_uuid = UUID(team_uuid_str)

    # Initialize components.
    memory = MemoryGraphInMemory(persist_path=f".openhive_memory_{config.name}.json")
    await memory.connect()

    message_bus = MessageBusLocal()
    await message_bus.connect()

    # Create team.
    team = Team(name=config.name, description=config.description, id=team_uuid)

    # Create the LLM client.
    llm = _create_llm_client(config)

    # Auto-assemble the team with candidate specialists and enterprise policy.
    swarm_policy = SwarmExecutionPolicy.from_mapping(config.enterprise.policy.model_dump())
    assembler = TeamAssembler(
        skill_registry=get_global_registry(),
        candidate_count=swarm_policy.candidate_count,
        department_priorities=config.enterprise.department_pricing,
    )

    console.print("[dim]Analyzing goal and assembling team...[/dim]")
    formation = await assembler.assemble_from_goal(goal, llm_client=llm)

    # Show team formation result.
    console.print(f"\n[green]Team assembled with {len(formation.tasks)} tasks[/green]")
    console.print(f"[dim]{formation.reasoning}[/dim]\n")

    # Runtime bridge: connect external OACP experts such as Hermes/OpenClaw.
    external_executors: dict[str, Any] = {}
    runtime_clients: list[OACPClient] = []

    runtime_bridge = config.enterprise.runtime_bridge
    if runtime_bridge.enabled:
        requested_runtimes = [
            str(name).strip().lower()
            for name in runtime_bridge.runtimes
            if str(name).strip()
        ]

        if not requested_runtimes:
            console.print("[yellow]runtime_bridge is enabled but no runtimes are configured[/yellow]")
        for runtime_kind in dict.fromkeys(requested_runtimes):
            if runtime_kind not in {"openclaw", "hermes", "openhuman"}:
                console.print(
                    f"[yellow]Skipping unsupported runtime_kind={runtime_kind}[/yellow]"
                )
                continue

            client = OACPClient(
                runtime_kind=runtime_kind,
                runtime_name=f"{runtime_kind} runtime",
                hub_url=runtime_bridge.hub_url,
                connect_timeout_seconds=runtime_bridge.connect_timeout_seconds,
            )
            if not await client.connect():
                console.print(
                    f"[yellow]Could not connect runtime={runtime_kind}; skipping it[/yellow]"
                )
                continue

            runtime_clients.append(client)

            async def _make_dispatcher(
                runtime_client: OACPClient,
            ):
                async def _dispatch(task_payload: dict[str, Any]) -> dict[str, Any]:
                    task_id = task_payload.get("execution_id") or task_payload.get("task_id")
                    if not isinstance(task_id, str):
                        task_id = str(task_id)

                    required_capabilities = task_payload.get("required_capabilities", [])
                    if not isinstance(required_capabilities, list):
                        required_capabilities = []

                    return await runtime_client.dispatch_task(
                        task_id=task_id,
                        payload=task_payload,
                        required_capabilities=required_capabilities,
                        timeout_seconds=runtime_bridge.request_timeout_seconds,
                    )

                return _dispatch

            external_executors[runtime_kind] = await _make_dispatcher(client)
            console.print(f"[green]Connected OACP runtime: {runtime_kind}[/green]")

    # Extend candidate pools with external runtimes for redundancy.
    candidate_assignments = {
        task_name: list(candidates)
        for task_name, candidates in formation.candidate_assignments.items()
    }
    if external_executors:
        external_names = list(external_executors.keys())
        for task_name, candidates in candidate_assignments.items():
            merged = list(dict.fromkeys([*candidates, *external_names]))
            candidate_assignments[task_name] = merged

    # Create agents from team formation.
    agent_instances: dict[str, Any] = {}
    specialists_created: set[str] = set()

    for task_name, specialist_name in formation.assignments.items():
        candidates = candidate_assignments.get(task_name, [])
        for candidate_name in [specialist_name, *candidates]:
            if candidate_name in external_executors:
                continue
            if candidate_name in specialists_created:
                continue
            specialists_created.add(candidate_name)

            # Create a specialist agent for enterprise swarm candidate pools.
            agent_def = Agent(
                name=candidate_name,
                role=AgentRole.SPECIALIST,
                description=f"{candidate_name} specialist",
            )
            team.add_agent(agent_def)
            agent_instances[candidate_name] = SpecialistAgent(
                agent_def=agent_def,
                team=team,
                memory=memory,
                message_bus=message_bus,
                llm_client=llm,
                specialty=candidate_name,
            )

    # Show enterprise policy.
    console.print(
        "[dim]Swarm policy: "
        f"parallelism={swarm_policy.parallelism}, "
        f"redundancy={swarm_policy.redundancy}, "
        f"candidates={swarm_policy.candidate_count}[/dim]"
    )
    console.print(
        "[dim]Quality scoring: "
        f"length={swarm_policy.scorer_length_weight:.2f} "
        f"evidence={swarm_policy.scorer_evidence_weight:.2f} "
        f"structure={swarm_policy.scorer_structure_weight:.2f} "
        f"duplicate_threshold={swarm_policy.scorer_duplicate_similarity_threshold:.2f} "
        f"confidence_threshold={swarm_policy.winner_confidence_threshold:.2f} "
        f"max_retries={swarm_policy.max_retry_rounds}[/dim]"
    )

    # Create orchestrator.
    orchestrator_def = Agent(
        name="orchestrator",
        role=AgentRole.ORCHESTRATOR,
        description="Task planner and coordinator",
    )
    team.add_agent(orchestrator_def)
    orchestrator = OrchestratorAgent(
        agent_def=orchestrator_def,
        team=team,
        memory=memory,
        message_bus=message_bus,
        llm_client=llm,
        external_executors=external_executors,
    )
    agent_instances["orchestrator"] = orchestrator

    # Start all agents.
    for agent in agent_instances.values():
        await agent.start()

    # Execute task.
    try:
        result = await orchestrator.execute_task({
            "goal": goal,
            "tasks": [t.__dict__ for t in formation.tasks],
            "assignments": formation.assignments,
            "candidate_assignments": candidate_assignments,
            "swarm_policy": swarm_policy.to_dict(),
        })
        _display_result(result)
    except Exception as e:
        console.print(f"[red]Execution failed: {e}[/red]")
        import traceback
        traceback.print_exc()

    # Cleanup.
    for agent in agent_instances.values():
        await agent.stop()
    await message_bus.disconnect()
    await memory.disconnect()
    for runtime_client in runtime_clients:
        await runtime_client.disconnect()


@app.command()
def discuss(
    question: str = typer.Option(..., prompt="Discussion question"),
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
) -> None:
    """Run a multi-agent discussion."""
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print("Run first: openhive init")
        raise typer.Exit(1)

    asyncio.run(_discuss_async(question, config))


async def _discuss_async(question: str, config: TeamConfig) -> None:
    """Run a multi-agent discussion asynchronously."""
    from openhive.runtime.collaboration import MultiAgentCollaboration

    console.print(Panel(f"[bold cyan]Multi-agent discussion[/bold cyan]\n{question}"))

    llm = _create_llm_client(config)

    collaboration = MultiAgentCollaboration(question)
    collaboration.set_llm_client(llm)

    try:
        result = await collaboration.discuss()

        console.print(Panel(
            f"[bold green]Discussion consensus[/bold green]\n\n{result.consensus[:500]}...",
            title="Final result"
        ))

        if result.agreements:
            console.print("\n[green]Agreements:[/green]")
            for a in result.agreements[:3]:
                console.print(f"  • {a[:100]}")

        if result.disagreements:
            console.print("\n[yellow]Disagreements:[/yellow]")
            for d in result.disagreements:
                console.print(f"  • {d}")

    except Exception as e:
        console.print(f"[red]Discussion failed: {e}[/red]")
        import traceback
        traceback.print_exc()


@app.command()
def swarm_audit(
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
    risk_level: str | None = typer.Option(None, help="Filter by risk level: low/medium/high/critical"),
    max_confidence: float | None = typer.Option(
        None,
        min=0.0,
        max=1.0,
        help="Only show decisions at or below this confidence threshold",
    ),
    alert_confidence: float = typer.Option(
        0.75,
        min=0.0,
        max=1.0,
        help="Low-confidence alert threshold",
    ),
    limit: int = typer.Option(100, help="Maximum rows to display"),
) -> None:
    """Show swarm decision audit metrics and low-confidence alerts."""
    asyncio.run(
        _swarm_audit_async(
            config_path=config_path,
            risk_level=risk_level,
            max_confidence=max_confidence,
            alert_confidence=alert_confidence,
            limit=limit,
        )
    )


def _normalize_risk_level(value: str | None) -> str:
    """Normalize risk level input."""
    return (value or "").strip().lower()


def _build_swarm_audit_rows(
    nodes: list[MemoryNode],
    risk_level: str | None = None,
    max_confidence: float | None = None,
) -> list[dict[str, Any]]:
    """Build swarm audit rows from memory nodes."""
    if risk_level:
        target_risk = _normalize_risk_level(risk_level)
    else:
        target_risk = ""

    rows: list[dict[str, Any]] = []

    for node in nodes:
        decision = node.metadata.get("decision") if isinstance(node.metadata, dict) else None
        if not isinstance(decision, dict):
            continue

        risk = _normalize_risk_level(str(decision.get("risk_level", "")))
        if target_risk and risk != target_risk:
            continue

        try:
            winner_confidence = float(decision.get("winner_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            winner_confidence = 0.0

        if max_confidence is not None and winner_confidence > max_confidence:
            continue

        try:
            attempts = int(decision.get("attempts", 1) or 1)
        except (TypeError, ValueError):
            attempts = 1

        chosen = str(decision.get("chosen") or "")
        retry_reason = decision.get("retry_reason")
        rows.append(
            {
                "task": str(node.metadata.get("task", node.id)),
                "risk_level": risk,
                "chosen": chosen,
                "winner_confidence": winner_confidence,
                "attempts": attempts,
                "routing_notes": (
                    [str(note) for note in (decision.get("routing_notes") or [])]
                    if isinstance(decision.get("routing_notes"), list)
                    else []
                ),
                "retry_reason": retry_reason if isinstance(retry_reason, str) else None,
                "is_retry": bool(retry_reason) or attempts > 1,
                "is_success": bool(chosen) and not retry_reason,
            }
        )

    return rows


async def _swarm_audit_async(
    config_path: str,
    risk_level: str | None,
    max_confidence: float | None,
    alert_confidence: float,
    limit: int,
) -> None:
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config_path}[/red]")
        return

    memory = MemoryGraphInMemory(persist_path=f".openhive_memory_{config.name}.json")
    await memory.connect()

    import hashlib
    team_uuid_str = hashlib.md5(config.name.encode()).hexdigest()[:32]
    from uuid import UUID

    team_uuid = UUID(team_uuid_str)
    nodes = await memory.query(
        team_id=team_uuid,
        type_filter="swarm_decision",
        limit=500,
    )

    rows = _build_swarm_audit_rows(
        nodes,
        risk_level=risk_level,
        max_confidence=max_confidence,
    )
    total = len(rows)
    rows = rows[:limit]
    displayed = len(rows)

    if total == 0:
        console.print("[dim]No swarm decision audit data yet[/dim]")
        await memory.disconnect()
        return

    successful = sum(1 for row in rows if row["is_success"])
    retried = sum(1 for row in rows if row["is_retry"])
    low_confidence = sum(1 for row in rows if row["winner_confidence"] < alert_confidence)

    console.print(
        "[bold cyan]OpenHive swarm audit[/bold cyan] "
        f"| showing {displayed}/{total}, success={successful}, "
        f"retry={retried}, low_confidence={low_confidence}"
    )
    if total:
        console.print(
            "[dim]Rates: "
            f"success={successful / total:.0%}, retry={retried / total:.0%}, "
            f"low_confidence={low_confidence / total:.0%}[/dim]"
        )

    table = Table(title="Decision audit")
    table.add_column("Task")
    table.add_column("Risk")
    table.add_column("Chosen")
    table.add_column("Confidence")
    table.add_column("Attempts")
    table.add_column("Routing")
    table.add_column("Alert")

    for row in rows:
        table.add_row(
            row["task"],
            row["risk_level"],
            row["chosen"] or "-",
            f"{row['winner_confidence']:.2f}",
            str(row["attempts"]),
            ", ".join(row.get("routing_notes", [])),
            row["retry_reason"] or ("retrying" if row["is_retry"] else "-"),
        )

    console.print(table)
    await memory.disconnect()


@app.command()
def hub(
    host: str = typer.Option("0.0.0.0", help="Listen address"),
    port: int = typer.Option(9090, help="Listen port"),
) -> None:
    """Start the AI Agent Club OACP hub."""
    from openhive.runtime.server import HubServer
    import asyncio

    async def run():
        server = HubServer(host=host, port=port)
        await server.start()
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            print("\nShutting down...")
            await server.stop()

    asyncio.run(run())


@app.command()
def memory_list(
    config_path: str = typer.Option("openhive.yaml", help="Config file path"),
    type_filter: str = typer.Option(None, help="Filter by memory type"),
    limit: int = typer.Option(20, help="Maximum rows to display"),
) -> None:
    """Show team memory."""
    asyncio.run(_memory_list_async(config_path, type_filter, limit))


async def _memory_list_async(config_path: str, type_filter: str | None, limit: int) -> None:
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config_path}[/red]")
        return

    memory = MemoryGraphInMemory(persist_path=f".openhive_memory_{config.name}.json")
    await memory.connect()

    import hashlib
    team_uuid_str = hashlib.md5(config.name.encode()).hexdigest()[:32]
    from uuid import UUID
    team_uuid = UUID(team_uuid_str)

    nodes = await memory.query(
        team_id=team_uuid,
        type_filter=type_filter,
        limit=limit,
    )

    if not nodes:
        console.print("[dim]No memory records yet[/dim]")
    else:
        table = Table(title="Team memory")
        table.add_column("Type", style="cyan")
        table.add_column("Content", style="white")
        table.add_column("Time", style="dim")

        for node in nodes:
            table.add_row(
                node.type,
                node.content[:80] + "..." if len(node.content) > 80 else node.content,
                node.created_at.strftime("%H:%M:%S"),
            )

        console.print(table)

    await memory.disconnect()


if __name__ == "__main__":
    app()
