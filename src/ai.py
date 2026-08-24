"""
ai.py

AI layer of the NovaShop Business Intelligence Assistant.

Main responsibilities:
1. generate_sql()      - natural language question -> SQL
2. validate_sql()      - safety validation before execution
3. summarize_result()  - query result -> short business explanation
4. suggest_chart_type()- simple automatic visualization selection

Uses the Google Gemini API.
Requires GEMINI_API_KEY in the environment / .env file.
"""

import os
import re
import time

import pandas as pd

from .database import get_schema, get_table_columns


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "gemini-3.6-flash"

# Prevent very large AI-generated result sets.
MAX_RESULT_ROWS = 500

# Only send a limited number of rows to Gemini for the business summary.
MAX_ROWS_FOR_SUMMARY = 200

# Retry transient API failures.
API_MAX_RETRIES = 2
API_RETRY_BACKOFF_SECONDS = 1.5

_client = None


# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------

def _get_client():
    """
    Lazily create the Google Gemini client.

    The API key is loaded from the GEMINI_API_KEY environment variable.
    """

    global _client

    if _client is None:
        from google import genai

        api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Create a .env file "
                "(see .env.example) or export it in your shell."
            )

        _client = genai.Client(api_key=api_key)

    return _client


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SQL_SYSTEM_PROMPT = """
You are a business intelligence SQL assistant for NovaShop GmbH,
a German electronics retailer.

You receive the schema of a SQLite database and a business question
in natural language.

Generate a single valid SQLite SELECT query that answers the question.

Rules:

- Use ONLY tables and columns contained in the provided schema.
- Never invent table names or column names.
- Never modify the database.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
  ATTACH, PRAGMA or other database-modifying statements.
- Only SELECT or WITH ... SELECT queries are allowed.
- Unless the question explicitly asks otherwise, use only orders
  where order_status = 'Completed' for revenue, profit and margin
  calculations.
- Revenue = quantity * unit_price.
- Gross profit = quantity * (unit_price - purchase_price).
- Gross margin = gross profit / revenue.
- If the question is ambiguous, for example "best customer",
  use total revenue as the default metric.
- If the question cannot be answered using the provided schema,
  respond with exactly NO_QUERY_POSSIBLE.
  - Use normal plain-text spacing and punctuation.
- Do not use Markdown, italics, bold text, special formatting, or LaTeX.

Output format:

Respond with EXACTLY two lines.

Line 1:
ASSUMPTION: <short note>

Use:
ASSUMPTION: none

when no assumption was necessary.

Line 2:
The raw SQLite SQL query.

If the question cannot be answered, line 2 must be:

NO_QUERY_POSSIBLE

Do not use markdown code fences.
Do not add explanations after the SQL.
"""


SUMMARY_SYSTEM_PROMPT = """
You are a business analyst writing a short answer for a business user.

You will receive:

1. The original business question.
2. The result returned by the SQL query.

Rules:

- Use ONLY information contained in the provided query result.
- Never invent numbers.
- Never introduce facts that are not contained in the result.
- Never invent explanations for why something happened.
- Be concise.
- Use 1-3 sentences.
- Use a professional business tone.
- If the result is empty, clearly state that no matching data was found.
"""


# ---------------------------------------------------------------------------
# SQL Safety
# ---------------------------------------------------------------------------

FORBIDDEN_KEYWORDS = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "REPLACE",
    "VACUUM",
    "REINDEX",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
]


class SQLValidationError(Exception):
    """Raised when generated SQL fails a safety validation rule."""

    pass


_IDENTIFIER_AFTER_FROM_JOIN = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)


_CTE_NAME = re.compile(
    r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,)\s*"
    r"([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(",
    re.IGNORECASE,
)


def _enforce_row_limit(
    sql: str,
    max_rows: int = MAX_RESULT_ROWS,
) -> str:
    """
    Add a LIMIT when the query does not already contain one.

    This prevents a generated query from returning an unnecessarily
    large result set to the Streamlit interface.
    """

    if re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
        return sql

    return f"{sql.rstrip()}\nLIMIT {max_rows}"


