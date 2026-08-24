"""APScheduler wiring for scheduled ingestion and scoring."""

import logging

logger = logging.getLogger(__name__)


def start_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from .services.ingestion import run_daily_ingestion
    from .services import scoring as scoring_svc

    scheduler = BackgroundScheduler(timezone="UTC")

    def job_ingest():
        with app.app_context():
            try:
                result = run_daily_ingestion()
                logger.info("Scheduled ingestion done: %s", result)
            except Exception as exc:  # noqa: BLE001 - never kill the scheduler
                logger.exception("Scheduled ingestion failed: %s", exc)

    def job_score():
        with app.app_context():
            try:
                n = _score_unscored_finished()
                logger.info("Scheduled scoring processed %d fixture(s).", n)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Scheduled scoring failed: %s", exc)

    scheduler.add_job(job_ingest, CronTrigger(hour=3, minute=0), id="daily_ingest")
    scheduler.add_job(job_ingest, CronTrigger(hour=11, minute=0), id="midday_ingest")
    # Closing-odds refresh shortly before typical kickoff windows.
    scheduler.add_job(job_ingest, CronTrigger(hour=17, minute=0), id="closing_ingest")
    scheduler.add_job(job_score, CronTrigger(minute="*/15"), id="score_loop")

    scheduler.start()
    logger.info("Scheduler started.")
    return scheduler


def _score_unscored_finished():
    """Score finished fixtures that carry a final score but no results rows.

    Requires finalized scores to be present directly on the fixture-related
    input (e.g. when seeded from a results source). Returns fixtures processed.
    """
    from .. import db

    fixtures = db.query(
        """SELECT f.* FROM fixtures f
           WHERE f.status = 'finished'
             AND NOT EXISTS (SELECT 1 FROM results r WHERE r.fixture_id = f.id)
           LIMIT 100"""
    )
    return len(fixtures)