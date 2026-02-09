"""测试调度器模块。"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from src.scheduler import SimpleScheduler, AgentTask, TaskStatus
from src.agents.base import AgentType, AgentResult


class MockAgent:
    """Mock Agent。"""

    def __init__(self, agent_type: AgentType, name: str):
        self.agent_type = agent_type
        self.name = name

    def execute(self, **kwargs):
        """执行任务。"""
        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[{"content": f"来自 {self.name} 的发现"}],
            handoffs_created=0,
        )


class TestSimpleScheduler:
    """测试 SimpleScheduler 类。"""

    def setup_method(self):
        """每个测试方法前的设置。"""
        self.scheduler = SimpleScheduler(max_concurrent=2, timeout=10)

    def test_initialization(self):
        """测试初始化。"""
        assert self.scheduler._max_concurrent == 2
        assert self.scheduler._timeout == 10

    @pytest.mark.asyncio
    async def test_run_single_task(self):
        """测试运行单个任务。"""
        agent = MockAgent(AgentType.SCOUT, "侦察专家")
        task = AgentTask(
            id="test-task-1",
            agent=agent,
            context={"target": "Notion"},
        )

        result = await self.scheduler._run_single_task(task)

        assert task.status == TaskStatus.COMPLETED
        assert task.result is not None
        assert task.started_at is not None
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_run_multiple_tasks(self):
        """测试并发运行多个任务。"""
        tasks = []
        for i in range(3):
            agent = MockAgent(AgentType.SCOUT, f"Agent-{i}")
            task = AgentTask(
                id=f"task-{i}",
                agent=agent,
                context={"target": f"Product-{i}"},
            )
            tasks.append(task)

        result = await self.scheduler.run_tasks(tasks)

        assert result.total_tasks == 3
        assert result.completed_tasks == 3
        assert result.failed_tasks == 0

    @pytest.mark.asyncio
    async def test_task_timeout(self):
        """测试任务超时。"""
        # 创建一个会超时的 Agent
        class SlowAgent:
            agent_type = AgentType.SCOUT
            name = "慢速 Agent"

            def execute(self, **kwargs):
                import time
                time.sleep(5)  # 超过超时时间
                return AgentResult(
                    agent_type="scout",
                    agent_name="慢速",
                    discoveries=[],
                    handoffs_created=0,
                )

        # 使用短超时
        scheduler = SimpleScheduler(max_concurrent=1, timeout=1)
        agent = SlowAgent()
        task = AgentTask(
            id="slow-task",
            agent=agent,
            context={},
        )

        result = await scheduler.run_tasks([task])

        assert result.failed_tasks == 1
        assert task.status == TaskStatus.FAILED
        assert "timed out" in task.error.lower()

    @pytest.mark.asyncio
    async def test_non_retryable_error_no_retry(self):
        """非临时错误不应重试。"""
        class FailingAgent:
            agent_type = AgentType.SCOUT
            name = "失败 Agent"

            def __init__(self):
                self.calls = 0

            def execute(self, **kwargs):
                self.calls += 1
                raise NameError("boom")

        scheduler = SimpleScheduler(max_concurrent=1, timeout=1, max_retries=2, retry_backoff=0)
        agent = FailingAgent()
        task = AgentTask(id="fail-task", agent=agent, context={})

        await scheduler.run_tasks([task])

        assert agent.calls == 1
        assert task.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_retryable_error_retries(self):
        """临时错误应按重试次数执行。"""
        class FlakyAgent:
            agent_type = AgentType.SCOUT
            name = "波动 Agent"

            def __init__(self):
                self.calls = 0

            def execute(self, **kwargs):
                self.calls += 1
                raise ConnectionError("network down")

        scheduler = SimpleScheduler(max_concurrent=1, timeout=1, max_retries=1, retry_backoff=0)
        agent = FlakyAgent()
        task = AgentTask(id="retry-task", agent=agent, context={})

        await scheduler.run_tasks([task])

        assert agent.calls == 2
        assert task.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_collect_results(self):
        """测试收集结果。"""
        tasks = []
        for i in range(2):
            agent = MockAgent(AgentType.SCOUT, f"Agent-{i}")
            task = AgentTask(
                id=f"task-{i}",
                agent=agent,
                context={},
            )
            tasks.append(task)

        await self.scheduler.run_tasks(tasks)

        results = self.scheduler.collect_results(tasks)

        assert "scout" in results
        assert len(results["scout"]) == 2

    def test_get_errors(self):
        """测试获取错误。"""
        tasks = []

        # 添加失败的任务
        task1 = AgentTask(
            id="failed-task",
            agent=MagicMock(),
            context={},
        )
        task1.status = TaskStatus.FAILED
        task1.error = "测试错误"
        task1.agent.agent_type = MagicMock()
        task1.agent.agent_type.value = "scout"
        tasks.append(task1)

        # 添加成功的任务
        task2 = AgentTask(
            id="success-task",
            agent=MagicMock(),
            context={},
        )
        task2.status = TaskStatus.COMPLETED
        task2.agent.agent_type = MagicMock()
        task2.agent.agent_type.value = "scout"
        tasks.append(task2)

        errors = self.scheduler.get_errors(tasks)

        assert len(errors) == 1
        assert errors[0]["task_id"] == "failed-task"
        assert errors[0]["error"] == "测试错误"
