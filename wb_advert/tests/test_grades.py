"""Tests for target-grade position helper (issue #7)."""

from __future__ import annotations

from wb_advert.optimizer.grades import position_meets_target


def test_position_meets_target_on_boundary():
    assert position_meets_target("top_1_3", 3) is True


def test_position_meets_target_better_than_goal():
    assert position_meets_target("top_1_3", 1) is True


def test_position_meets_target_worse_than_goal():
    assert position_meets_target("top_1_3", 110) is False


def test_position_meets_target_no_position():
    assert position_meets_target("top_1_3", None) is None


def test_position_meets_target_unknown_grade():
    assert position_meets_target("pos_20_plus", 5) is None
    assert position_meets_target(None, 5) is None
