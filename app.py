"""
app.py
NovaShop AI Business Intelligence Assistant - Streamlit front end.

Flow for the natural-language section:
  user question -> src.ai.generate_sql() -> src.ai.validate_sql()
  -> src.database.execute_query() -> src.ai.suggest_chart_type()
  -> src.visualizations.build_chart() -> src.ai.summarize_result()
"""

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from src import analytics, ai, database, visualizations

load_dotenv()

st.set_page_config(page_title="NovaShop BI Assistant", page_icon="📊", layout="wide")


# Cache expensive DB round-trips so re-typing in the text box (which
# reruns the whole script on every keystroke in Streamlit) doesn't
# re-execute five SQL queries against the database every time.
@st.cache_data(ttl=300)
def cached_kpis():
    return database.get_kpis()


@st.cache_data(ttl=300)
def cached_revenue_by_month():
    return analytics.revenue_by_month()


@st.cache_data(ttl=300)
def cached_revenue_by_category():
    return analytics.revenue_by_category()


@st.cache_data(ttl=300)
def cached_top_products(limit=10):
    return analytics.top_products(limit)


@st.cache_data(ttl=300)
def cached_revenue_by_segment():
    return analytics.revenue_by_segment()

# ---------------------------------------------------------------- styling --
st.markdown("""
<style>
    .kpi-box {padding: 1rem; border-radius: 0.5rem; background: #0e1117;
              border: 1px solid #262730;}
    .stChatMessage {background: transparent;}
</style>
""", unsafe_allow_html=True)

st.title("📊 NovaShop AI Business Intelligence Assistant")
st.caption(
    "Ask business questions in plain English. The assistant turns them into "
    "SQL, runs it against the NovaShop database, and explains the result."
)

if not os.path.exists(database.DB_PATH):
    st.error(
        "Database not found. Run `python scripts/generate_data.py` and then "
        "`python scripts/create_database.py` first (see README)."
    )
    st.stop()

# --------------------------------------------------------------- KPI row --
kpis = cached_kpis()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Revenue", f"€{kpis['revenue']:,.0f}")
c2.metric("Gross Profit", f"€{kpis['profit']:,.0f}")
c3.metric("Completed Orders", f"{kpis['orders']:,}")
c4.metric("Customers", f"{kpis['customers']:,}")

st.divider()

# ---------------------------------------------------------- static charts --
# Reuses the same chart builders as the NL assistant below (src/visualizations)
# instead of duplicating px.* calls, so the two code paths can't drift apart.
st.subheader("Revenue Development")
monthly = cached_revenue_by_month()
st.plotly_chart(visualizations.build_line_chart(monthly), use_container_width=True)

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Revenue by Category")
    cat_df = cached_revenue_by_category()
    st.plotly_chart(visualizations.build_bar_chart(cat_df), use_container_width=True)

with col_b:
    st.subheader("Top 10 Products")
    top_df = cached_top_products(10)[["product_name", "revenue"]]
    st.plotly_chart(
        visualizations.build_bar_chart(top_df, horizontal=True),
        use_container_width=True,
    )

st.subheader("Revenue by Customer Segment")
seg_df = cached_revenue_by_segment()
st.plotly_chart(visualizations.build_pie_chart(seg_df), use_container_width=True)

st.divider()

# --------------------------------------------------------- NL assistant --
st.subheader("💬 Ask your business data")

example_questions = [
    "Which product category generated the highest revenue in 2025?",
    "How did monthly revenue develop in 2025?",
    "What are our 10 most valuable customers?",
    "Which category has the highest gross margin?",
    "Which products have the highest return rate?",
]
question = st.selectbox(
    "Try an example or type your own below:",
    [""] + example_questions,
    format_func=lambda x: x if x else "— choose an example —",
)
typed_question = st.text_input(
    "Or ask your own question",
    value=question if question else "",
    placeholder="e.g. Which cities generate the most revenue?",
)

if st.button("Analyze", type="primary") and typed_question.strip():
    q = typed_question.strip()

    if not os.environ.get("GEMINI_API_KEY"):
        st.error(
            "GEMINI_API_KEY is not set. Add it to a `.env` file in the "
            "project root (see `.env.example`) and restart the app."
        )
        st.stop()

    with st.spinner("Generating SQL..."):
        try:
            gen = ai.generate_sql(q)
        except ai.SQLValidationError as e:
            st.error(f"The generated query was rejected for safety reasons: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Could not generate SQL: {e}")
            st.stop()

    sql = gen["sql"]

    if sql.strip().upper() == "NO_QUERY_POSSIBLE":
        st.warning(
            "This question can't be answered with the data available in "
            "NovaShop's database (e.g. it may ask about information the "
            "schema doesn't contain)."
        )
        st.stop()

    if gen["assumption"]:
        st.info(f"ℹ️ Assumption made to answer this question: {gen['assumption']}")

    with st.spinner("Running query..."):
        try:
            result_df = database.execute_query(sql)
        except Exception as e:
            st.error(f"Query execution failed: {e}")
            st.code(sql, language="sql")
            st.stop()

    with st.spinner("Interpreting results..."):
        try:
            summary = ai.summarize_result(q, result_df)
        except Exception as e:
            summary = None
            st.warning(f"Could not generate a business summary: {e}")

    st.markdown("#### AI Answer")
    if summary:
        st.success(summary)

    if not result_df.empty:
        chart_type = ai.suggest_chart_type(result_df)
        if chart_type == "kpi":
            val = result_df.iloc[0, -1]
            st.metric(result_df.columns[-1].replace("_", " ").title(), f"{val:,.2f}")
        elif chart_type in ("line", "bar"):
            fig = visualizations.build_chart(result_df, chart_type)
            if fig is not None:
                st.markdown("#### Visualization")
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Result Table")
        st.dataframe(result_df, use_container_width=True)
    else:
        st.info("The query returned no rows.")

    with st.expander("Generated SQL"):
        st.code(sql, language="sql")

st.divider()
st.caption(
    "NovaShop GmbH is a fictional company. All data is synthetically "
    "generated for demonstration purposes. Built with Python, SQLite, "
    "Streamlit, Plotly, and Claude."
)
