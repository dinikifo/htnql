# HTNQL

**Hierarchical Task Network Query Language**

A Python library for declarative reporting over relational databases using AI planning techniques.

[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## Overview

HTNQL lets you describe *what* data you want without specifying *how* to join tables. It uses Hierarchical Task Network (HTN) planning—a technique from artificial intelligence—to automatically infer table joins from your database schema's foreign key relationships.

```python
from htnql import QueryEngine, SchemaGraph, ReportSpec, MetricSpec

# Define what you want declaratively
spec = ReportSpec(
    name="revenue_by_city",
    metrics=[MetricSpec("SUM(bookings.total_price_cents)", "revenue")],
    group_by=["listings.city"],  # HTNQL figures out the join automatically
    filters=[]
)

# Execute
rows = engine.run_report(spec)
```

## Features

- **Declarative Interface**: Specify metrics, groupings, and filters—not joins
- **Automatic Join Inference**: Foreign keys guide join path discovery
- **HTN Planning Engine**: AI planning techniques for query construction
- **Multiple Execution Modes**: Auto-planned, base SQL, or raw SQL
- **Extensible Agents**: Customize planning strategies via configuration
- **Visual Query Builder**: PySide6 GUI for interactive report building
- **Debug Tracing**: Inspect the planning process step-by-step

## Installation

```bash
# unzip the library
-

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e .
```

## Quick Start

### 1. Connect to a Database

```python
from sqlalchemy import create_engine, MetaData
from htnql import SchemaGraph, QueryEngine

engine = create_engine("sqlite:///your_database.db")
metadata = MetaData()
metadata.reflect(bind=engine)

schema_graph = SchemaGraph(metadata)
query_engine = QueryEngine(engine, schema_graph)
```

### 2. Define a Report

```python
from htnql import ReportSpec, MetricSpec, FilterSpec

spec = ReportSpec(
    name="sales_summary",
    metrics=[
        MetricSpec("SUM(orders.amount_cents)", "total_sales"),
        MetricSpec("COUNT(*)", "order_count"),
    ],
    group_by=["customers.region", "products.category"],
    filters=[
        FilterSpec("orders.status", "=", "completed")
    ],
    limit=100
)
```

### 3. Execute and Inspect

```python
# Simple execution
rows = query_engine.run_report(spec)
for row in rows:
    print(row)

# With planning trace for debugging
rows, trace = query_engine.run_report_with_trace(spec)
for step in trace:
    print(f"{step.task.name} -> {step.method_name}")
```

## Execution Modes

HTNQL supports three execution modes:

| Mode | When to Use | How It Works |
|------|-------------|--------------|
| **Auto** | Default, most cases | Infers tables from columns, builds joins automatically |
| **Base SQL** | Complex subqueries | Your SQL becomes a subquery; metrics/filters applied on top |
| **Raw SQL** | Full control | Executes your SQL directly, bypasses planner |

```python
# Auto mode (default)
spec = ReportSpec(name="auto", metrics=[...], group_by=[...])

# Base SQL mode
spec = ReportSpec(
    name="custom_base",
    base_sql="SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id",
    metrics=[MetricSpec("SUM(amount)", "total")],
    group_by=["region"]
)

# Raw SQL mode
spec = ReportSpec(
    name="raw",
    raw_sql="SELECT region, SUM(amount) FROM orders GROUP BY region"
)
```

## Demo Databases

Three example databases are included:

### Ledger (Double-Entry Accounting)
```bash
cd demos/ledger
python populate.py
```

```python
# Trial balance report
spec = ReportSpec(
    name="trial_balance",
    metrics=[MetricSpec("SUM(entries.amount_cents)", "balance")],
    group_by=["accounts.code", "accounts.name", "accounts.type"]
)
```

### Issues (Bug Tracking)
```bash
cd demos/issues
python populate.py
```

```python
# Average resolution time by priority
spec = ReportSpec(
    name="resolution_time",
    metrics=[MetricSpec("AVG(julianday(closed_at) - julianday(created_at))", "avg_days")],
    group_by=["issues.priority"],
    filters=[FilterSpec("issues.closed_at", "!=", "")]
)
```

### Airbnb (Rental Marketplace)
```bash
cd demos/airbnb
python populate.py
```

```python
# Revenue by city
spec = ReportSpec(
    name="city_revenue",
    metrics=[MetricSpec("SUM(bookings.total_price_cents)", "revenue")],
    group_by=["listings.city"],
    filters=[FilterSpec("bookings.status", "=", "CONFIRMED")]
)
```

## GUI Application

Launch the visual query builder:

```bash
python -m htnql.gui
# or
python gui.py
```

Features:
- Browse database tables and columns
- Build reports visually with metrics, groupings, and filters
- View results in a table
- Inspect HTN planning trace for debugging

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      ReportSpec                             │
│            (metrics, group_by, filters, limit)              │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                     QueryEngine                             │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ SchemaGraph │    │ HTNPlanner  │    │   Agents    │     │
│  │  (FK graph) │    │  (methods)  │    │  (config)   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    SQL + Results                            │
└─────────────────────────────────────────────────────────────┘
```

### HTN Planning Flow

```
AnswerReport
├── ChooseExecutionMode (raw_sql | base_sql | auto)
├── PlanExecution
│   └── PlanAutoSql
│       ├── ValidateSpecStructurally
│       ├── InferTablesFromSpec
│       ├── AnalyzeComplexity
│       ├── FindJoinForest
│       └── BuildSqlFromPlan
└── ExecutePlannedSql
```

## Extending HTNQL

### Custom Agents

Define new planning strategies:

```python
CUSTOM_AGENT = {
    "tasks": {
        "FindJoinForest": {
            "methods": [
                {
                    "name": "MyCustomJoinStrategy",
                    "when": [{"field": "inferred_tables", "op": "size_lte", "value": 3}],
                    "steps": [{"primitive": "FindJoinForest.StrictFK"}]
                }
            ]
        }
    }
}

engine = QueryEngine(db, schema, agent="custom", agents_config={"custom": CUSTOM_AGENT})
```

### Custom Primitives

Add new primitive operations:

```python
from htnql.htn_core import PrimitiveOp
from htnql.planning_primitives import PRIMITIVE_REGISTRY

def my_custom_operation(state, task):
    # Your logic here
    return state

PRIMITIVE_REGISTRY["MyOperation"] = PrimitiveOp(
    task_name="MyOperation",
    apply=my_custom_operation
)
```

## API Reference

### Core Classes

| Class | Description |
|-------|-------------|
| `ReportSpec` | Declarative report specification |
| `MetricSpec` | Aggregate expression (expr + alias) |
| `FilterSpec` | WHERE predicate (column + op + value) |
| `SchemaGraph` | Graph of tables and FK relationships |
| `QueryEngine` | Main entry point for query execution |

### QueryEngine Methods

```python
# Execute report, return rows
rows = engine.run_report(spec)

# Execute with planning trace
rows, trace = engine.run_report_with_trace(spec)
```

### Filter Operators

| Operator | SQL Equivalent |
|----------|----------------|
| `=` | `column = value` |
| `!=` | `column != value` |
| `<`, `>`, `<=`, `>=` | Comparisons |
| `IN` | `column IN (...)` |
| `LIKE` | `column LIKE pattern` |

## Project Structure

```
htnql/
├── htnql/                  # Core library
│   ├── __init__.py
│   ├── report_spec.py      # ReportSpec, MetricSpec, FilterSpec
│   ├── schema_graph.py     # SchemaGraph, FKEdge
│   ├── query_engine.py     # QueryEngine
│   ├── htn_core.py         # HTNPlanner, Task, Method, PrimitiveOp
│   ├── planning_state.py   # PlanningState
│   ├── planning_domain_basic.py
│   ├── planning_primitives.py
│   ├── agent_dsl.py
│   ├── builtin_agents.py
│   ├── shape_suggestion.py
│   └── gui.py              # PySide6 GUI
├── demos/                  # Example databases
│   ├── ledger/
│   ├── issues/
│   └── airbnb/
├── examples/               # Usage examples
├── tests/                  # Test suite
├── docs/                   # Documentation
├── requirements.txt
├── setup.py
└── README.md
```

## Requirements

- Python 3.10+
- SQLAlchemy 2.0+
- PySide6 (for GUI, optional)

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## AI-assistance disclosure

This project was created by a human author with significant assistance from
an AI coding assistant (OpenAI’s ChatGPT / GPT-5.1 Thinking).

The AI was used for:

- Brainstorming the architecture and feature set.
- Iterating on the interpreter logic and JSON runtime design.
- Helping refine the GUI bridge and example scripts.
- Producing and polishing documentation like this README.

All code and decisions were reviewed and accepted by a human before being committed.

## License

This project is released into the public domain under [The Unlicense](LICENSE). You are free to copy, modify, publish, use, compile, sell, or distribute this software for any purpose, commercial or non-commercial, and by any means.

## Acknowledgments

HTNQL draws inspiration from:
- HTN planning research in artificial intelligence
- Declarative query interfaces like GraphQL and PRQL
- The SQLAlchemy project for database abstraction
