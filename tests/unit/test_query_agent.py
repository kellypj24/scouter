"""Unit tests for src/agent/query_agent.py."""

from unittest.mock import AsyncMock, MagicMock

import duckdb
import pytest

from src.agent.providers.base import LLMError
from src.agent.query_agent import _FALLBACK_SQL, QueryAgent, SQLResponse
from src.data.schema import ColumnSchema, ModelSchema, SchemaContext


@pytest.fixture
def schema_context():
    return SchemaContext(
        models=[
            ModelSchema(
                name="mart_equity_screener",
                domain="equity",
                description="Equity screener",
                columns=[
                    ColumnSchema(name="ticker", dtype="VARCHAR"),
                    ColumnSchema(name="ytd_return", dtype="DOUBLE"),
                ],
            )
        ]
    )


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE test_data (ticker VARCHAR, ytd_return DOUBLE)")
    c.execute("INSERT INTO test_data VALUES ('AAPL', 0.15), ('MSFT', 0.20)")
    yield c
    c.close()


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.complete_structured = AsyncMock(
        return_value=SQLResponse(
            sql="SELECT ticker, ytd_return FROM test_data ORDER BY ytd_return DESC LIMIT 10",
            explanation="Returns top performers",
        )
    )
    return provider


@pytest.fixture
def agent(mock_provider, conn, schema_context):
    return QueryAgent(provider=mock_provider, conn=conn, schema_context=schema_context)


class TestClassifyDomains:
    def test_sector_keyword(self, agent):
        domains = agent.classify_domains("which sector has highest rotation?")
        assert "sector" in domains
        assert "core" in domains

    def test_risk_keyword(self, agent):
        domains = agent.classify_domains("show me drawdown and sharpe ratio")
        assert "risk" in domains

    def test_equity_keyword(self, agent):
        domains = agent.classify_domains("top performing stocks by momentum")
        assert "equity" in domains

    def test_no_match_returns_none(self, agent):
        domains = agent.classify_domains("hello world")
        assert domains is None

    def test_multiple_domains(self, agent):
        domains = agent.classify_domains("compare sector volatility and beta")
        assert "sector" in domains
        assert "risk" in domains
        assert "core" in domains

    def test_always_prepends_core(self, agent):
        domains = agent.classify_domains("show me sector performance")
        assert domains[0] == "core"


class TestValidateSQL:
    def test_valid_select(self, agent):
        sql = "SELECT ticker FROM test_data"
        assert agent._validate_sql(sql) == sql

    def test_strips_trailing_semicolon(self, agent):
        result = agent._validate_sql("SELECT 1;")
        assert not result.endswith(";")

    def test_blocks_insert(self, agent):
        with pytest.raises(ValueError, match="blocked statement"):
            agent._validate_sql("INSERT INTO test_data VALUES ('X', 0.1)")

    def test_blocks_drop(self, agent):
        with pytest.raises(ValueError, match="blocked statement"):
            agent._validate_sql("DROP TABLE test_data")

    def test_blocks_create(self, agent):
        with pytest.raises(ValueError, match="blocked statement"):
            agent._validate_sql("CREATE TABLE foo (id INTEGER)")

    def test_blocks_delete(self, agent):
        with pytest.raises(ValueError, match="blocked statement"):
            agent._validate_sql("DELETE FROM test_data WHERE ticker = 'AAPL'")

    def test_rejects_non_select(self, agent):
        with pytest.raises(ValueError, match="not a SELECT"):
            agent._validate_sql("SHOW TABLES")

    def test_case_insensitive_blocking(self, agent):
        with pytest.raises(ValueError):
            agent._validate_sql("insert into foo values (1)")


class TestExecute:
    def test_returns_query_result_and_df(self, agent):
        result, df = agent._execute("SELECT ticker, ytd_return FROM test_data")
        assert result.row_count == 2
        assert "ticker" in result.columns
        assert len(df) == 2

    def test_sql_stored_in_result(self, agent):
        sql = "SELECT ticker FROM test_data LIMIT 1"
        result, _ = agent._execute(sql)
        assert result.sql == sql


class TestRun:
    async def test_happy_path(self, agent):
        result, df = await agent.run("What are the top performing stocks?")
        assert result.row_count == 2
        assert len(df) == 2

    async def test_llm_failure_uses_fallback(self, mock_provider, conn, schema_context):
        mock_provider.complete_structured = AsyncMock(side_effect=LLMError("timeout"))
        # Fallback SQL references mart_equity_screener which doesn't exist in test conn —
        # create a stand-in so execution succeeds
        conn.execute("CREATE SCHEMA main_equity")
        conn.execute(
            "CREATE TABLE main_equity.mart_equity_screener "
            "(ticker VARCHAR, company_name VARCHAR, sector VARCHAR, "
            "ytd_return DOUBLE, volatility_20d DOUBLE, sharpe_20d DOUBLE)"
        )
        conn.execute(
            "INSERT INTO main_equity.mart_equity_screener VALUES ('AAPL','Apple','Tech',0.1,0.2,1.5)"
        )
        agent = QueryAgent(provider=mock_provider, conn=conn, schema_context=schema_context)
        result, df = await agent.run("show me something")
        assert result.sql == _FALLBACK_SQL

    async def test_retries_with_wider_schema_on_first_failure(
        self, mock_provider, conn, schema_context
    ):
        good_response = SQLResponse(
            sql="SELECT ticker FROM test_data LIMIT 1",
            explanation="ok",
        )
        mock_provider.complete_structured = AsyncMock(
            side_effect=[LLMError("first attempt fails"), good_response]
        )
        agent = QueryAgent(provider=mock_provider, conn=conn, schema_context=schema_context)
        result, df = await agent.run("What is the top stock?")
        assert mock_provider.complete_structured.call_count == 2
        assert result.row_count == 1
