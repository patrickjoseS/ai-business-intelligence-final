"""
visualizations.py
Plotly chart builders. Kept deliberately simple (a handful of rules,
not a general-purpose auto-viz engine) per the project's Phase 10 scope.
"""

import pandas as pd
import plotly.express as px

NOVA_COLORS = px.colors.sequential.Teal


def _first_numeric_col(df: pd.DataFrame) -> str:
    return df.select_dtypes(include="number").columns[0]


def _first_non_numeric_col(df: pd.DataFrame) -> str:
    numeric = set(df.select_dtypes(include="number").columns)
    for c in df.columns:
        if c not in numeric:
            return c
    return df.columns[0]


def build_line_chart(df: pd.DataFrame, title: str = ""):
    x_col = _first_non_numeric_col(df)
    y_col = _first_numeric_col(df)
    fig = px.line(df.sort_values(x_col), x=x_col, y=y_col, markers=True, title=title)
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10))
    return fig


def build_bar_chart(df: pd.DataFrame, title: str = "", horizontal: bool = False):
    x_col = _first_non_numeric_col(df)
    y_col = _first_numeric_col(df)
    df_sorted = df.sort_values(y_col, ascending=horizontal)
    if horizontal:
        fig = px.bar(df_sorted, x=y_col, y=x_col, orientation="h", title=title,
                      color=y_col, color_continuous_scale=NOVA_COLORS)
    else:
        fig = px.bar(df_sorted, x=x_col, y=y_col, title=title,
                      color=y_col, color_continuous_scale=NOVA_COLORS)
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), coloraxis_showscale=False)
    return fig


def build_pie_chart(df: pd.DataFrame, title: str = ""):
    x_col = _first_non_numeric_col(df)
    y_col = _first_numeric_col(df)
    fig = px.pie(df, names=x_col, values=y_col, title=title, hole=0.4,
                 color_discrete_sequence=NOVA_COLORS)
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10))
    return fig


def build_chart(df: pd.DataFrame, chart_type: str, title: str = ""):
    """Dispatch to the right builder based on ai.suggest_chart_type()."""
    if chart_type == "line":
        return build_line_chart(df, title)
    if chart_type == "bar":
        return build_bar_chart(df, title, horizontal=len(df) > 6)
    if chart_type == "pie":
        return build_pie_chart(df, title)
    return None
