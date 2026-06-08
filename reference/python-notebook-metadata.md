# Python notebook metadata (Fabric jupyter kernel) — canonical template source

**Engine:** `python` (single-node polars / duckdb / delta-rs)
**Confirmed empirically** from a real Fabric Python notebook exported by the user
(Slice 0, 2026-06-07; research §8.1). This is the **authoritative** metadata
block every Python-engine builder and the utilities-notebook template must emit.

> If you are generating a `.ipynb` for `engine=python`, copy the metadata block
> below verbatim (substituting the lakehouse-binding placeholders). Do **not**
> use the PySpark `synapse_pyspark` kernel — Fabric would run the notebook as the
> wrong type.

## The discriminator

Fabric decides a notebook is a **Python** notebook (not PySpark) from **two**
signals, which must agree:

1. `metadata.kernel_info.name == "jupyter"`
2. `metadata.microsoft.language_group == "jupyter_python"`

Set **both**; do not rely on one alone. The structure hook does not check the
kernel today, but the pipeline validator (Slice 6) positively asserts
`microsoft.language_group == "jupyter_python"` for the Python engine.

| Field | PySpark (today) | Python (this engine) |
|---|---|---|
| `kernel_info.name` | `synapse_pyspark` | `jupyter` |
| `kernelspec.name` / `display_name` | `synapse_pyspark` / `Synapse PySpark` | `jupyter` / `Jupyter` |
| `microsoft.language_group` | (absent) | `jupyter_python` |
| `language_info.name` | `python` | `python` |
| `dependencies.lakehouse` | present | **identical shape** |

## Confirmed metadata block (copy verbatim; fill the lakehouse placeholders)

```json
{
  "kernel_info": { "name": "jupyter", "jupyter_kernel_name": "python3.11" },
  "kernelspec": { "name": "jupyter", "display_name": "Jupyter" },
  "language_info": { "name": "python" },
  "microsoft": { "language": "python", "language_group": "jupyter_python" },
  "nteract": { "version": "nteract-front-end@1.0.0" },
  "spark_compute": {
    "compute_id": "/trident/default",
    "session_options": { "conf": { "spark.synapse.nbs.session.timeout": "1200000" } }
  },
  "dependencies": {
    "lakehouse": {
      "known_lakehouses": [ { "id": "<lakehouse-id>" } ],
      "default_lakehouse": "<lakehouse-id>",
      "default_lakehouse_name": "<lakehouse-name>",
      "default_lakehouse_workspace_id": "<workspace-id>"
    }
  }
}
```

The top-level notebook envelope uses `"nbformat": 4`, `"nbformat_minor": 5`.

## Notes for builders / template authors

- **`dependencies.lakehouse` is shape-identical to PySpark** — the existing
  lakehouse-binding logic ports unchanged; only the kernel / `microsoft` block
  differs between engines. Bind the **silver** lakehouse for silver notebooks and
  the **bronze** lakehouse for bronze notebooks, exactly as the PySpark path does.
- **`spark_compute` + `nteract` blocks appear even on a Python notebook** —
  Fabric adds them on export. They are harmless residue for the `jupyter` kernel.
  We mirror exactly what Fabric emits rather than stripping them (lowest-risk
  choice; the open micro-question on whether stripping `spark_compute` is safe is
  deferred to the Slice 3 `fab`-deploy round-trip).
- `jupyter_kernel_name` is **informational** — the deploy honors the workspace
  default if the runtime version differs (the real export showed `python3.12`; we
  template `python3.11` per the documented Fabric default, and Fabric will adjust).
- No local absolute paths anywhere in generated metadata — only lakehouse IDs,
  names, and workspace IDs (all non-path identifiers).
