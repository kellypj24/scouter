"""Unit tests for src/agent/query_agent.py."""

from unittest.mock import AsyncMock, MagicMock

import duckdb
import pytest

from src.agent.providers.base import LLMError
from src.agent.query_agent import _FALLBACK_SQL, QueryAgent, SQLResponse
from src.data.schema import ColumnSchema, ModelSchema, SchemaContext


def _make_model(name: str, domain: str, cols: list[str]) -> ModelSchema:
    """Helper: build a ModelSchema with the given column names."""
    return ModelSchema(
        name=name,
        domain=domain,
        description="",
        columns=[ColumnSchema(name=c, dtype="VARCHAR") for c in cols],
    )


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


# ── Fixtures shared by the _validate_schema guard tests ───────────────────────


@pytest.fixture
def sector_fund_schema():
    """SchemaContext that includes mart_sector_fundamentals."""
    return SchemaContext(
        models=[
            _make_model(
                "mart_sector_fundamentals",
                "sector",
                [
                    "sector",
                    "avg_ytd_return_ew",
                    "avg_mtd_return_ew",
                    "avg_volatility_20d",
                    "avg_sharpe_20d",
                    "avg_drawdown_from_52w_high",
                    "median_ytd_return",
                    "pct_constituents_positive_ytd",
                    "ticker_count",
                    "total_market_cap",
                    "avg_market_cap",
                ],
            )
        ]
    )


@pytest.fixture
def screener_and_risk_schema():
    """SchemaContext that includes both mart_equity_screener and mart_risk_profile."""
    return SchemaContext(
        models=[
            _make_model(
                "mart_equity_screener",
                "equity",
                ["ticker", "sector", "ytd_return", "volatility_20d", "sharpe_20d"],
            ),
            _make_model(
                "mart_risk_profile",
                "risk",
                [
                    "ticker",
                    "sector",
                    "drawdown_from_52w_high",
                    "volatility_pctile_in_sector",
                    "sharpe_pctile_in_sector",
                    "volatility_pctile_market",
                    "sharpe_pctile_market",
                ],
            ),
        ]
    )


@pytest.fixture
def sector_fund_agent(mock_provider, conn, sector_fund_schema):
    return QueryAgent(provider=mock_provider, conn=conn, schema_context=sector_fund_schema)


@pytest.fixture
def risk_agent(mock_provider, conn, screener_and_risk_schema):
    return QueryAgent(provider=mock_provider, conn=conn, schema_context=screener_and_risk_schema)


# ── Guard 1: mart_sector_fundamentals — no time dimension ─────────────────────


class TestValidateSchemaGuard1SectorFundamentals:
    def test_bare_year_col_raises_error(self, sector_fund_agent):
        sql = (
            "SELECT year, sector, avg_ytd_return_ew "
            "FROM main_sector.mart_sector_fundamentals "
            "WHERE year = 2024"
        )
        errors = sector_fund_agent._validate_schema(sql)
        assert any("time-dimension" in e for e in errors)

    def test_bare_date_col_raises_error(self, sector_fund_agent):
        sql = (
            "SELECT date, sector FROM main_sector.mart_sector_fundamentals "
            "WHERE date >= '2024-01-01'"
        )
        errors = sector_fund_agent._validate_schema(sql)
        assert any("time-dimension" in e for e in errors)

    def test_bare_month_col_raises_error(self, sector_fund_agent):
        sql = "SELECT month, sector FROM main_sector.mart_sector_fundamentals"
        errors = sector_fund_agent._validate_schema(sql)
        assert any("time-dimension" in e for e in errors)

    def test_bare_quarter_col_raises_error(self, sector_fund_agent):
        sql = "SELECT quarter, sector FROM main_sector.mart_sector_fundamentals"
        errors = sector_fund_agent._validate_schema(sql)
        assert any("time-dimension" in e for e in errors)

    def test_valid_snapshot_query_no_error(self, sector_fund_agent):
        sql = (
            "SELECT sector, avg_ytd_return_ew "
            "FROM main_sector.mart_sector_fundamentals "
            "ORDER BY avg_ytd_return_ew DESC"
        )
        errors = sector_fund_agent._validate_schema(sql)
        assert not any("time-dimension" in e for e in errors)

    def test_no_false_positive_without_sector_fund_table(self, agent):
        # year column in an unrelated query should not trigger Guard 1.
        sql = "SELECT year FROM test_data"
        errors = agent._validate_schema(sql)
        assert not any("time-dimension" in e for e in errors)


# ── Guard 2: _pctile_in_sector on wrong table ─────────────────────────────────


