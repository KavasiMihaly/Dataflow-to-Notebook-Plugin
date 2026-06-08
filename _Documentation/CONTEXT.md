# Fabric Dataflow Migration Toolkit — Context

The domain language for migrating Power BI Dataflow Gen1 definitions into Microsoft Fabric medallion notebooks. This glossary pins the terms the plugin's agents, skills, and config share, so the same concept isn't named three ways across the codebase.

## Language

**Engine**:
The compute substrate a generated notebook targets — either distributed Spark or a single-node Python interpreter. Selected once per migration via the `notebook_engine` toggle (`pyspark | python`).
_Avoid_: runtime, kernel, language, compute (for this concept).

**PySpark notebook**:
A generated notebook that runs on a Fabric Spark cluster (`synapse_pyspark` kernel). The default engine; suited to larger / distributed workloads.
_Avoid_: Spark notebook (in config values), Synapse notebook.

**Python notebook**:
A generated notebook that runs on Fabric's single-node Python runtime (`jupyter` kernel, `microsoft.language_group: "jupyter_python"`), using polars / duckdb / delta-rs instead of Spark. Chosen for low-volume workloads.
_Avoid_: pure-Python notebook, pandas notebook, non-Spark notebook.
