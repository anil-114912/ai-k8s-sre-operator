"""AI SRE sidecar agent entry point.

Starts three concurrent loops:
  1. Log tailer — reads new log lines from the configured file(s)
  2. Error detector — matches lines against patterns, records metrics
  3. Report loop — every report_interval_secs, sends an APM report to the operator

Usage (as container command):
    python -m agent.main

Or directly:
    python agent/main.py
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from agent.config import AgentConfig
from agent.error_detector import ErrorDetector
from agent.log_tailer import LogTailer
from agent.metrics_reporter import MetricsReporter
from agent.pattern_learner import PatternLearner


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def run(config: AgentConfig) -> None:
    """Main agent loop — blocks until SIGTERM/SIGINT."""
    _setup_logging(config.log_level)
    logger = logging.getLogger("agent")

    logger.info("AI SRE Agent v%s starting", config.agent_version)
    logger.info(
        "Service: %s | Namespace: %s | Pod: %s",
        config.service_name,
        config.pod_namespace,
        config.pod_name,
    )
    logger.info("Operator API: %s", config.operator_api_url)
    logger.info("Report interval: %ds", config.report_interval_secs)

    # Load error patterns
    detector = ErrorDetector.from_yaml(
        builtin_path=config.builtin_patterns_path(),
        custom_path=config.custom_patterns_path or None,
        ignore_patterns=config.ignore_patterns,
    )

    reporter = MetricsReporter(config)
    learner = PatternLearner(config)

    # -------------------------------------------------------------------------
    # Signal handling — graceful shutdown
    # -------------------------------------------------------------------------
    _stop_event = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        logger.info("Received signal %d — shutting down", signum)
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # -------------------------------------------------------------------------
    # Reporter thread
    # -------------------------------------------------------------------------
    def _report_loop() -> None:
        while not _stop_event.is_set():
            time.sleep(config.report_interval_secs)
            if _stop_event.is_set():
                break
            # Flush detected patterns into reporter
            detected = detector.flush()
            reporter.record_patterns(detected)
            novel = getattr(detector, "_novel_buffer", [])
            reporter.record_novel(list(novel))
            # Trigger send
            report = reporter._build_report()
            reporter._reset()
            reporter._flush_buffer()
            if not reporter._send(report):
                reporter._buffer(report)
                logger.warning("Report buffered (API unreachable)")
            else:
                logger.info(
                    "Report sent: errors=%d patterns=%d lines=%d",
                    report.error_count,
                    len(report.patterns_detected),
                    report.total_lines,
                )
            # Submit novel patterns to learning store (less frequently)
            if report.error_count > 0:
                learner.flush_to_api()

    reporter_thread = threading.Thread(target=_report_loop, name="reporter", daemon=True)
    reporter_thread.start()

    # -------------------------------------------------------------------------
    # Log tailing — main thread
    # -------------------------------------------------------------------------
    log_paths = config.effective_log_paths()
    logger.info("Tailing %d log path(s): %s", len(log_paths), log_paths)

    # Novel-error heuristic: lines with error keywords but no pattern match
    _ERROR_KEYWORDS = {"error", "exception", "fatal", "panic", "traceback", "critical"}

    def _tail_one(path: str) -> None:
        tailer = LogTailer(path, tail_lines=config.tail_lines)
        for line in tailer.lines():
            if _stop_event.is_set():
                break
            reporter.record_line(line)
            matches = detector.process_line(line)
            if not matches:
                # Check if it looks like an error — novel candidate
                low = line.lower()
                if any(kw in low for kw in _ERROR_KEYWORDS):
                    learner.observe(line)

    if len(log_paths) == 1:
        _tail_one(log_paths[0])
    elif len(log_paths) > 1:
        threads = []
        for path in log_paths:
            t = threading.Thread(target=_tail_one, args=(path,), name=f"tail:{path}", daemon=True)
            t.start()
            threads.append(t)
        _stop_event.wait()
    else:
        logger.warning("No log paths configured — agent is idle. Set LOG_PATH or LOG_PATHS.")
        _stop_event.wait()

    logger.info("Agent stopped")


def main() -> None:
    config = AgentConfig()
    run(config)


if __name__ == "__main__":
    main()