class TestValidateSchemaGuard2PctileWrongTable:
    def test_unqualified_pctile_col_from_screener_raises_error(self, risk_agent):
        sql = "SELECT ticker, volatility_pctile_in_sector FROM main_equity.mart_equity_screener"
        errors = risk_agent._validate_schema(sql)
        assert any("mart_risk_profile" in e for e in errors)

    def test_sharpe_pctile_col_from_screener_raises_error(self, risk_agent):
        sql = "SELECT ticker, sharpe_pctile_in_sector FROM main_equity.mart_equity_screener"
        errors = risk_agent._validate_schema(sql)
        assert any("mart_risk_profile" in e for e in errors)

    def test_qualified_pctile_on_screener_alias_raises_error(self, risk_agent):
        sql = (
            "SELECT s.ticker, s.volatility_pctile_in_sector "
            "FROM main_equity.mart_equity_screener AS s"
        )
        errors = risk_agent._validate_schema(sql)
        assert any("mart_risk_profile" in e for e in errors)

    def test_pctile_from_risk_profile_no_error(self, risk_agent):
        sql = "SELECT ticker, volatility_pctile_in_sector FROM main_risk.mart_risk_profile"
        errors = risk_agent._validate_schema(sql)
        assert not any("mart_risk_profile" in e for e in errors)

    def test_no_false_positive_without_screener_table(self, risk_agent):
        # A pctile column referenced on mart_risk_profile (correct table) should
        # not trigger Guard 2 even though screener is in the schema context.
        sql = "SELECT ticker, volatility_pctile_in_sector FROM main_risk.mart_risk_profile"
        errors = risk_agent._validate_schema(sql)
        # Guard 2 error specifically mentions "Percentile-within-sector columns".
        assert not any("Percentile-within-sector" in e for e in errors)


# ── Guard 3: avg_drawdown* on mart_risk_profile ───────────────────────────────


class TestValidateSchemaGuard3AvgDrawdownWrongTable:
    def test_unqualified_avg_drawdown_from_risk_profile_raises_error(self, risk_agent):
        sql = "SELECT sector, avg_drawdown FROM main_risk.mart_risk_profile GROUP BY sector"
        errors = risk_agent._validate_schema(sql)
        # Guard message includes the exact correct query as a template.
        assert any("avg_drawdown_from_52w_high" in e for e in errors)
        assert any("Correct query" in e for e in errors)

    def test_avg_drawdown_variant_name_raises_error(self, risk_agent):
        # avg_drawdown_pct, avg_drawdown_52w — any avg_drawdown_* prefix triggers.
        sql = "SELECT sector, avg_drawdown_52w FROM main_risk.mart_risk_profile GROUP BY sector"
        errors = risk_agent._validate_schema(sql)
        assert any("avg_drawdown_from_52w_high" in e for e in errors)

    def test_qualified_avg_drawdown_on_risk_alias_raises_error(self, risk_agent):
        sql = "SELECT r.sector, r.avg_drawdown FROM main_risk.mart_risk_profile AS r"
        errors = risk_agent._validate_schema(sql)
        assert any("avg_drawdown_from_52w_high" in e for e in errors)

    def test_per_ticker_drawdown_column_no_error(self, risk_agent):
        # drawdown_from_52w_high is the real per-ticker column — should not fire.
        sql = (
            "SELECT ticker, drawdown_from_52w_high "
            "FROM main_risk.mart_risk_profile "
            "ORDER BY drawdown_from_52w_high ASC LIMIT 10"
        )
        errors = risk_agent._validate_schema(sql)
        assert not any("avg_drawdown_from_52w_high" in e for e in errors)

    def test_avg_function_alias_no_error(self, risk_agent):
        # AVG(col) AS avg_drawdown — avg_drawdown is an alias, not a Column node.
        sql = (
            "SELECT sector, AVG(drawdown_from_52w_high) AS avg_drawdown "
            "FROM main_risk.mart_risk_profile "
            "GROUP BY sector"
        )
        errors = risk_agent._validate_schema(sql)
        assert not any("avg_drawdown_from_52w_high" in e for e in errors)

    def test_no_false_positive_without_risk_profile_table(self, sector_fund_agent):
        # Guard 3 should not fire when mart_risk_profile is not in the query.
        sql = "SELECT sector, avg_drawdown_from_52w_high FROM main_sector.mart_sector_fundamentals"
        errors = sector_fund_agent._validate_schema(sql)
        assert not any("mart_sector_fundamentals" in e and "avg_drawdown" in e for e in errors)


# ── Guard 4 (classify_domains): sector-name expansion ────────────────────────
# (formerly labelled Guard 3 in the classify_domains context)


class TestClassifyDomainsSectorNameExpansion:
    def test_sector_name_expands_to_sector_domain(self, agent):
        # "healthcare" is in _SECTOR_NAME_KEYWORDS; "performance" triggers equity.
        # sector domain should be added even though no short sector keyword matched.
        domains = agent.classify_domains("Healthcare sector performance this year")
        assert "sector" in domains
        assert "equity" in domains

    def test_technology_triggers_sector_expansion(self, agent):
        # "sharpe" → risk; "technology" should add sector via expansion.
        domains = agent.classify_domains("What is the average Sharpe ratio in Technology?")
        assert "risk" in domains
        assert "sector" in domains

    def test_financials_triggers_sector_expansion(self, agent):
        # "drawdown" → risk; "financials" contains "financial" substring → sector.
        domains = agent.classify_domains("Show drawdown for Financials stocks")
        assert "risk" in domains
        assert "sector" in domains

    def test_no_expansion_without_financial_keywords(self, agent):
        # "technology" alone (no financial keyword) → return None, not ["core", "sector"].
        domains = agent.classify_domains("technology data")
        assert domains is None

    def test_expansion_does_not_duplicate_sector(self, agent):
        # "sector" keyword already fires sector domain; guard should not add a duplicate.
        domains = agent.classify_domains("sector volatility in Technology")
        assert domains.count("sector") == 1

    def test_core_always_first_after_expansion(self, agent):
        domains = agent.classify_domains("Healthcare stock returns")
        assert domains[0] == "core"
