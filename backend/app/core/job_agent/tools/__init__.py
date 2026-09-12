from app.core.job_agent.tools.data_loader import load_excel_data
from app.core.job_agent.tools.db_writer import db_writer
from app.core.job_agent.tools.dedup import deduplicate_jobs
from app.core.job_agent.tools.embedder import job_embedder
from app.core.job_agent.tools.job_extractor import job_extractor
from app.core.job_agent.tools.portrait_builder import portrait_builder
from app.core.job_agent.tools.pre_cleaner import clean_job_data
from app.core.job_agent.tools.quality_judge import quality_judge
from app.core.job_agent.tools.report_summarizer import report_summarizer
from app.core.job_agent.tools.url_fetcher import url_fetcher
from app.core.job_agent.tools.url_safety import url_safety_check
from app.core.job_agent.tools.web_collector import web_collector

__all__ = [
    "clean_job_data",
    "db_writer",
    "deduplicate_jobs",
    "job_embedder",
    "job_extractor",
    "load_excel_data",
    "portrait_builder",
    "quality_judge",
    "report_summarizer",
    "url_fetcher",
    "url_safety_check",
    "web_collector",
]

JOB_AGENT_TOOLS = [
    load_excel_data,
    clean_job_data,
    deduplicate_jobs,
    quality_judge,
    url_safety_check,
    url_fetcher,
    job_extractor,
    portrait_builder,
    job_embedder,
    db_writer,
    web_collector,
    report_summarizer,
]