def validate_sql(
    sql: str,
    enforce_row_limit: bool = True,
) -> str:
    """
    Validate AI-generated SQL before execution.

    Safety layers:

    1. Query must contain SQL.
    2. Only SELECT or WITH statements are allowed.
    3. Multiple SQL statements are rejected.
    4. Dangerous SQL keywords are rejected.
    5. Referenced physical tables must exist in the database schema.
    6. CTE aliases are allowed.
    7. A row limit is added when necessary.

    The database layer should additionally use a read-only SQLite
    connection as a second safety layer.
    """

    if not sql or not sql.strip():
        raise SQLValidationError("Empty query.")

    cleaned = sql.strip()

    # Remove accidental Markdown fences.
    cleaned = re.sub(
        r"^```sql\s*|^```\s*|```$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # Remove one trailing semicolon.
    cleaned = cleaned.rstrip(";").strip()

    if cleaned.upper() == "NO_QUERY_POSSIBLE":
        return cleaned

    upper = cleaned.upper()

    # Only SELECT / WITH queries.
    if not (
        upper.startswith("SELECT")
        or upper.startswith("WITH")
    ):
        raise SQLValidationError(
            "Query rejected: only SELECT/WITH statements are allowed."
        )

    # Reject stacked SQL statements.
    original_without_final_semicolon = sql.strip().rstrip(";")

    if ";" in original_without_final_semicolon:
        raise SQLValidationError(
            "Query rejected: multiple statements are not allowed."
        )

    # Block dangerous keywords.
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(
            rf"\b{re.escape(keyword)}\b",
            upper,
        ):
            raise SQLValidationError(
                f"Query rejected: forbidden keyword '{keyword}'."
            )

    # Validate referenced tables.
    known_tables = {
        table.lower()
        for table in get_table_columns().keys()
    }

    referenced_tables = {
        table.lower()
        for table in _IDENTIFIER_AFTER_FROM_JOIN.findall(cleaned)
    }

    # WITH aliases are not physical database tables.
    cte_names = {
        name.lower()
        for name in _CTE_NAME.findall(cleaned)
    }

    unknown_tables = (
        referenced_tables
        - known_tables
        - cte_names
    )

    if unknown_tables:
        raise SQLValidationError(
            "Query rejected: references unknown table(s) "
            f"{sorted(unknown_tables)}."
        )

    if enforce_row_limit:
        cleaned = _enforce_row_limit(cleaned)

    return cleaned


# ---------------------------------------------------------------------------
# Gemini API helper
# ---------------------------------------------------------------------------

def _call_with_retry(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
):
    """
    Call Gemini with a small retry mechanism for temporary API errors.
    """

    from google.genai import types

    client = _get_client()

    last_error = None

    for attempt in range(API_MAX_RETRIES + 1):

        try:
            return client.models.generate_content(
                model=MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=max_tokens,
                    temperature=0,
                    thinking_config=types.ThinkingConfig(
                        thinking_level="minimal"
                    ),
                ),
            )

        except Exception as error:
            last_error = error

            if attempt < API_MAX_RETRIES:
                wait_seconds = (
                    API_RETRY_BACKOFF_SECONDS
                    * (attempt + 1)
                )

                time.sleep(wait_seconds)

    raise last_error


# ---------------------------------------------------------------------------
# Natural language -> SQL
# ---------------------------------------------------------------------------

def generate_sql(question: str) -> dict:
    """
    Convert a natural-language business question into validated SQL.

    Returns:

    {
        "sql": "...",
        "assumption": None or "..."
    }

    If the question is ambiguous, Gemini can return an assumption.
    The Streamlit application can display this assumption to the user.
    """

    schema = get_schema()

    user_prompt = (
        f"DATABASE SCHEMA:\n"
        f"{schema}\n\n"
        f"QUESTION:\n"
        f"{question}"
    )

    response = _call_with_retry(
        system_prompt=SQL_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=1200,
    )

    raw = (response.text or "").strip()

    assumption = None

    lines = raw.split("\n", 1)

    if (
        len(lines) == 2
        and lines[0]
        .strip()
        .upper()
        .startswith("ASSUMPTION:")
    ):

        note = lines[0].split(":", 1)[1].strip()

        if note.lower() != "none":
            assumption = note

        raw_sql = lines[1].strip()

    else:
        # Graceful fallback if Gemini does not follow
        # the requested two-line format exactly.
        raw_sql = raw

    validated_sql = validate_sql(raw_sql)

    return {
        "sql": validated_sql,
        "assumption": assumption,
    }


# ---------------------------------------------------------------------------
# Query result -> business explanation
# ---------------------------------------------------------------------------

def summarize_result(
    question: str,
    result_df: pd.DataFrame,
) -> str:
    """
    Convert a query result into a short business-language explanation.

    Gemini only receives the original question and the actual query result.
    """

    if result_df.empty:

        table_str = "(no rows returned)"

    else:

        truncated = result_df.head(
            MAX_ROWS_FOR_SUMMARY
        )

        table_str = truncated.to_csv(
            index=False
        )

        if len(result_df) > MAX_ROWS_FOR_SUMMARY:

            remaining = (
                len(result_df)
                - MAX_ROWS_FOR_SUMMARY
            )

            table_str += (
                f"\n... ({remaining} more rows not shown)"
            )

    user_prompt = (
        f"QUESTION:\n"
        f"{question}\n\n"
        f"QUERY RESULT:\n"
        f"{table_str}"
    )

    response = _call_with_retry(
        system_prompt=SUMMARY_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=600,
    )

    return (response.text or "").strip()


# ---------------------------------------------------------------------------
# Automatic chart suggestion
# ---------------------------------------------------------------------------

def suggest_chart_type(
    df: pd.DataFrame,
) -> str:
    """
    Suggest a simple visualization type.

    Rules:

    - One row + one numeric value -> KPI
    - Time column + numeric value -> line chart
    - Category + numeric value -> bar chart
    - Otherwise -> table
    """

    if df is None or df.empty:
        return "table"

    columns_lower = [
        column.lower()
        for column in df.columns
    ]

    numeric_columns = (
        df
        .select_dtypes(include="number")
        .columns
        .tolist()
    )

    # Single numeric result -> KPI
    if (
        len(df) == 1
        and len(numeric_columns) == 1
        and len(df.columns) <= 2
    ):
        return "kpi"

    # Time series -> line chart
    time_columns = {
        "month",
        "year",
        "order_date",
        "date",
    }

    if (
        any(
            column in time_columns
            for column in columns_lower
        )
        and numeric_columns
    ):
        return "line"

    # Category + number -> bar chart
    non_numeric_columns = [
        column
        for column in df.columns
        if column not in numeric_columns
    ]

    if (
        non_numeric_columns
        and numeric_columns
    ):
        return "bar"

    return "table"