from .pipeline_runner import run_pipeline_job

if __name__ == "__main__":
    print(run_pipeline_job(trigger_source="cli"))
