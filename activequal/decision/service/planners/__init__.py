"""Planner registry. Register new planners here by name."""

from __future__ import annotations

from .base import PlannerPlugin
from .gp_planner import GPPlanner
from .grid_planner import GridPlanner
from .random_planner import RandomPlanner
from .tpe_planner import TPEPlanner

PLANNER_REGISTRY: dict[str, PlannerPlugin] = {
    planner.name: planner for planner in (TPEPlanner(), GPPlanner(), RandomPlanner(), GridPlanner())
}

__all__ = ["PLANNER_REGISTRY", "PlannerPlugin"]
