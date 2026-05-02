"""Schedules — intentionally empty.

All triggers are now handled by sensors (pipeline/sensors/) which are
event-based and self-correcting when the machine sleeps. Cron schedules miss
windows silently; sensors catch up on the next daemon cycle.

This file is the escape hatch: add a ScheduleDefinition here if a sensor is
temporarily disabled and you need a guaranteed wall-clock trigger.
"""
