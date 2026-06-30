import asyncio
import os
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from acp import (
    Agent,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent as run_acp_agent,
    text_block,
    update_agent_message,
)
from acp.interfaces import Client
from acp.schema import (
    AudioContentBlock,
    ClientCapabilities,
    EmbeddedResourceContentBlock,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    McpServerStdio,
    ResourceContentBlock,
    SseMcpServer,
    TextContentBlock,
)

from kernel.manifest import Manifest
from kernel.metrics import NullSink
from daemon.brain import brain_tier
from products.chat.session import ChatSession
from products.agent import default_registry, project_root_guard
from products.agent.coordinator import combine_guards
from products.agent.rails import protected_rails_guard
from products.agent.loop import run_agent, AgentStep
from products.chat.app import _session_preamble, _is_framework_scope


class KinoxAgent(Agent):
    _conn: Client
    _session: ChatSession | None = None
    _kinox_root: Path

    def __init__(self):
        super().__init__()
        self._kinox_root = Path(__file__).resolve().parents[2]

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        from kernel.manifest import probe
        manifest = probe()
        cwd_path = Path(cwd)
        
        system_prompt = _session_preamble(self._kinox_root, cwd_path)
        system_prompt += (
            "\n\n### ACP SERVER MODE\n"
            "You are running within an Agent Client Protocol session."
        )
        
        system_prompt += (
            "\n\n### RESIDUAL MEMORY MODE\n"
            "This session uses constant memory. You must end your final response to every turn "
            "with a strict `<residual_state>` block summarizing what you did, what the current "
            "state of the project is, and what you think the user might want to do next. "
            "This summary will be fed back to you as your only memory of the past conversation."
        )

        metrics_dir = cwd_path / ".kinox"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        from kernel.metrics import MetricsSink
        self._session = ChatSession(
            manifest=manifest,
            sink=MetricsSink(metrics_dir / "agent-events.jsonl"),
            cwd=cwd_path,
            system_prompt=system_prompt,
        )
        
        residual_file = cwd_path / ".kinox_residual"
        if residual_file.is_file():
            try:
                saved_state = residual_file.read_text(encoding="utf-8")
                if saved_state.strip():
                    self._session.history.append({"role": "assistant", "content": saved_state})
            except Exception:
                pass
        
        return NewSessionResponse(session_id=uuid.uuid4().hex)

    async def prompt(
        self,
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | AudioContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        if not self._session:
            return PromptResponse(stop_reason="error")
            
        task = ""
        for block in prompt:
            text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
            task += text + "\n"
            
        task = task.strip()
        
        # Get active tier (cloud brain or local fallback)
        tier = brain_tier()
        if not tier and self._session.manifest.local_models:
            tier = self._session.manifest.local_models[0].as_tier()
            
        if not tier:
            return PromptResponse(stop_reason="error")

        steps_q: deque[AgentStep] = deque()
        tokens_q: deque[str] = deque()

        async def drain_queues():
            # Send initial message block
            chunk = update_agent_message(text_block(""))
            await self._conn.session_update(session_id=session_id, update=chunk, source="kinox")

            while not task_future.done() or steps_q or tokens_q:
                # Drain tokens
                if tokens_q:
                    buffer = ""
                    while tokens_q:
                        buffer += tokens_q.popleft()
                    chunk = update_agent_message(text_block(buffer))
                    await self._conn.session_update(session_id=session_id, update=chunk, source="kinox")
                
                # Drain steps (tools)
                if steps_q:
                    while steps_q:
                        step = steps_q.popleft()
                        if step.kind == "tool":
                            msg = f"\n> **Tool:** `{step.name}`\n"
                            chunk = update_agent_message(text_block(msg))
                            await self._conn.session_update(session_id=session_id, update=chunk, source="kinox")
                
                await asyncio.sleep(0.05)

        base_id = uuid.uuid4().hex[:12]
        
        from products.capabilities.registry import CapabilityRegistry
        from products.agent.config import load_ruleset, load_token_budget, load_tool_config
        from products.agent.planner import plan_task
        
        global_path = Path("~/.kinox/config.toml").expanduser()
        global_text = global_path.read_text() if global_path.is_file() else None
        project_path = self._kinox_root / "kinox.toml"
        project_text = project_path.read_text() if project_path.is_file() else None
        profile = os.environ.get("KINOX_PROFILE")

        config_budget = load_token_budget(global_text, project_text, profile=profile)
        ruleset = load_ruleset(global_text, project_text, profile=profile)
        tool_config = load_tool_config(global_text, project_text, profile=profile)

        skills = CapabilityRegistry.from_claude_dir(self._kinox_root / ".claude")
        
        mcp_on = os.environ.get("KINOX_MCP", "1").lower() not in ("0", "off", "false", "no")
        if not tool_config.allow_mcp:
            mcp_on = False
        mcp_config = self._kinox_root / ".claude" / "mcp-servers.json" if mcp_on else None

        def parallel_callback(slices_def: list[dict[str, object]]) -> str:
            from products.agent import Slice, run_parallel
            from products.agent.coordinator import OverlapError, assert_disjoint
            
            _slices = [
                Slice(
                    task=str(s.get("task", "")),
                    owned=[str(p) for p in s.get("owned_paths", [])],
                    label=f"a{i + 1}"
                )
                for i, s in enumerate(slices_def)
            ]
            try:
                assert_disjoint(_slices, self._session.cwd)
            except OverlapError as exc:
                return f"(error: overlap refused - {exc})"
            
            _base_id = uuid.uuid4().hex[:12]
            def make_run() -> object:
                async def run(sl: Slice, guard: object) -> object:
                    plan = await plan_task(sl.task, sink=self._session.sink, task_id=f"{_base_id}:{sl.label}-plan", root=self._session.cwd, registry=registry)
                    return await run_agent(
                        sl.task,
                        tier=tier,
                        registry=registry,
                        sink=self._session.sink,
                        task_id=f"{_base_id}:{sl.label}",
                        guard=guard,
                        preamble=self._session.system_prompt,
                        plan=plan,
                        fallback=None, # Tiers fallback not strictly needed for sub-agents here
                        max_turns=int(os.environ.get("KINOX_MAX_TURNS", "30"))
                    )
                return run
                
            async def do_parallel() -> str:
                # Notify parent client about parallel sub-agents spawning
                sub_agents_list = [{"id": s.label, "task": s.task, "status": "running"} for s in _slices]
                try:
                    await self._conn.ext_notification("session/swarm", {
                        "session_id": session_id,
                        "sub_agents": sub_agents_list
                    })
                except Exception:
                    pass

                res = await run_parallel(_slices, root=self._session.cwd, run=make_run())

                # Notify parent client that sub-agents have finished
                for item in sub_agents_list:
                    item["status"] = "done"
                try:
                    await self._conn.ext_notification("session/swarm", {
                        "session_id": session_id,
                        "sub_agents": sub_agents_list
                    })
                except Exception:
                    pass

                return "\n".join(f"[{s.label}] {r.final_text}" for s, r in zip(_slices, res))

            return asyncio.run(do_parallel())

        # No Y/n prompt: ask_fn=None forces auto-allow or silent failure for guards
        guard = combine_guards(
            project_root_guard(
                self._session.cwd,
                deny_write_subpaths=("projects",) if _is_framework_scope(self._kinox_root, self._session.cwd) else (),
                ruleset=ruleset,
                ask_fn=None, # explicit NO prompt (auto-approve interactive elements)
            ),
            protected_rails_guard(self._session.cwd),
        )

        registry = default_registry(
            self._session.cwd,
            skills=skills,
            allow_bash=tool_config.allow_bash,
            allow_write=tool_config.allow_write,
            mcp_config=mcp_config,
            parallel_callback=parallel_callback,
        )

        plan = await plan_task(
            task,
            sink=self._session.sink,
            task_id=f"{base_id}-plan",
            root=self._session.cwd,
            registry=registry
        )

        task_future = asyncio.create_task(
            run_agent(
                task,
                tier=tier,
                registry=registry,
                sink=self._session.sink,
                task_id=base_id,
                preamble=self._session.system_prompt,
                history=list(self._session.history),
                plan=plan,
                guard=guard,
                max_turns=30,
                spent_offset=self._session.tokens_spent,
                on_step=steps_q.append,
                on_token=tokens_q.append,
            )
        )
        
        drain_future = asyncio.create_task(drain_queues())
        
        # Wait for agent loop and drainer to finish
        result = await task_future
        await drain_future
        
        final_text = getattr(result, "final_text", "")
        if self._session.residual_mode and "<residual_state>" in final_text:
            residual_start = final_text.find("<residual_state>")
            residual_end = final_text.find("</residual_state>")
            if residual_start != -1:
                state_text = final_text[residual_start:residual_end + 17] if residual_end != -1 else final_text[residual_start:]
                self._session.history.clear()
                self._session.history.append({"role": "assistant", "content": state_text})
                try:
                    (self._session.cwd / ".kinox_residual").write_text(state_text, encoding="utf-8")
                except Exception:
                    pass
        else:
            self._session.history.append({"role": "user", "content": task})
            self._session.history.append({"role": "assistant", "content": final_text})
            # keep max pairs check simple
            while len(self._session.history) > 20:
                self._session.history.pop(0)

        self._session.tokens_spent = getattr(result, "tokens_spent", self._session.tokens_spent)

        return PromptResponse(stop_reason="end_turn")


async def main() -> None:
    await run_acp_agent(KinoxAgent())


if __name__ == "__main__":
    asyncio.run(main())
